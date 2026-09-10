import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import PreviewModal from "../components/PreviewModal";
import ApprovalCard from "../components/ApprovalCard";
import CompletionReport from "../components/CompletionReport";
import { downloadProjectZip } from "../utils/download";
import { detectTechStack, parseApiKeys, humanizeReport } from "../utils/techstack";

/*
 * Backend configuration
 *
 * Local:
 *   VITE_API_URL=http://localhost:8000
 *
 * Production:
 *   VITE_API_URL=https://verireview.onrender.com
 *
 * WebSocket protocol is converted explicitly:
 *   http://  -> ws://
 *   https:// -> wss://
 */
const API_BASE = (
  import.meta.env.VITE_API_URL || "http://localhost:8000"
).trim().replace(/\/+$/, "");

const WS_BASE = API_BASE
  .replace(/^https:\/\//i, "wss://")
  .replace(/^http:\/\//i, "ws://");

const STAGES = [
  {
    key: "plan",
    label: "Plan",
    match: "plan:",
    color: "#a78bfa",
    desc: "Product spec from your task",
  },
  {
    key: "architect",
    label: "Architect",
    match: "architect:",
    color: "#fb923c",
    desc: "APIs, pages, data model",
  },
  {
    key: "build",
    label: "Build",
    match: "build:",
    color: "#34d399",
    desc: "Backend + frontend code",
  },
  {
    key: "test",
    label: "Test",
    match: "test:",
    color: "#60a5fa",
    desc: "Cases + automated checks",
  },
  {
    key: "verify",
    label: "Verify",
    match: "verify:",
    color: "#2dd4bf",
    desc: "Requirements check",
  },
  {
    key: "review",
    label: "Review",
    match: "review:",
    color: "#fbbf24",
    desc: "Bugs, security, quality",
  },
  {
    key: "complete",
    label: "Complete",
    match: "complete:",
    color: "#f472b6",
    desc: "Docs, Docker, export",
  },
];

const STAGE_COLOR = Object.fromEntries(
  STAGES.map((stage) => [stage.key, stage.color])
);

const TABS = [
  "Overview",
  "Spec",
  "Architecture",
  "Backend",
  "Frontend",
  "Tests",
  "Verification",
  "Findings",
];

function detectStage(message) {
  const lower = (message || "").toLowerCase();

  if (
    lower.includes("sending back to coding agent") ||
    lower.includes("fail: review gate")
  ) {
    return "build";
  }

  for (let i = STAGES.length - 1; i >= 0; i -= 1) {
    if (lower.includes(STAGES[i].match)) {
      return STAGES[i].key;
    }
  }

  return "info";
}

function isFailMessage(message) {
  const lower = (message || "").toLowerCase();

  return (
    lower.includes("fail:") ||
    lower.includes("sending back to coding agent") ||
    lower.includes(": fail")
  );
}

function formatClock(date) {
  return date.toLocaleTimeString([], { hour12: false });
}

function formatDuration(ms) {
  const safeMs = Math.max(0, Number(ms) || 0);
  const seconds = Math.floor(safeMs / 1000);
  const minutes = Math.floor(seconds / 60);

  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  }

  return `${seconds}s`;
}

function StatusPill({ tone, children }) {
  return (
    <span className={`vr-status vr-status-${tone}`}>
      {children}
    </span>
  );
}

function StageDot({ status, color }) {
  const background =
    status === "done"
      ? "#34d399"
      : status === "running"
        ? color
        : "rgba(148,163,184,.25)";

  return (
    <span
      className={status === "running" ? "vr-pulse" : undefined}
      style={{
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background,
        flexShrink: 0,
        boxShadow:
          status === "running"
            ? `0 0 12px ${color}`
            : "none",
      }}
    />
  );
}

function buildPartial(task) {
  if (!task || task.error) {
    return null;
  }

  return {
    product_spec: task.product_spec,
    architecture: task.architecture,
    database_design: task.database_design,
    backend_code: task.backend_code,
    frontend_code: task.frontend_code,
    qa_notes: task.qa_notes,
    test_report: task.test_report,
    test_passed: task.test_passed,
    verification_report: task.verification_report,
    requirements_met: task.requirements_met,
    verified_findings: task.verified_findings,
    review_passed: task.review_passed,
    revision_count: task.revision_count,
    generation_failed: task.generation_failed,
    generation_error: task.generation_error,
    ai_status: task.ai_status,
    ai_error: task.ai_error,
    ai_failed_stage: task.ai_failed_stage,
  };
}

export default function Dashboard() {
  const { user } = useAuth();

  const ownerEmail = (user?.email || "").trim().toLowerCase();

  const ownerQuery = ownerEmail
    ? `?owner=${encodeURIComponent(ownerEmail)}`
    : "";

  const ownerHeaders = ownerEmail
    ? { "X-User-Email": ownerEmail }
    : {};

  const [task, setTask] = useState("");
  const [stackInput, setStackInput] = useState("");
  const [dbUrl, setDbUrl] = useState("");
  const [apiKeysText, setApiKeysText] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [entries, setEntries] = useState([]);
  const [partial, setPartial] = useState(null);
  const [result, setResult] = useState(null);

  const [stats, setStats] = useState({
    total_projects: 0,
    total_verified_findings: 0,
    total_revisions: 0,
  });

  const [runs, setRuns] = useState([]);

  const [autoScroll, setAutoScroll] = useState(true);
  const [activeTab, setActiveTab] = useState("Overview");

  const [startedAt, setStartedAt] = useState(null);
  const [finishedAt, setFinishedAt] = useState(null);
  const [now, setNow] = useState(Date.now());

  const [showPreview, setShowPreview] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewCode, setPreviewCode] = useState("");
  const [previewTaskId, setPreviewTaskId] = useState(null);

  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  const [approval, setApproval] = useState(null);
  const [deciding, setDeciding] = useState(false);

  const approvalResolveRef = useRef(null);
  const wsRef = useRef(null);
  const consoleRef = useRef(null);
  const idRef = useRef(0);

  /*
   * Refresh dashboard statistics and recent runs.
   */
  const refreshStats = useCallback(async () => {
    try {
      const [statsResponse, historyResponse] = await Promise.all([
        fetch(`${API_BASE}/stats${ownerQuery}`, {
          headers: ownerHeaders,
        }),

        fetch(`${API_BASE}/history${ownerQuery}`, {
          headers: ownerHeaders,
        }),
      ]);

      if (statsResponse.ok) {
        const statsData = await statsResponse.json();
        setStats(statsData);
      }

      if (historyResponse.ok) {
        const historyData = await historyResponse.json();

        if (Array.isArray(historyData)) {
          setRuns(historyData.slice(0, 5));
        }
      }
    } catch {
      // Backend may be sleeping/offline.
    }
  }, [ownerQuery, ownerEmail]);

  /*
   * Initial dashboard load.
   */
  useEffect(() => {
    refreshStats();

    return () => {
      try {
        wsRef.current?.close();
      } catch {
        // Ignore cleanup errors.
      }
    };
  }, [refreshStats]);

  /*
   * Elapsed timer while a workflow is running.
   */
  useEffect(() => {
    if (!loading) {
      return undefined;
    }

    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => clearInterval(timer);
  }, [loading]);

  /*
   * Auto-scroll live console.
   */
  useEffect(() => {
    if (autoScroll && consoleRef.current) {
      consoleRef.current.scrollTop =
        consoleRef.current.scrollHeight;
    }
  }, [entries, autoScroll]);

  /*
   * Add an entry to the live console.
   */
  const pushEntry = useCallback((message, stage) => {
    idRef.current += 1;

    const entry = {
      id: idRef.current,
      time: new Date(),
      stage: stage || detectStage(message),
      message,
      fail: isFailMessage(message),
    };

    setEntries((previous) => [...previous, entry]);
  }, []);

  /*
   * REST approval decision.
   *
   * Defined before runViaWebSocket/handleStart so all workflow
   * functions have a stable reference.
   */
  const decideRest = useCallback(
    async (runId, approved) => {
      setDeciding(true);

      try {
        pushEntry(
          approved
            ? "Approved — coding agent is fixing the files…"
            : "Skipped fixing — packaging the build…",
          "info"
        );

        const response = await fetch(`${API_BASE}/review/decide`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...ownerHeaders,
          },
          body: JSON.stringify({
            run_id: runId,
            approved,
            owner_email: ownerEmail || undefined,
          }),
        });

        if (!response.ok) {
          throw new Error(
            `Backend responded ${response.status}`
          );
        }

        const data = await response.json();

        if (data.error) {
          throw new Error(data.error);
        }

        return data;
      } finally {
        setDeciding(false);
      }
    },
    [ownerEmail, pushEntry]
  );

  /*
   * WebSocket workflow.
   *
   * Production:
   *   https://verireview.onrender.com
   *        ↓
   *   wss://verireview.onrender.com/ws/review
   *
   * Local:
   *   http://localhost:8000
   *        ↓
   *   ws://localhost:8000/ws/review
   */
  const runViaWebSocket = useCallback(
    (taskText, extras = {}) =>
      new Promise((resolve, reject) => {
        let settled = false;
        let timeoutId = null;

        const cleanup = () => {
          if (timeoutId) {
            clearTimeout(timeoutId);
            timeoutId = null;
          }

          if (wsRef.current === ws) {
            wsRef.current = null;
          }
        };

        const fail = (message) => {
          if (settled) {
            return;
          }

          settled = true;
          cleanup();

          try {
            ws.close();
          } catch {
            // Ignore close errors.
          }

          reject(new Error(message));
        };

        const succeed = (data) => {
          if (settled) {
            return;
          }

          settled = true;
          cleanup();

          try {
            ws.close();
          } catch {
            // Ignore close errors.
          }

          resolve(data);
        };

        /*
         * Explicitly use the already-normalized WebSocket URL.
         */
        const websocketUrl = `${WS_BASE}/ws/review`;

        let ws;

        try {
          ws = new WebSocket(websocketUrl);
        } catch {
          fail("Could not create the WebSocket connection.");
          return;
        }

        wsRef.current = ws;

        ws.onopen = () => {
          try {
            ws.send(
              JSON.stringify({
                task: taskText,
                owner_email:
                  ownerEmail || undefined,
                ...extras,
              })
            );
          } catch {
            fail("Could not send the task to the backend.");
          }
        };

        ws.onmessage = async (event) => {
          try {
            const msg = JSON.parse(event.data);

            if (msg.type === "step") {
              pushEntry(msg.message, msg.stage);

              if (msg.partial) {
                setPartial(msg.partial);
              }

              return;
            }

            if (msg.type === "awaiting_approval") {
              if (msg.partial) {
                setPartial(msg.partial);
              }

              pushEntry(
                `REVIEW: Initial verify + review done — waiting for your approval (run #${msg.run_id})…`,
                "review"
              );

              setApproval({
                mode: "ws",
                ...msg,
              });

              const approved = await new Promise((resolveApproval) => {
                approvalResolveRef.current =
                  resolveApproval;
              });

              approvalResolveRef.current = null;

              try {
                ws.send(
                  JSON.stringify({
                    action: approved ? "approve" : "skip",
                  })
                );
              } catch {
                // Backend may have closed the connection.
              }

              setApproval(null);
              return;
            }

            if (msg.type === "fixing") {
              pushEntry(
                "Approved — coding agent is fixing the files…",
                "info"
              );
              return;
            }

            if (msg.type === "approval_timeout") {
              fail(
                "Approval timed out. Resume it from History."
              );
              return;
            }

            if (msg.type === "done") {
              succeed(msg.result);
              return;
            }

            if (msg.type === "error") {
              fail(
                msg.message || "Workflow failed"
              );
            }
          } catch (parseError) {
            fail(
              parseError?.message ||
                "Invalid response received from backend."
            );
          }
        };

        ws.onerror = () => {
          /*
           * This intentionally rejects so handleStart()
           * can use the REST fallback.
           */
          fail(
            "WebSocket connection failed. Falling back to REST."
          );
        };

        ws.onclose = () => {
          /*
           * A normal close after receiving "done" is expected.
           * If the connection closes before the workflow settles,
           * let the REST fallback handle it.
           */
          if (!settled) {
            fail(
              "WebSocket connection closed before the workflow completed."
            );
          }
        };

        /*
         * Safety timeout.
         */
        timeoutId = window.setTimeout(() => {
          fail(
            "WebSocket timed out after 30 minutes. Check History — a pending run can be resumed."
          );
        }, 1000 * 60 * 30);
      }),
    [ownerEmail, pushEntry]
  );

  /*
   * Start workflow.
   */
  const handleStart = async (event) => {
    event.preventDefault();

    const taskText = task.trim();

    if (!taskText || loading) {
      return;
    }

    const detectedStacks = detectTechStack(taskText);

    const effectiveStack =
      stackInput.trim() ||
      detectedStacks.join(" + ");

    const apiKeys = parseApiKeys(apiKeysText);

    const extras = {
      tech_stack: effectiveStack || undefined,
      db_url: dbUrl.trim() || undefined,
      api_keys:
        Object.keys(apiKeys).length > 0
          ? apiKeys
          : undefined,
    };

    setLoading(true);
    setError("");
    setEntries([]);
    setPartial(null);
    setResult(null);
    setApproval(null);
    setDownloadError("");
    setActiveTab("Overview");
    setStartedAt(new Date());
    setFinishedAt(null);
    setNow(Date.now());

    pushEntry(`USER TASK: ${taskText}`, "info");

    try {
      let data;

      /*
       * First attempt:
       * WebSocket live workflow.
       */
      try {
        data = await runViaWebSocket(
          taskText,
          extras
        );
      } catch (wsError) {
        /*
         * WebSocket failed.
         *
         * Continue automatically through REST.
         */
        pushEntry(
          "WebSocket unavailable — running via REST with approval gate…",
          "info"
        );

        const phase1Response = await fetch(
          `${API_BASE}/review/phase1`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...ownerHeaders,
            },
            body: JSON.stringify({
              task: taskText,
              owner_email:
                ownerEmail || undefined,
              ...extras,
            }),
          }
        );

        if (!phase1Response.ok) {
          throw new Error(
            `Backend responded ${phase1Response.status}`
          );
        }

        const pending =
          await phase1Response.json();

        if (pending.error) {
          throw new Error(pending.error);
        }

        /*
         * Load the generated work for the approval screen.
         */
        try {
          const taskResponse = await fetch(
            `${API_BASE}/task/${pending.run_id}${ownerQuery}`,
            {
              headers: ownerHeaders,
            }
          );

          if (taskResponse.ok) {
            const taskData =
              await taskResponse.json();

            if (!taskData.error) {
              setPartial({
                ...buildPartial(taskData),
                review_passed:
                  pending.review_passed,
              });

              pushEntry(
                `REVIEW: Initial verify + review done — waiting for your approval (run #${pending.run_id})…`,
                "review"
              );
            }
          }
        } catch {
          // Partial view is best effort.
        }

        /*
         * Show approval card.
         */
        setApproval({
          mode: "rest",
          ...pending,
        });

        const approved =
          await new Promise((resolveApproval) => {
            approvalResolveRef.current =
              resolveApproval;
          });

        approvalResolveRef.current = null;
        setApproval(null);

        data = await decideRest(
          pending.run_id,
          approved
        );

        setPartial(buildPartial(data));
      }

      /*
       * Final result.
       */
      setResult(data);
      setFinishedAt(new Date());

      await refreshStats();
    } catch (workflowError) {
      setError(
        workflowError?.message ||
          "Failed to run workflow. Check that the backend is available."
      );

      setFinishedAt(new Date());
    } finally {
      setLoading(false);
    }
  };

  /*
   * Copy live console logs.
   */
  const copyLogs = async () => {
    const text = entries
      .map(
        (entry) =>
          `[${formatClock(entry.time)}] [${entry.stage.toUpperCase()}] ${entry.message}`
      )
      .join("\n");

    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard may be unavailable.
    }
  };

  /*
   * Download generated project.
   */
  const handleDownload = async (taskId) => {
    if (!taskId || downloading) {
      return;
    }

    setDownloading(true);
    setDownloadError("");

    try {
      await downloadProjectZip({
        taskId,
        ownerQuery,
        ownerHeaders,
      });
    } catch (downloadException) {
      setDownloadError(
        downloadException?.message ||
          "Download failed. Is the backend running?"
      );
    } finally {
      setDownloading(false);
    }
  };

  /*
   * Preview helper.
   */
  const openPreviewForCode = ({
    code,
    title,
    taskId,
  }) => {
    setPreviewCode(code || "");
    setPreviewTitle(title || "");
    setPreviewTaskId(taskId ?? null);
    setShowPreview(true);
  };

  /*
   * Preview current result.
   */
  const handlePreviewCurrent = () => {
    const code = live?.frontend_code || "";

    openPreviewForCode({
      code,
      title: result
        ? `Run #${result.id} preview`
        : "Current run preview",
      taskId: result?.id ?? null,
    });
  };

  /*
   * Preview a historical run.
   */
  const handlePreviewRun = async (run) => {
    try {
      const response = await fetch(
        `${API_BASE}/task/${run.id}${ownerQuery}`,
        {
          headers: ownerHeaders,
        }
      );

      if (!response.ok) {
        throw new Error(
          `Backend responded ${response.status}`
        );
      }

      const data = await response.json();

      if (data.error) {
        throw new Error("Project not found");
      }

      openPreviewForCode({
        code: data.frontend_code || "",
        title: `Run #${run.id} preview`,
        taskId: run.id,
      });
    } catch (previewError) {
      setError(
        previewError?.message ||
          "Could not load preview."
      );
    }
  };

  /*
   * Approval button.
   */
  const handleApprovalDecision = async (
    approved
  ) => {
    if (!approval || deciding) {
      return;
    }

    /*
     * WebSocket mode:
     * resolve the Promise waiting inside runViaWebSocket().
     */
    if (approval.mode === "ws") {
      const resolver =
        approvalResolveRef.current;

      approvalResolveRef.current = null;
      setApproval(null);

      if (resolver) {
        resolver(approved);
      }

      return;
    }

    /*
     * REST mode:
     * call /review/decide directly.
     */
    const runId =
      approval.runId ?? approval.run_id;

    setApproval(null);
    setLoading(true);

    try {
      const data = await decideRest(
        runId,
        approved
      );

      setResult(data);
      setPartial(buildPartial(data));
      setFinishedAt(new Date());

      await refreshStats();

      setSearchParams({});
    } catch (decisionError) {
      setError(
        decisionError?.message ||
          "Could not complete the run."
      );

      setFinishedAt(new Date());
    } finally {
      setLoading(false);
    }
  };

  /*
   * Resume a paused approval run.
   */
  useEffect(() => {
    const resumeId =
      searchParams.get("resume");

    if (!resumeId) {
      return undefined;
    }

    let cancelled = false;

    (async () => {
      try {
        const response = await fetch(
          `${API_BASE}/review/pending/${resumeId}${ownerQuery}`,
          {
            headers: ownerHeaders,
          }
        );

        if (!response.ok) {
          return;
        }

        const pending =
          await response.json();

        if (
          cancelled ||
          pending.error
        ) {
          return;
        }

        try {
          const taskResponse =
            await fetch(
              `${API_BASE}/task/${pending.run_id}${ownerQuery}`,
              {
                headers: ownerHeaders,
              }
            );

          if (taskResponse.ok) {
            const taskData =
              await taskResponse.json();

            if (
              !taskData.error &&
              !cancelled
            ) {
              setPartial({
                ...buildPartial(taskData),
                review_passed:
                  pending.review_passed,
              });
            }
          }
        } catch {
          // Best effort.
        }

        if (!cancelled) {
          setApproval({
            mode: "rest",
            ...pending,
          });

          setStartedAt(new Date());
          setFinishedAt(null);
        }
      } catch {
        // Ignore resume errors.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [searchParams, ownerQuery]);

  /*
   * Derive stage statuses from console messages.
   */
  const stageStatus = useMemo(() => {
    return STAGES.map((stage) => {
      const hits = entries.filter(
        (entry) =>
          entry.stage === stage.key
      );

      let status = "waiting";

      if (hits.length > 0) {
        status = "done";
      }

      const lastOverall =
        entries[entries.length - 1];

      if (
        loading &&
        lastOverall &&
        lastOverall.stage === stage.key
      ) {
        status = "running";
      }

      if (
        !loading &&
        entries.length > 0 &&
        lastOverall &&
        lastOverall.stage === stage.key &&
        stage.key !== "complete"
      ) {
        status = "done";
      }

      const failHit = hits.find(
        (hit) => hit.fail
      );

      return {
        ...stage,
        status,
        count: hits.length,
        last:
          hits[hits.length - 1] || null,
        failed:
          !!failHit && status !== "done",
      };
    });
  }, [entries, loading]);

  const doneCount = stageStatus.filter(
    (stage) => stage.status === "done"
  ).length;

  const progress = Math.round(
    (doneCount / STAGES.length) * 100
  );

  const elapsed = startedAt
    ? formatDuration(
        (finishedAt || now) -
          startedAt.getTime()
      )
    : "—";

  const live = result || partial;

  const findings =
    result?.verified_findings ||
    partial?.verified_findings ||
    [];

  const reviewPassed = result
    ? result.review_passed !== false &&
      findings.length === 0
    : null;

  /*
   * Split backend output into files using FILE markers.
   */
  const backendFiles = useMemo(() => {
    const code = live?.backend_code || "";

    const output = {};
    let current = null;
    const buffer = [];

    const markerFor = (line) => {
      const trimmed = line.trim();

      for (const prefix of [
        "// FILE:",
        "# FILE:",
      ]) {
        if (trimmed.startsWith(prefix)) {
          return trimmed
            .slice(prefix.length)
            .trim();
        }
      }

      return null;
    };

    for (const line of code.split("\n")) {
      const marker = markerFor(line);

      if (marker) {
        if (current) {
          output[current] =
            buffer.join("\n").trim();
        }

        current = marker;
        buffer.length = 0;
      } else {
        buffer.push(line);
      }
    }

    if (current) {
      output[current] =
        buffer.join("\n").trim();
    }

    return output;
  }, [live]);

  /*
   * Work viewer tabs.
   */
  const renderTab = () => {
    if (!live) {
      return (
        <div
          style={{
            color: "#475569",
            fontSize: "13px",
          }}
        >
          Run the workflow to see each
          agent&apos;s output here, live.
        </div>
      );
    }

    const renderPre = (text) => (
      <pre className="vr-code">
        {text || "—"}
      </pre>
    );

    switch (activeTab) {
      case "Spec":
        return renderPre(live.product_spec);

      case "Architecture":
        return renderPre(
          `${live.architecture || ""}\n\n${
            live.database_design
              ? `Data model:\n${live.database_design}`
              : ""
          }`
        );

      case "Backend": {
        const names =
          Object.keys(backendFiles);

        if (!names.length) {
          return renderPre(
            live.backend_code
          );
        }

        return (
          <div
            style={{
              display: "grid",
              gap: "10px",
            }}
          >
            {names.map((name) => (
              <div key={name}>
                <div
                  style={{
                    color: "#a5b4fc",
                    fontSize: "12px",
                    fontWeight: 700,
                    marginBottom: "6px",
                  }}
                >
                  {name}
                </div>

                <pre className="vr-code">
                  {backendFiles[name].slice(
                    0,
                    4000
                  )}
                </pre>
              </div>
            ))}
          </div>
        );
      }

      case "Frontend":
        return renderPre(
          (live.frontend_code || "").slice(
            0,
            6000
          )
        );

      case "Tests":
        return (
          <div>
            {typeof live.test_passed ===
              "boolean" && (
              <div
                style={{
                  marginBottom: "10px",
                }}
              >
                <StatusPill
                  tone={
                    live.test_passed
                      ? "success"
                      : "danger"
                  }
                >
                  TEST{" "}
                  {live.test_passed
                    ? "PASS"
                    : "FAIL"}
                </StatusPill>
              </div>
            )}

            {renderPre(
              humanizeReport(
                live.test_report ||
                  live.qa_notes
              )
            )}
          </div>
        );

      case "Verification":
        return (
          <div>
            {typeof live.requirements_met ===
              "boolean" && (
              <div
                style={{
                  marginBottom: "10px",
                }}
              >
                <StatusPill
                  tone={
                    live.requirements_met
                      ? "success"
                      : "danger"
                  }
                >
                  VERIFY{" "}
                  {live.requirements_met
                    ? "PASS"
                    : "FAIL"}
                </StatusPill>
              </div>
            )}

            {renderPre(
              humanizeReport(
                live.verification_report
              )
            )}
          </div>
        );

      case "Findings":
        if (!findings.length) {
          return (
            <div
              style={{
                color: "#6ee7b7",
                fontSize: "13px",
              }}
            >
              No confirmed findings —
              review PASS.
            </div>
          );
        }

        return (
          <div
            style={{
              display: "grid",
              gap: "8px",
            }}
          >
            {findings.map((finding, index) => (
              <div
                key={index}
                className="vr-finding"
                style={{
                  padding: "14px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent:
                      "space-between",
                    gap: "8px",
                  }}
                >
                  <strong
                    style={{
                      color: "#e2e8f0",
                      fontSize: "13px",
                    }}
                  >
                    {finding.category}
                  </strong>

                  <StatusPill
                    tone={
                      finding.severity ===
                      "high"
                        ? "danger"
                        : finding.severity ===
                            "medium"
                          ? "warning"
                          : "info"
                    }
                  >
                    {finding.severity}
                  </StatusPill>
                </div>

                <div className="vr-finding-location">
                  {finding.file}
                </div>

                <div className="vr-finding-description">
                  {finding.issue}
                </div>

                {finding.verification && (
                  <div
                    style={{
                      color: "#475569",
                      fontSize: "11px",
                      marginTop: "6px",
                    }}
                  >
                    Verified:{" "}
                    {finding.verification}
                  </div>
                )}
              </div>
            ))}
          </div>
        );

      default:
        return (
          <div
            style={{
              display: "grid",
              gap: "10px",
            }}
          >
            <div
              style={{
                display: "flex",
                gap: "8px",
                flexWrap: "wrap",
              }}
            >
              {typeof live.test_passed ===
                "boolean" && (
                <StatusPill
                  tone={
                    live.test_passed
                      ? "success"
                      : "danger"
                  }
                >
                  TEST{" "}
                  {live.test_passed
                    ? "PASS"
                    : "FAIL"}
                </StatusPill>
              )}

              {typeof live.requirements_met ===
                "boolean" && (
                <StatusPill
                  tone={
                    live.requirements_met
                      ? "success"
                      : "danger"
                  }
                >
                  VERIFY{" "}
                  {live.requirements_met
                    ? "PASS"
                    : "FAIL"}
                </StatusPill>
              )}

              <StatusPill
                tone={
                  findings.length
                    ? "warning"
                    : "success"
                }
              >
                REVIEW {findings.length}{" "}
                finding(s)
              </StatusPill>

              {(live.revision_count ?? 0) >
                0 && (
                <StatusPill tone="info">
                  Revision{" "}
                  {live.revision_count}
                </StatusPill>
              )}
            </div>

            <div
              style={{
                color: "#94a3b8",
                fontSize: "13px",
                lineHeight: 1.7,
              }}
            >
              {humanizeReport(
                live.product_spec || ""
              ).slice(0, 500) ||
                "Agent output streams here as each stage completes…"}
            </div>
          </div>
        );
    }
  };

  return (
    <div className="vr-page">
      <main className="vr-dashboard">
        <div className="vr-container">

          {/* Header */}
          <div className="vr-dashboard-header">
            <div>
              <div className="vr-section-label">
                <span
                  style={{
                    width: "6px",
                    height: "6px",
                    borderRadius: "50%",
                    background: "#34d399",
                  }}
                />
                Engineering workspace
              </div>

              <h1 className="vr-dashboard-title">
                Agent Workspace
              </h1>

              <p className="vr-dashboard-subtitle">
                Describe a task once — agents
                plan, build, test, verify, review,
                fix and package it.
              </p>
            </div>

            <Link
              to="/history"
              className="vr-button vr-button-secondary"
            >
              View history
            </Link>
          </div>

          {/* Stats */}
          <div className="vr-dashboard-grid">
            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Total projects
              </div>

              <div className="vr-stat-value">
                {String(
                  stats.total_projects ?? 0
                ).padStart(2, "0")}
              </div>

              <StatusPill tone="info">
                All time
              </StatusPill>
            </div>

            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Verified findings
              </div>

              <div className="vr-stat-value">
                {String(
                  stats.total_verified_findings ??
                    0
                ).padStart(2, "0")}
              </div>

              <StatusPill
                tone={
                  findings.length > 0
                    ? "warning"
                    : "success"
                }
              >
                {findings.length > 0
                  ? "Needs attention"
                  : "Clean"}
              </StatusPill>
            </div>

            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Elapsed
              </div>

              <div
                className="vr-stat-value"
                style={{
                  fontSize: "24px",
                }}
              >
                {elapsed}
              </div>

              <StatusPill
                tone={
                  loading
                    ? "warning"
                    : "info"
                }
              >
                {loading
                  ? "Running"
                  : finishedAt
                    ? "Finished"
                    : "Idle"}
              </StatusPill>
            </div>

            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Last run
              </div>

              <div
                className="vr-stat-value"
                style={{
                  fontSize: "22px",
                }}
              >
                {result
                  ? reviewPassed
                    ? "PASS"
                    : "FAIL"
                  : loading
                    ? `${progress}%`
                    : "—"}
              </div>

              <StatusPill
                tone={
                  result
                    ? reviewPassed
                      ? "success"
                      : "danger"
                    : loading
                      ? "warning"
                      : "warning"
                }
              >
                {loading
                  ? "Running"
                  : result
                    ? reviewPassed
                      ? "Verified"
                      : "Fix needed"
                    : "Idle"}
              </StatusPill>
            </div>
          </div>

          {/* Task composer */}
          <div
            className="vr-card"
            style={{
              marginTop: "20px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent:
                  "space-between",
                gap: "16px",
                marginBottom: "14px",
                flexWrap: "wrap",
              }}
            >
              <div>
                <div className="vr-section-label">
                  New engineering task
                </div>

                <h2
                  style={{
                    margin:
                      "8px 0 6px",
                    color: "#f8fafc",
                    fontSize: "20px",
                  }}
                >
                  What should the agents
                  build?
                </h2>
              </div>

              <StatusPill
                tone={
                  loading
                    ? "warning"
                    : "info"
                }
              >
                {loading
                  ? `Running — ${progress}%`
                  : "Ready"}
              </StatusPill>
            </div>

            <form onSubmit={handleStart}>
              <textarea
                className="vr-task-input"
                value={task}
                onChange={(event) =>
                  setTask(event.target.value)
                }
                rows={5}
                style={{
                  minHeight: "120px",
                }}
                placeholder="Build a Spring Boot REST API with JWT authentication, PostgreSQL, role-based access control, and a React dashboard for managing employees."
                aria-label="Engineering task"
              />

              {(() => {
                const detected =
                  detectTechStack(task);

                return (
                  <div
                    style={{
                      display: "grid",
                      gap: "10px",
                      marginTop: "12px",
                    }}
                  >
                    <div>
                      <label
                        htmlFor="vr-tech-stack"
                        style={{
                          display: "block",
                          color: "#cbd5e1",
                          fontSize: "12px",
                          fontWeight: 600,
                          marginBottom:
                            "6px",
                        }}
                      >
                        Tech stack
                      </label>

                      <input
                        id="vr-tech-stack"
                        className="vr-input"
                        value={stackInput}
                        onChange={(event) =>
                          setStackInput(
                            event.target.value
                          )
                        }
                        placeholder={
                          detected.length
                            ? `Detected: ${detected.join(
                                " + "
                              )} (edit if needed)`
                            : "e.g. Spring Boot + React + PostgreSQL (blank = auto)"
                        }
                        aria-label="Tech stack"
                      />

                      <div
                        style={{
                          color: "#475569",
                          fontSize: "11px",
                          marginTop: "5px",
                        }}
                      >
                        {detected.length ? (
                          <>
                            Detected from your
                            task:{" "}
                            <span
                              style={{
                                color: "#a5b4fc",
                              }}
                            >
                              {detected.join(
                                ", "
                              )}
                            </span>{" "}
                            — no need to type
                            it, or override
                            above.
                          </>
                        ) : (
                          "Mention the stack in your task or type it here — otherwise agents default to Spring Boot + React."
                        )}
                      </div>
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns:
                          "minmax(0, 1fr) minmax(0, 1fr)",
                        gap: "10px",
                      }}
                    >
                      <div>
                        <label
                          htmlFor="vr-db-url"
                          style={{
                            display: "block",
                            color: "#cbd5e1",
                            fontSize: "12px",
                            fontWeight: 600,
                            marginBottom:
                              "6px",
                          }}
                        >
                          Database URL
                        </label>

                        <input
                          id="vr-db-url"
                          className="vr-input"
                          value={dbUrl}
                          onChange={(event) =>
                            setDbUrl(
                              event.target.value
                            )
                          }
                          placeholder="postgresql://user:pass@host:5432/db"
                          autoComplete="off"
                          aria-label="Database URL"
                        />
                      </div>

                      <div>
                        <label
                          htmlFor="vr-api-keys"
                          style={{
                            display: "block",
                            color: "#cbd5e1",
                            fontSize: "12px",
                            fontWeight: 600,
                            marginBottom:
                              "6px",
                          }}
                        >
                          API keys (one
                          KEY=value per line)
                        </label>

                        <textarea
                          id="vr-api-keys"
                          className="vr-input"
                          value={apiKeysText}
                          onChange={(event) =>
                            setApiKeysText(
                              event.target.value
                            )
                          }
                          placeholder={
                            "OPENAI_API_KEY=sk-...\nSTRIPE_KEY=..."
                          }
                          rows={2}
                          style={{
                            height: "48px",
                            resize: "vertical",
                            fontFamily:
                              "monospace",
                            fontSize: "12px",
                          }}
                          autoComplete="off"
                          aria-label="API keys"
                        />
                      </div>
                    </div>

                    <div
                      style={{
                        color: "#475569",
                        fontSize: "11px",
                      }}
                    >
                      Asked every run — baked
                      into the ZIP&apos;s `.env`
                      (never shown to other
                      users). Leave blank to
                      use placeholders.
                    </div>
                  </div>
                );
              })()}

              <div
                style={{
                  display: "flex",
                  justifyContent:
                    "space-between",
                  gap: "12px",
                  marginTop: "12px",
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    color: "#475569",
                    fontSize: "11px",
                  }}
                >
                  Streams live over
                  WebSocket, REST fallback.
                </span>

                <button
                  type="submit"
                  className="vr-button vr-button-primary"
                  disabled={
                    !task.trim() || loading
                  }
                  style={{
                    opacity:
                      !task.trim() || loading
                        ? 0.5
                        : 1,
                  }}
                >
                  {loading
                    ? "Running agents…"
                    : "Start agent workflow"}
                </button>
              </div>
            </form>

            {error && (
              <div
                role="alert"
                style={{
                  marginTop: "12px",
                  padding: "12px",
                  borderRadius: "10px",
                  border:
                    "1px solid rgba(248,113,113,.25)",
                  background:
                    "rgba(248,113,113,.07)",
                  color: "#fca5a5",
                  fontSize: "12px",
                }}
              >
                {error}
              </div>
            )}
          </div>

          {/* Approval gate */}
          {approval && (
            <ApprovalCard
              approval={approval}
              deciding={deciding}
              onApprove={() =>
                handleApprovalDecision(true)
              }
              onSkip={() =>
                handleApprovalDecision(false)
              }
            />
          )}

          {/* Pending approval */}
          {!approval &&
            !loading &&
            runs.some(
              (run) =>
                run.status ===
                "awaiting_approval"
            ) && (
              <div
                className="vr-card"
                style={{
                  marginTop: "20px",
                  border:
                    "1px solid rgba(251,191,36,.3)",
                  background:
                    "linear-gradient(145deg, rgba(251,191,36,.07), rgba(255,255,255,.02))",
                }}
              >
                {(() => {
                  const pendingRun =
                    runs.find(
                      (run) =>
                        run.status ===
                        "awaiting_approval"
                    );

                  if (!pendingRun) {
                    return null;
                  }

                  return (
                    <div
                      style={{
                        display: "flex",
                        justifyContent:
                          "space-between",
                        gap: "16px",
                        flexWrap: "wrap",
                        alignItems:
                          "center",
                      }}
                    >
                      <div>
                        <div
                          className="vr-section-label"
                          style={{
                            color:
                              "#fcd34d",
                          }}
                        >
                          Waiting for your
                          approval
                        </div>

                        <h2
                          style={{
                            margin:
                              "7px 0 6px",
                            color:
                              "#f8fafc",
                            fontSize:
                              "18px",
                          }}
                        >
                          Run #{pendingRun.id}{" "}
                          finished review —
                          approve the fix to
                          continue
                        </h2>

                        <div
                          style={{
                            color:
                              "#94a3b8",
                            fontSize:
                              "12px",
                          }}
                        >
                          {(
                            pendingRun.task ||
                            ""
                          ).slice(0, 100)}
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() =>
                          setSearchParams({
                            resume: String(
                              pendingRun.id
                            ),
                          })
                        }
                        className="vr-button vr-button-primary"
                        style={{
                          padding:
                            "10px 16px",
                          fontSize:
                            "13px",
                        }}
                      >
                        Review &amp; approve
                        →
                      </button>
                    </div>
                  );
                })()}
              </div>
            )}

          {/* Completion result */}
          {result &&
            !loading &&
            !approval && (
              <div
                className="vr-card"
                style={{
                  marginTop: "20px",
                  border:
                    result.generation_failed
                      ? "1px solid rgba(248,113,113,.3)"
                      : "1px solid rgba(52,211,153,.25)",
                  background:
                    result.generation_failed
                      ? "linear-gradient(145deg, rgba(248,113,113,.07), rgba(255,255,255,.02))"
                      : "linear-gradient(145deg, rgba(52,211,153,.08), rgba(255,255,255,.02))",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent:
                      "space-between",
                    gap: "16px",
                    flexWrap: "wrap",
                    alignItems:
                      "center",
                  }}
                >
                  <div>
                    <div
                      className="vr-section-label"
                      style={{
                        color:
                          result.generation_failed
                            ? "#fca5a5"
                            : "#6ee7b7",
                      }}
                    >
                      {result.generation_failed
                        ? "Task failed — AI unavailable"
                        : "Task complete — final verify + review"}
                    </div>

                    <h2
                      style={{
                        margin:
                          "7px 0 6px",
                        color:
                          "#f8fafc",
                        fontSize:
                          "18px",
                      }}
                    >
                      {result.generation_failed
                        ? `Run #${result.id} could not be generated — AI unavailable`
                        : result.test_passed &&
                            result.requirements_met &&
                            (
                              result.verified_findings ||
                              []
                            ).length === 0
                          ? `No bugs or errors — run #${result.id} is verified clean`
                          : `Run #${result.id} finished with ${(result.verified_findings || []).length} remaining issue(s)`}
                    </h2>

                    <div
                      style={{
                        display: "flex",
                        gap: "8px",
                        flexWrap: "wrap",
                        marginTop: "8px",
                      }}
                    >
                      <StatusPill
                        tone={
                          result.test_passed
                            ? "success"
                            : "danger"
                        }
                      >
                        TEST{" "}
                        {result.test_passed
                          ? "PASS"
                          : "FAIL"}
                      </StatusPill>

                      <StatusPill
                        tone={
                          result.requirements_met
                            ? "success"
                            : "danger"
                        }
                      >
                        VERIFY{" "}
                        {result.requirements_met
                          ? "PASS"
                          : "FAIL"}
                      </StatusPill>

                      <StatusPill
                        tone={
                          (
                            result.verified_findings ||
                            []
                          ).length
                            ? "warning"
                            : "success"
                        }
                      >
                        REVIEW{" "}
                        {
                          (
                            result.verified_findings ||
                            []
                          ).length
                        }{" "}
                        finding(s)
                      </StatusPill>

                      {(result.revision_count ??
                        0) > 0 && (
                        <StatusPill tone="info">
                          {
                            result.revision_count
                          }{" "}
                          fix round(s)
                          approved
                        </StatusPill>
                      )}
                    </div>

                    <div
                      style={{
                        color:
                          "#94a3b8",
                        fontSize:
                          "12px",
                        marginTop:
                          "8px",
                      }}
                    >
                      {result.tech_stack && (
                        <span
                          style={{
                            color:
                              "#a5b4fc",
                          }}
                        >
                          {
                            result.tech_stack
                          }{" "}
                          ·{" "}
                        </span>
                      )}

                      {result.generation_failed
                        ? result.generation_error ||
                          result.ai_error ||
                          "AI was unavailable. Fix the provider quota/key issue and run the task again."
                        : result.test_passed &&
                            result.requirements_met &&
                            (
                              result.verified_findings ||
                              []
                            ).length === 0
                          ? "Verified clean — proceed to the downloadable ZIP below."
                          : (
                                result.revision_count ??
                                0
                              ) > 0
                            ? "Best-effort build packaged after the approved fix rounds."
                            : "Finished without fixing — no fix rounds were applied."}
                    </div>

                    {downloadError && (
                      <div
                        style={{
                          color:
                            "#fca5a5",
                          fontSize:
                            "12px",
                          marginTop:
                            "8px",
                        }}
                      >
                        {downloadError}
                      </div>
                    )}
                  </div>

                  <div
                    style={{
                      display: "flex",
                      gap: "10px",
                      flexWrap: "wrap",
                    }}
                  >
                    <button
                      type="button"
                      onClick={() =>
                        handleDownload(
                          result.id
                        )
                      }
                      disabled={downloading}
                      className="vr-button vr-button-primary"
                      style={{
                        padding:
                          "10px 16px",
                        fontSize:
                          "13px",
                        opacity:
                          downloading
                            ? 0.6
                            : 1,
                      }}
                    >
                      {downloading
                        ? "Preparing ZIP…"
                        : "Download ZIP"}
                    </button>

                    <button
                      type="button"
                      onClick={
                        handlePreviewCurrent
                      }
                      className="vr-button vr-button-secondary"
                      style={{
                        padding:
                          "10px 16px",
                        fontSize:
                          "13px",
                      }}
                    >
                      Watch preview
                    </button>

                    <Link
                      to="/review"
                      className="vr-button vr-button-secondary"
                      style={{
                        padding:
                          "10px 16px",
                        fontSize:
                          "13px",
                      }}
                    >
                      Open review
                    </Link>
                  </div>
                </div>
              </div>
            )}

          {result &&
            !loading &&
            !approval && (
              <CompletionReport
                result={result}
              />
            )}

          {/* Live run */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "minmax(0, 1fr) minmax(0, 1.2fr)",
              gap: "20px",
              marginTop: "20px",
            }}
            className="vr-run-grid"
          >
            {/* Agent tracker */}
            <div className="vr-card">
              <div
                style={{
                  display: "flex",
                  justifyContent:
                    "space-between",
                  alignItems: "center",
                  marginBottom: "6px",
                }}
              >
                <div>
                  <div className="vr-section-label">
                    Live agents
                  </div>

                  <h2
                    style={{
                      margin:
                        "7px 0 0",
                      color:
                        "#f8fafc",
                      fontSize:
                        "18px",
                    }}
                  >
                    Completion status
                  </h2>
                </div>

                <StatusPill
                  tone={
                    loading
                      ? "warning"
                      : entries.length
                        ? "success"
                        : "info"
                  }
                >
                  {loading
                    ? "Running"
                    : entries.length
                      ? "Done"
                      : "Idle"}
                </StatusPill>
              </div>

              {/* Progress */}
              <div
                style={{
                  margin:
                    "14px 0 6px",
                  display: "flex",
                  justifyContent:
                    "space-between",
                  fontSize: "11px",
                  color: "#64748b",
                }}
              >
                <span>
                  {doneCount}/
                  {STAGES.length}{" "}
                  stages complete
                </span>

                <span>
                  {progress}%
                </span>
              </div>

              <div className="vr-progress-track">
                <div
                  className="vr-progress-fill"
                  style={{
                    width: `${progress}%`,
                  }}
                />
              </div>

              <div
                style={{
                  display: "grid",
                  gap: "8px",
                  marginTop: "14px",
                }}
              >
                {stageStatus.map(
                  (stage, index) => (
                    <div
                      key={stage.key}
                      className={
                        stage.status ===
                        "running"
                          ? "vr-stage-running"
                          : undefined
                      }
                      style={{
                        display:
                          "flex",
                        gap: "12px",
                        padding:
                          "11px 13px",
                        borderRadius:
                          "11px",
                        border:
                          stage.status ===
                          "running"
                            ? `1px solid ${stage.color}55`
                            : "1px solid rgba(255,255,255,.05)",
                        background:
                          stage.status ===
                          "running"
                            ? `${stage.color}11`
                            : "rgba(255,255,255,.018)",
                      }}
                    >
                      <div
                        style={{
                          display:
                            "flex",
                          flexDirection:
                            "column",
                          alignItems:
                            "center",
                          gap: "4px",
                        }}
                      >
                        <StageDot
                          status={
                            stage.status
                          }
                          color={
                            stage.color
                          }
                        />

                        <span
                          style={{
                            color:
                              "#475569",
                            fontSize:
                              "10px",
                            fontWeight:
                              700,
                          }}
                        >
                          {String(
                            index + 1
                          ).padStart(
                            2,
                            "0"
                          )}
                        </span>
                      </div>

                      <div
                        style={{
                          flex: 1,
                          minWidth: 0,
                        }}
                      >
                        <div
                          style={{
                            display:
                              "flex",
                            justifyContent:
                              "space-between",
                            gap: "8px",
                            alignItems:
                              "center",
                          }}
                        >
                          <span
                            style={{
                              color:
                                "#e2e8f0",
                              fontSize:
                                "13px",
                              fontWeight:
                                600,
                            }}
                          >
                            {
                              stage.label
                            }
                          </span>

                          <span
                            style={{
                              fontSize:
                                "10px",
                              fontWeight:
                                700,
                              letterSpacing:
                                ".06em",
                              color:
                                stage.status ===
                                "done"
                                  ? "#6ee7b7"
                                  : stage.status ===
                                      "running"
                                    ? stage.color
                                    : "#475569",
                            }}
                          >
                            {stage.status ===
                            "done"
                              ? "DONE"
                              : stage.status ===
                                  "running"
                                ? "RUNNING"
                                : "QUEUED"}
                          </span>
                        </div>

                        <div
                          style={{
                            color:
                              "#475569",
                            fontSize:
                              "11px",
                          }}
                        >
                          {
                            stage.desc
                          }
                        </div>

                        {stage.last && (
                          <div
                            style={{
                              color:
                                "#94a3b8",
                              fontSize:
                                "11px",
                              marginTop:
                                "4px",
                              overflow:
                                "hidden",
                              textOverflow:
                                "ellipsis",
                              whiteSpace:
                                "nowrap",
                            }}
                          >
                            {
                              stage.last
                                .message
                            }
                          </div>
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>
            </div>

            {/* Console */}
            <div
              className="vr-card"
              style={{
                padding: 0,
                overflow: "hidden",
              }}
            >
              <div className="vr-console-header">
                <div
                  style={{
                    display: "flex",
                    gap: "6px",
                  }}
                >
                  <span
                    className="vr-console-dot"
                    style={{
                      background:
                        "#f87171",
                    }}
                  />

                  <span
                    className="vr-console-dot"
                    style={{
                      background:
                        "#fbbf24",
                    }}
                  />

                  <span
                    className="vr-console-dot"
                    style={{
                      background:
                        "#34d399",
                    }}
                  />
                </div>

                <span
                  style={{
                    color:
                      "#94a3b8",
                    fontSize:
                      "12px",
                    fontWeight:
                      600,
                  }}
                >
                  agent console — live{" "}
                  {loading
                    ? "(running)"
                    : entries.length
                      ? "(finished)"
                      : "(idle)"}
                </span>

                <div
                  style={{
                    display: "flex",
                    gap: "8px",
                    alignItems:
                      "center",
                  }}
                >
                  <button
                    type="button"
                    onClick={() =>
                      setAutoScroll(
                        (value) =>
                          !value
                      )
                    }
                    className="vr-console-btn"
                  >
                    {autoScroll
                      ? "Auto-scroll on"
                      : "Auto-scroll off"}
                  </button>

                  <button
                    type="button"
                    onClick={copyLogs}
                    className="vr-console-btn"
                  >
                    Copy
                  </button>
                </div>
              </div>

              <div
                ref={consoleRef}
                className="vr-console"
              >
                {entries.length ===
                  0 && (
                  <div
                    style={{
                      color:
                        "#475569",
                      fontSize:
                        "12px",
                    }}
                  >
                    $ waiting for
                    task… describe
                    what the agents
                    should build
                    above.
                  </div>
                )}

                {entries.map(
                  (entry) => (
                    <div
                      key={entry.id}
                      className="vr-console-line"
                    >
                      <span className="vr-console-time">
                        {formatClock(
                          entry.time
                        )}
                      </span>

                      <span
                        className="vr-console-stage"
                        style={{
                          color:
                            STAGE_COLOR[
                              entry.stage
                            ] ||
                            "#94a3b8",
                          borderColor:
                            `${
                              STAGE_COLOR[
                                entry.stage
                              ] ||
                              "#94a3b8"
                            }44`,
                          background:
                            `${
                              STAGE_COLOR[
                                entry.stage
                              ] ||
                              "#94a3b8"
                            }11`,
                        }}
                      >
                        {entry.stage.toUpperCase()}
                      </span>

                      <span
                        style={{
                          color:
                            entry.fail
                              ? "#fca5a5"
                              : "#cbd5e1",
                        }}
                      >
                        {entry.message}
                      </span>
                    </div>
                  )
                )}

                {loading && (
                  <div className="vr-console-cursor">
                    $ ▊
                  </div>
                )}
              </div>

              <div className="vr-console-footer">
                {entries.length} log
                line(s) · elapsed{" "}
                {elapsed}

                {result && (
                  <span
                    style={{
                      marginLeft:
                        "8px",
                    }}
                  >
                    · TEST{" "}
                    {result.test_passed
                      ? "PASS"
                      : "FAIL"}{" "}
                    · VERIFY{" "}
                    {result.requirements_met
                      ? "PASS"
                      : "FAIL"}{" "}
                    ·{" "}
                    {
                      findings.length
                    }{" "}
                    finding(s)
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Work viewer */}
          <div
            className="vr-card"
            style={{
              marginTop: "20px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent:
                  "space-between",
                gap: "12px",
                flexWrap: "wrap",
                alignItems:
                  "center",
              }}
            >
              <div>
                <div className="vr-section-label">
                  Work produced
                </div>

                <h2
                  style={{
                    margin:
                      "7px 0 0",
                    color:
                      "#f8fafc",
                    fontSize:
                      "18px",
                  }}
                >
                  See what the agents
                  did
                </h2>
              </div>

              {result && (
                <div
                  style={{
                    display: "flex",
                    gap: "10px",
                    flexWrap:
                      "wrap",
                  }}
                >
                  <Link
                    to="/review"
                    className="vr-button vr-button-secondary"
                    style={{
                      padding:
                        "9px 13px",
                      fontSize:
                        "12px",
                    }}
                  >
                    Open review
                  </Link>

                  <button
                    type="button"
                    onClick={
                      handlePreviewCurrent
                    }
                    className="vr-button vr-button-secondary"
                    style={{
                      padding:
                        "9px 13px",
                      fontSize:
                        "12px",
                    }}
                  >
                    Watch preview
                  </button>

                  <button
                    type="button"
                    onClick={() =>
                      handleDownload(
                        result.id
                      )
                    }
                    disabled={
                      downloading
                    }
                    className="vr-button vr-button-primary"
                    style={{
                      padding:
                        "9px 13px",
                      fontSize:
                        "12px",
                    }}
                  >
                    {downloading
                      ? "Preparing…"
                      : "Download ZIP"}
                  </button>
                </div>
              )}
            </div>

            <div className="vr-tabs">
              {TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  onClick={() =>
                    setActiveTab(tab)
                  }
                  className={`vr-tab${
                    activeTab === tab
                      ? " vr-tab-active"
                      : ""
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div
              style={{
                marginTop: "12px",
              }}
            >
              {renderTab()}
            </div>
          </div>

          {/* Recent runs */}
          <div
            className="vr-card"
            style={{
              marginTop: "20px",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent:
                  "space-between",
                alignItems:
                  "center",
                gap: "12px",
              }}
            >
              <div>
                <div className="vr-section-label">
                  Workspace activity
                </div>

                <h2
                  style={{
                    margin:
                      "7px 0 0",
                    color:
                      "#f8fafc",
                    fontSize:
                      "18px",
                  }}
                >
                  Recent engineering
                  runs
                </h2>
              </div>

              <Link
                to="/history"
                className="vr-button vr-button-secondary"
                style={{
                  padding:
                    "9px 13px",
                  fontSize:
                    "12px",
                }}
              >
                View history
              </Link>
            </div>

            {runs.length === 0 ? (
              <div
                style={{
                  marginTop: "16px",
                  padding: "22px",
                  textAlign:
                    "center",
                  border:
                    "1px dashed rgba(255,255,255,.07)",
                  borderRadius:
                    "11px",
                  color:
                    "#64748b",
                  fontSize:
                    "12px",
                }}
              >
                No completed runs
                yet.
              </div>
            ) : (
              <div
                style={{
                  marginTop: "12px",
                  display: "grid",
                  gap: "8px",
                }}
              >
                {runs.map((run) => (
                  <div
                    key={run.id}
                    style={{
                      display: "flex",
                      justifyContent:
                        "space-between",
                      gap: "12px",
                      padding:
                        "12px 14px",
                      borderRadius:
                        "10px",
                      border:
                        "1px solid rgba(255,255,255,.06)",
                      flexWrap:
                        "wrap",
                      alignItems:
                        "center",
                    }}
                  >
                    <div
                      style={{
                        color:
                          "#e2e8f0",
                        fontSize:
                          "13px",
                        flex:
                          "1 1 220px",
                        minWidth: 0,
                      }}
                    >
                      #{run.id} —{" "}
                      {(run.task || "")
                        .slice(
                          0,
                          80
                        )}

                      <div
                        style={{
                          color:
                            "#475569",
                          fontSize:
                            "11px",
                          marginTop:
                            "4px",
                        }}
                      >
                        {run.created_at
                          ? new Date(
                              run.created_at
                            ).toLocaleString()
                          : ""}{" "}
                        ·{" "}
                        {
                          run.verified_findings_count ??
                          0
                        }{" "}
                        findings ·{" "}
                        {
                          run.revision_count ??
                          0
                        }{" "}
                        revisions
                      </div>
                    </div>

                    <div
                      style={{
                        display:
                          "flex",
                        gap: "8px",
                        alignItems:
                          "center",
                        flexWrap:
                          "wrap",
                      }}
                    >
                      <StatusPill
                        tone={
                          run.status ===
                          "completed"
                            ? "success"
                            : run.status ===
                                "awaiting_approval"
                              ? "warning"
                              : "info"
                        }
                      >
                        {run.status ===
                        "awaiting_approval"
                          ? "needs approval"
                          : run.status}
                      </StatusPill>

                      {run.status ===
                      "awaiting_approval" ? (
                        <Link
                          to={`/dashboard?resume=${run.id}`}
                          className="vr-console-btn"
                        >
                          Resume
                        </Link>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() =>
                              handlePreviewRun(
                                run
                              )
                            }
                            className="vr-console-btn"
                          >
                            Preview
                          </button>

                          <button
                            type="button"
                            onClick={() =>
                              handleDownload(
                                run.id
                              )
                            }
                            className="vr-console-btn"
                          >
                            ZIP
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </main>

      <PreviewModal
        open={showPreview}
        title={previewTitle}
        frontendCode={previewCode}
        downloading={downloading}
        onClose={() =>
          setShowPreview(false)
        }
        onDownload={
          previewTaskId
            ? () =>
                handleDownload(
                  previewTaskId
                )
            : undefined
        }
      />
    </div>
  );
}