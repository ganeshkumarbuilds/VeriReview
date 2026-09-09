import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import PreviewModal from "../components/PreviewModal";
import ApprovalCard from "../components/ApprovalCard";
import CompletionReport from "../components/CompletionReport";
import { downloadProjectZip } from "../utils/download";
import { detectTechStack, parseApiKeys, humanizeReport } from "../utils/techstack";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const STAGES = [
  { key: "plan", label: "Plan", match: "plan:", color: "#a78bfa", desc: "Product spec from your task" },
  { key: "architect", label: "Architect", match: "architect:", color: "#fb923c", desc: "APIs, pages, data model" },
  { key: "build", label: "Build", match: "build:", color: "#34d399", desc: "Backend + frontend code" },
  { key: "test", label: "Test", match: "test:", color: "#60a5fa", desc: "Cases + automated checks" },
  { key: "verify", label: "Verify", match: "verify:", color: "#2dd4bf", desc: "Requirements check" },
  { key: "review", label: "Review", match: "review:", color: "#fbbf24", desc: "Bugs, security, quality" },
  { key: "complete", label: "Complete", match: "complete:", color: "#f472b6", desc: "Docs, Docker, export" },
];

const STAGE_COLOR = Object.fromEntries(STAGES.map((s) => [s.key, s.color]));

function detectStage(message) {
  const lower = (message || "").toLowerCase();
  if (lower.includes("sending back to coding agent") || lower.includes("fail: review gate")) return "build";
  for (let i = STAGES.length - 1; i >= 0; i--) {
    if (lower.includes(STAGES[i].match)) return STAGES[i].key;
  }
  return "info";
}

function isFailMessage(message) {
  const lower = (message || "").toLowerCase();
  return lower.includes("fail:") || lower.includes("sending back to coding agent") || lower.includes(": fail");
}

function formatClock(date) {
  return date.toLocaleTimeString([], { hour12: false });
}

function formatDuration(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

function StatusPill({ tone, children }) {
  return <span className={`vr-status vr-status-${tone}`}>{children}</span>;
}

function StageDot({ status, color }) {
  const bg =
    status === "done" ? "#34d399" : status === "running" ? color : "rgba(148,163,184,.25)";
  return (
    <span
      className={status === "running" ? "vr-pulse" : undefined}
      style={{
        width: "10px", height: "10px", borderRadius: "50%",
        background: bg, flexShrink: 0,
        boxShadow: status === "running" ? `0 0 12px ${color}` : "none",
      }}
    />
  );
}

const TABS = ["Overview", "Spec", "Architecture", "Backend", "Frontend", "Tests", "Verification", "Findings"];

export default function Dashboard() {
  const { user } = useAuth();
  const ownerEmail = (user?.email || "").trim().toLowerCase();
  const ownerQuery = ownerEmail ? `?owner=${encodeURIComponent(ownerEmail)}` : "";
  const ownerHeaders = ownerEmail ? { "X-User-Email": ownerEmail } : {};
  const [task, setTask] = useState("");
  const [stackInput, setStackInput] = useState("");
  const [dbUrl, setDbUrl] = useState("");
  const [apiKeysText, setApiKeysText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [entries, setEntries] = useState([]);
  const [partial, setPartial] = useState(null);
  const [result, setResult] = useState(null);
  const [stats, setStats] = useState({ total_projects: 0, total_verified_findings: 0, total_revisions: 0 });
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
  const [searchParams, setSearchParams] = useSearchParams();
  const wsRef = useRef(null);
  const consoleRef = useRef(null);
  const idRef = useRef(0);

  const refreshStats = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([
        fetch(`${API_BASE}/stats${ownerQuery}`, { headers: ownerHeaders }).then((r) => (r.ok ? r.json() : null)),
        fetch(`${API_BASE}/history${ownerQuery}`, { headers: ownerHeaders }).then((r) => (r.ok ? r.json() : null)),
      ]);
      if (s) setStats(s);
      if (Array.isArray(h)) setRuns(h.slice(0, 5));
    } catch { /* backend offline */ }
  }, [ownerQuery]);

  useEffect(() => {
    refreshStats();
    return () => { try { wsRef.current?.close(); } catch { /* noop */ } };
  }, [refreshStats]);

  useEffect(() => {
    if (!loading) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [loading]);

  useEffect(() => {
    if (autoScroll && consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [entries, autoScroll]);

  const pushEntry = useCallback((message, stage) => {
    idRef.current += 1;
    const entry = {
      id: idRef.current,
      time: new Date(),
      stage: stage || detectStage(message),
      message,
      fail: isFailMessage(message),
    };
    setEntries((prev) => [...prev, entry]);
  }, []);

  const runViaWebSocket = (taskText, extras = {}) =>
    new Promise((resolve, reject) => {
      let settled = false;
      const ws = new WebSocket(API_BASE.replace("http", "ws") + "/ws/review");
      wsRef.current = ws;
      ws.onopen = () => ws.send(JSON.stringify({ task: taskText, owner_email: ownerEmail || undefined, ...extras }));
      ws.onmessage = async (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "step") {
            pushEntry(msg.message, msg.stage);
            if (msg.partial) setPartial(msg.partial);
          } else if (msg.type === "awaiting_approval") {
            if (msg.partial) setPartial(msg.partial);
            pushEntry(`REVIEW: Initial verify + review done — waiting for your approval (run #${msg.run_id})…`, "review");
            setApproval({ mode: "ws", ...msg });
            const approved = await new Promise((res) => { approvalResolveRef.current = res; });
            approvalResolveRef.current = null;
            try { ws.send(JSON.stringify({ action: approved ? "approve" : "skip" })); } catch { /* noop */ }
            setApproval(null);
          } else if (msg.type === "fixing") {
            pushEntry("Approved — coding agent is fixing the files…", "info");
          } else if (msg.type === "approval_timeout") {
            settled = true;
            ws.close();
            reject(new Error("Approval timed out. Resume it from History."));
          } else if (msg.type === "done") {
            settled = true;
            ws.close();
            resolve(msg.result);
          } else if (msg.type === "error") {
            settled = true;
            ws.close();
            reject(new Error(msg.message || "Workflow failed"));
          }
        } catch (e) {
          if (!settled) { settled = true; ws.close(); reject(e); }
        }
      };
      ws.onerror = () => {
        if (!settled) { settled = true; try { ws.close(); } catch { /* noop */ } reject(new Error("WebSocket failed")); }
      };
      setTimeout(() => {
        if (!settled) { settled = true; try { ws.close(); } catch { /* noop */ } reject(new Error("WebSocket timed out after 30 min. Check History — a pending run can be resumed.")); }
      }, 1000 * 60 * 30);
    });

  const handleStart = async (event) => {
    event.preventDefault();
    const taskText = task.trim();
    if (!taskText || loading) return;
    const detectedStacks = detectTechStack(taskText);
    const effectiveStack = stackInput.trim() || detectedStacks.join(" + ");
    const apiKeys = parseApiKeys(apiKeysText);
    const extras = {
      tech_stack: effectiveStack || undefined,
      db_url: dbUrl.trim() || undefined,
      api_keys: Object.keys(apiKeys).length ? apiKeys : undefined,
    };
    setLoading(true);
    setError("");
    setEntries([]);
    setPartial(null);
    setResult(null);
    setActiveTab("Overview");
    setStartedAt(new Date());
    setFinishedAt(null);
    pushEntry(`USER TASK: ${taskText}`, "info");
    try {
      let data;
      try {
        data = await runViaWebSocket(taskText, extras);
      } catch (wsError) {
        // REST fallback keeps the same approval gate: phase 1, ask user, then decide.
        pushEntry("WebSocket unavailable — running via REST with approval gate…", "info");
        const p1Res = await fetch(`${API_BASE}/review/phase1`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...ownerHeaders },
          body: JSON.stringify({ task: taskText, owner_email: ownerEmail || undefined, ...extras }),
        });
        if (!p1Res.ok) throw new Error(`Backend responded ${p1Res.status}`);
        const pending = await p1Res.json();
        if (pending.error) throw new Error(pending.error);
        try {
          const tRes = await fetch(`${API_BASE}/task/${pending.run_id}${ownerQuery}`, { headers: ownerHeaders });
          if (tRes.ok) {
            const t = await tRes.json();
            if (!t.error) {
              setPartial({
                product_spec: t.product_spec, architecture: t.architecture,
                database_design: t.database_design, backend_code: t.backend_code,
                frontend_code: t.frontend_code, qa_notes: t.qa_notes,
                test_report: t.test_report, test_passed: t.test_passed,
                verification_report: t.verification_report, requirements_met: t.requirements_met,
                verified_findings: t.verified_findings, review_passed: pending.review_passed,
                revision_count: t.revision_count,
              });
              pushEntry(`REVIEW: Initial verify + review done — waiting for your approval (run #${pending.run_id})…`, "review");
            }
          }
        } catch { /* partial view is best-effort */ }
        setApproval({ mode: "rest", ...pending });
        const approved = await new Promise((res) => { approvalResolveRef.current = res; });
        approvalResolveRef.current = null;
        setApproval(null);
        data = await decideRest(pending.run_id, approved);
        setPartial({
          product_spec: data.product_spec, architecture: data.architecture,
          database_design: data.database_design, backend_code: data.backend_code,
          frontend_code: data.frontend_code, qa_notes: data.qa_notes,
          test_report: data.test_report, test_passed: data.test_passed,
          verification_report: data.verification_report, requirements_met: data.requirements_met,
          verified_findings: data.verified_findings, review_passed: data.review_passed,
          revision_count: data.revision_count,
        });
      }
      setResult(data);
      setFinishedAt(new Date());
      refreshStats();
    } catch (e) {
      setError(e.message || "Failed to run workflow. Is the backend running on :8000?");
      setFinishedAt(new Date());
    } finally {
      setLoading(false);
    }
  };

  const copyLogs = async () => {
    const text = entries.map((e) => `[${formatClock(e.time)}] [${e.stage.toUpperCase()}] ${e.message}`).join("\n");
    try { await navigator.clipboard.writeText(text); } catch { /* clipboard unavailable */ }
  };

  const handleDownload = async (taskId) => {
    if (!taskId || downloading) return;
    setDownloading(true);
    setDownloadError("");
    try {
      await downloadProjectZip({ taskId, ownerQuery, ownerHeaders });
    } catch (e) {
      setDownloadError(e.message || "Download failed. Is the backend running?");
    } finally {
      setDownloading(false);
    }
  };

  const openPreviewForCode = ({ code, title, taskId }) => {
    setPreviewCode(code || "");
    setPreviewTitle(title || "");
    setPreviewTaskId(taskId ?? null);
    setShowPreview(true);
  };

  const handlePreviewCurrent = () => {
    const code = live?.frontend_code || "";
    openPreviewForCode({ code, title: result ? `Run #${result.id} preview` : "Current run preview", taskId: result?.id ?? null });
  };

  const handlePreviewRun = async (run) => {
    try {
      const res = await fetch(`${API_BASE}/task/${run.id}${ownerQuery}`, { headers: ownerHeaders });
      if (!res.ok) throw new Error(`Backend responded ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error("Project not found");
      openPreviewForCode({ code: data.frontend_code || "", title: `Run #${run.id} preview`, taskId: run.id });
    } catch (e) {
      setError(e.message || "Could not load preview");
    }
  };

  const decideRest = async (runId, approved) => {
    setDeciding(true);
    try {
      pushEntry(approved ? "Approved — coding agent is fixing the files…" : "Skipped fixing — packaging the build…", "info");
      const res = await fetch(`${API_BASE}/review/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...ownerHeaders },
        body: JSON.stringify({ run_id: runId, approved, owner_email: ownerEmail || undefined }),
      });
      if (!res.ok) throw new Error(`Backend responded ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      return data;
    } finally {
      setDeciding(false);
    }
  };

  const handleApprovalDecision = async (approved) => {
    if (!approval || deciding) return;
    if (approval.mode === "ws") {
      const r = approvalResolveRef.current;
      approvalResolveRef.current = null;
      setApproval(null);
      if (r) r(approved);
      return;
    }
    // REST mode (fallback or resumed run): decide via API, then show final result.
    const runId = approval.runId ?? approval.run_id;
    setApproval(null);
    setLoading(true);
    try {
      const data = await decideRest(runId, approved);
      setResult(data);
      setPartial({
        product_spec: data.product_spec, architecture: data.architecture,
        database_design: data.database_design, backend_code: data.backend_code,
        frontend_code: data.frontend_code, qa_notes: data.qa_notes,
        test_report: data.test_report, test_passed: data.test_passed,
        verification_report: data.verification_report, requirements_met: data.requirements_met,
        verified_findings: data.verified_findings, review_passed: data.review_passed,
        revision_count: data.revision_count,
      });
      setFinishedAt(new Date());
      refreshStats();
      setSearchParams({});
    } catch (e) {
      setError(e.message || "Could not complete the run");
      setFinishedAt(new Date());
    } finally {
      setLoading(false);
    }
  };

  // Resume a paused run (e.g. from History → Resume): load its review result
  // and show the same approval card.
  useEffect(() => {
    const resumeId = searchParams.get("resume");
    if (!resumeId) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/review/pending/${resumeId}${ownerQuery}`, { headers: ownerHeaders });
        if (!res.ok) return;
        const pending = await res.json();
        if (cancelled || pending.error) return;
        try {
          const tRes = await fetch(`${API_BASE}/task/${pending.run_id}${ownerQuery}`, { headers: ownerHeaders });
          if (tRes.ok) {
            const t = await tRes.json();
            if (!t.error && !cancelled) {
              setPartial({
                product_spec: t.product_spec, architecture: t.architecture,
                database_design: t.database_design, backend_code: t.backend_code,
                frontend_code: t.frontend_code, qa_notes: t.qa_notes,
                test_report: t.test_report, test_passed: t.test_passed,
                verification_report: t.verification_report, requirements_met: t.requirements_met,
                verified_findings: t.verified_findings, review_passed: pending.review_passed,
                revision_count: t.revision_count,
              });
            }
          }
        } catch { /* best-effort */ }
        if (!cancelled) {
          setApproval({ mode: "rest", ...pending });
          setStartedAt(new Date());
        }
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, [searchParams, ownerQuery]);

  // Per-stage status derived from console entries
  const stageStatus = useMemo(() => {
    return STAGES.map((s) => {
      const hits = entries.filter((e) => e.stage === s.key);
      let status = "waiting";
      if (hits.length > 0) status = "done";
      const lastOverall = entries[entries.length - 1];
      if (loading && lastOverall && lastOverall.stage === s.key) status = "running";
      if (!loading && entries.length > 0 && lastOverall && lastOverall.stage === s.key && s.key !== "complete") {
        // keep last active stage as done once finished
        status = "done";
      }
      const failHit = hits.find((h) => h.fail);
      return { ...s, status, count: hits.length, last: hits[hits.length - 1] || null, failed: !!failHit && status !== "done" ? true : false };
    });
  }, [entries, loading]);

  const doneCount = stageStatus.filter((s) => s.status === "done").length;
  const progress = Math.round((doneCount / STAGES.length) * 100);
  const elapsed = startedAt ? formatDuration((finishedAt || now) - startedAt.getTime()) : "—";
  const live = result || partial;
  const findings = result?.verified_findings || partial?.verified_findings || [];
  const reviewPassed = result ? (result.review_passed !== false && findings.length === 0) : null;

  const backendFiles = useMemo(() => {
    const code = live?.backend_code || "";
    const out = {};
    let current = null;
    const buf = [];
    const markerFor = (line) => {
      const t = line.trim();
      for (const prefix of ["// FILE:", "# FILE:"]) {
        if (t.startsWith(prefix)) return t.slice(prefix.length).trim();
      }
      return null;
    };
    for (const line of code.split("\n")) {
      const marker = markerFor(line);
      if (marker) {
        if (current) out[current] = buf.join("\n").trim();
        current = marker;
        buf.length = 0;
      } else buf.push(line);
    }
    if (current) out[current] = buf.join("\n").trim();
    return out;
  }, [live]);

  const renderTab = () => {
    if (!live) return <div style={{ color: "#475569", fontSize: "13px" }}>Run the workflow to see each agent&apos;s output here, live.</div>;
    const pre = (text) => (
      <pre className="vr-code">{text || "—"}</pre>
    );
    switch (activeTab) {
      case "Spec": return pre(live.product_spec);
      case "Architecture": return pre(`${live.architecture || ""}\n\n${live.database_design ? `Data model:\n${live.database_design}` : ""}`);
      case "Backend": {
        const names = Object.keys(backendFiles);
        if (!names.length) return pre(live.backend_code);
        return (
          <div style={{ display: "grid", gap: "10px" }}>
            {names.map((n) => (
              <div key={n}>
                <div style={{ color: "#a5b4fc", fontSize: "12px", fontWeight: 700, marginBottom: "6px" }}>{n}</div>
                <pre className="vr-code">{backendFiles[n].slice(0, 4000)}</pre>
              </div>
            ))}
          </div>
        );
      }
      case "Frontend": return pre((live.frontend_code || "").slice(0, 6000));
      case "Tests": return (
        <div>
          {typeof live.test_passed === "boolean" && (
            <div style={{ marginBottom: "10px" }}>
              <StatusPill tone={live.test_passed ? "success" : "danger"}>TEST {live.test_passed ? "PASS" : "FAIL"}</StatusPill>
            </div>
          )}
          {pre(humanizeReport(live.test_report || live.qa_notes))}
        </div>
      );
      case "Verification": return (
        <div>
          {typeof live.requirements_met === "boolean" && (
            <div style={{ marginBottom: "10px" }}>
              <StatusPill tone={live.requirements_met ? "success" : "danger"}>VERIFY {live.requirements_met ? "PASS" : "FAIL"}</StatusPill>
            </div>
          )}
          {pre(humanizeReport(live.verification_report))}
        </div>
      );
      case "Findings":
        if (!findings.length) return <div style={{ color: "#6ee7b7", fontSize: "13px" }}>No confirmed findings — review PASS.</div>;
        return (
          <div style={{ display: "grid", gap: "8px" }}>
            {findings.map((f, i) => (
              <div key={i} className="vr-finding" style={{ padding: "14px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: "8px" }}>
                  <strong style={{ color: "#e2e8f0", fontSize: "13px" }}>{f.category}</strong>
                  <StatusPill tone={f.severity === "high" ? "danger" : f.severity === "medium" ? "warning" : "info"}>{f.severity}</StatusPill>
                </div>
                <div className="vr-finding-location">{f.file}</div>
                <div className="vr-finding-description">{f.issue}</div>
                {f.verification && <div style={{ color: "#475569", fontSize: "11px", marginTop: "6px" }}>Verified: {f.verification}</div>}
              </div>
            ))}
          </div>
        );
      default:
        return (
          <div style={{ display: "grid", gap: "10px" }}>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
              {typeof live.test_passed === "boolean" && <StatusPill tone={live.test_passed ? "success" : "danger"}>TEST {live.test_passed ? "PASS" : "FAIL"}</StatusPill>}
              {typeof live.requirements_met === "boolean" && <StatusPill tone={live.requirements_met ? "success" : "danger"}>VERIFY {live.requirements_met ? "PASS" : "FAIL"}</StatusPill>}
              <StatusPill tone={findings.length ? "warning" : "success"}>REVIEW {findings.length} finding(s)</StatusPill>
              {(live.revision_count ?? 0) > 0 && <StatusPill tone="info">Revision {live.revision_count}</StatusPill>}
            </div>
            <div style={{ color: "#94a3b8", fontSize: "13px", lineHeight: 1.7 }}>
              {(humanizeReport(live.product_spec || "").slice(0, 500)) || "Agent output streams here as each stage completes…"}
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
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#34d399" }} />
                Engineering workspace
              </div>
              <h1 className="vr-dashboard-title">Agent Workspace</h1>
              <p className="vr-dashboard-subtitle">
                Describe a task once — agents plan, build, test, verify, review, fix and package it.
              </p>
            </div>
            <Link to="/history" className="vr-button vr-button-secondary">View history</Link>
          </div>

          {/* Stats */}
          <div className="vr-dashboard-grid">
            <div className="vr-stat-card">
              <div className="vr-stat-label">Total projects</div>
              <div className="vr-stat-value">{String(stats.total_projects ?? 0).padStart(2, "0")}</div>
              <StatusPill tone="info">All time</StatusPill>
            </div>
            <div className="vr-stat-card">
              <div className="vr-stat-label">Verified findings</div>
              <div className="vr-stat-value">{String(stats.total_verified_findings ?? 0).padStart(2, "0")}</div>
              <StatusPill tone={findings.length > 0 ? "warning" : "success"}>{findings.length > 0 ? "Needs attention" : "Clean"}</StatusPill>
            </div>
            <div className="vr-stat-card">
              <div className="vr-stat-label">Elapsed</div>
              <div className="vr-stat-value" style={{ fontSize: "24px" }}>{elapsed}</div>
              <StatusPill tone={loading ? "warning" : "info"}>{loading ? "Running" : finishedAt ? "Finished" : "Idle"}</StatusPill>
            </div>
            <div className="vr-stat-card">
              <div className="vr-stat-label">Last run</div>
              <div className="vr-stat-value" style={{ fontSize: "22px" }}>
                {result ? (reviewPassed ? "PASS" : "FAIL") : loading ? `${progress}%` : "—"}
              </div>
              <StatusPill tone={result ? (reviewPassed ? "success" : "danger") : loading ? "warning" : "warning"}>
                {loading ? "Running" : result ? (reviewPassed ? "Verified" : "Fix needed") : "Idle"}
              </StatusPill>
            </div>
          </div>

          {/* Task composer */}
          <div className="vr-card" style={{ marginTop: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", marginBottom: "14px", flexWrap: "wrap" }}>
              <div>
                <div className="vr-section-label">New engineering task</div>
                <h2 style={{ margin: "8px 0 6px", color: "#f8fafc", fontSize: "20px" }}>What should the agents build?</h2>
              </div>
              <StatusPill tone={loading ? "warning" : "info"}>{loading ? `Running — ${progress}%` : "Ready"}</StatusPill>
            </div>
            <form onSubmit={handleStart}>
              <textarea
                className="vr-task-input"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                rows={5}
                style={{ minHeight: "120px" }}
                placeholder="Build a Spring Boot REST API with JWT authentication, PostgreSQL, role-based access control, and a React dashboard for managing employees."
                aria-label="Engineering task"
              />
              {(() => {
                const detected = detectTechStack(task);
                return (
                  <div style={{ display: "grid", gap: "10px", marginTop: "12px" }}>
                    <div>
                      <label htmlFor="vr-tech-stack" style={{ display: "block", color: "#cbd5e1", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>
                        Tech stack
                      </label>
                      <input
                        id="vr-tech-stack"
                        className="vr-input"
                        value={stackInput}
                        onChange={(e) => setStackInput(e.target.value)}
                        placeholder={detected.length ? `Detected: ${detected.join(" + ")} (edit if needed)` : "e.g. Spring Boot + React + PostgreSQL (blank = auto)"}
                        aria-label="Tech stack"
                      />
                      <div style={{ color: "#475569", fontSize: "11px", marginTop: "5px" }}>
                        {detected.length
                          ? <>Detected from your task: <span style={{ color: "#a5b4fc" }}>{detected.join(", ")}</span> — no need to type it, or override above.</>
                          : "Mention the stack in your task or type it here — otherwise agents default to Spring Boot + React."}
                      </div>
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "10px" }}>
                      <div>
                        <label htmlFor="vr-db-url" style={{ display: "block", color: "#cbd5e1", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>
                          Database URL
                        </label>
                        <input
                          id="vr-db-url"
                          className="vr-input"
                          value={dbUrl}
                          onChange={(e) => setDbUrl(e.target.value)}
                          placeholder="postgresql://user:pass@host:5432/db"
                          autoComplete="off"
                          aria-label="Database URL"
                        />
                      </div>
                      <div>
                        <label htmlFor="vr-api-keys" style={{ display: "block", color: "#cbd5e1", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>
                          API keys (one KEY=value per line)
                        </label>
                        <textarea
                          id="vr-api-keys"
                          className="vr-input"
                          value={apiKeysText}
                          onChange={(e) => setApiKeysText(e.target.value)}
                          placeholder={"OPENAI_API_KEY=sk-...\nSTRIPE_KEY=..."}
                          rows={2}
                          style={{ height: "48px", resize: "vertical", fontFamily: "monospace", fontSize: "12px" }}
                          autoComplete="off"
                          aria-label="API keys"
                        />
                      </div>
                    </div>
                    <div style={{ color: "#475569", fontSize: "11px" }}>
                      Asked every run — baked into the ZIP&apos;s `.env` (never shown to other users). Leave blank to use placeholders.
                    </div>
                  </div>
                );
              })()}
              <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", marginTop: "12px", flexWrap: "wrap", alignItems: "center" }}>
                <span style={{ color: "#475569", fontSize: "11px" }}>Streams live over WebSocket, REST fallback.</span>
                <button type="submit" className="vr-button vr-button-primary" disabled={!task.trim() || loading} style={{ opacity: !task.trim() || loading ? 0.5 : 1 }}>
                  {loading ? "Running agents…" : "Start agent workflow"}
                </button>
              </div>
            </form>
            {error && (
              <div role="alert" style={{ marginTop: "12px", padding: "12px", borderRadius: "10px", border: "1px solid rgba(248,113,113,.25)", background: "rgba(248,113,113,.07)", color: "#fca5a5", fontSize: "12px" }}>
                {error}
              </div>
            )}
          </div>

          {/* Approval gate: verify + review result, user permits the fix */}
          {approval && (
            <ApprovalCard
              approval={approval}
              deciding={deciding}
              onApprove={() => handleApprovalDecision(true)}
              onSkip={() => handleApprovalDecision(false)}
            />
          )}

          {/* Pending approval from an earlier run (e.g. after refresh): resume it */}
          {!approval && !loading && runs.some((r) => r.status === "awaiting_approval") && (
            <div className="vr-card" style={{ marginTop: "20px", border: "1px solid rgba(251,191,36,.3)", background: "linear-gradient(145deg, rgba(251,191,36,.07), rgba(255,255,255,.02))" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
                <div>
                  <div className="vr-section-label" style={{ color: "#fcd34d" }}>Waiting for your approval</div>
                  <h2 style={{ margin: "7px 0 6px", color: "#f8fafc", fontSize: "18px" }}>
                    Run #{runs.find((r) => r.status === "awaiting_approval").id} finished review — approve the fix to continue
                  </h2>
                  <div style={{ color: "#94a3b8", fontSize: "12px" }}>
                    {(runs.find((r) => r.status === "awaiting_approval").task || "").slice(0, 100)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setSearchParams({ resume: String(runs.find((r) => r.status === "awaiting_approval").id) })}
                  className="vr-button vr-button-primary"
                  style={{ padding: "10px 16px", fontSize: "13px" }}
                >
                  Review & approve →
                </button>
              </div>
            </div>
          )}

          {/* Completion actions: clean result gates the download */}
          {result && !loading && !approval && (
            <div className="vr-card" style={{ marginTop: "20px", border: result.generation_failed ? "1px solid rgba(248,113,113,.3)" : "1px solid rgba(52,211,153,.25)", background: result.generation_failed ? "linear-gradient(145deg, rgba(248,113,113,.07), rgba(255,255,255,.02))" : "linear-gradient(145deg, rgba(52,211,153,.08), rgba(255,255,255,.02))" }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
                <div>
                  <div className="vr-section-label" style={{ color: result.generation_failed ? "#fca5a5" : "#6ee7b7" }}>
                    {result.generation_failed ? "Task failed — AI unavailable" : "Task complete — final verify + review"}
                  </div>
                  <h2 style={{ margin: "7px 0 6px", color: "#f8fafc", fontSize: "18px" }}>
                    {result.generation_failed
                      ? `Run #${result.id} could not be generated — AI quota exhausted`
                      : result.test_passed && result.requirements_met && (result.verified_findings || []).length === 0
                      ? `No bugs or errors — run #${result.id} is verified clean`
                      : `Run #${result.id} finished with ${(result.verified_findings || []).length} remaining issue(s)`}
                  </h2>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
                    <StatusPill tone={result.test_passed ? "success" : "danger"}>TEST {result.test_passed ? "PASS" : "FAIL"}</StatusPill>
                    <StatusPill tone={result.requirements_met ? "success" : "danger"}>VERIFY {result.requirements_met ? "PASS" : "FAIL"}</StatusPill>
                    <StatusPill tone={(result.verified_findings || []).length ? "warning" : "success"}>REVIEW {(result.verified_findings || []).length} finding(s)</StatusPill>
                    {(result.revision_count ?? 0) > 0 && <StatusPill tone="info">{result.revision_count} fix round(s) approved</StatusPill>}
                  </div>
                  <div style={{ color: "#94a3b8", fontSize: "12px", marginTop: "8px" }}>
                    {result.tech_stack && (
                      <span style={{ color: "#a5b4fc" }}>{result.tech_stack} · </span>
                    )}
                    {result.generation_failed
                      ? (result.generation_error || "AI quota exhausted — fix the quota/key issue and run again. Files below are error stubs, not a build.")
                      : result.test_passed && result.requirements_met && (result.verified_findings || []).length === 0
                      ? "Verified clean — proceed to the downloadable ZIP below."
                      : (result.revision_count ?? 0) > 0
                      ? "Best-effort build packaged after the approved fix rounds."
                      : "Finished without fixing — no fix rounds were applied."}
                  </div>
                  {downloadError && <div style={{ color: "#fca5a5", fontSize: "12px", marginTop: "8px" }}>{downloadError}</div>}
                </div>
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <button type="button" onClick={() => handleDownload(result.id)} disabled={downloading} className="vr-button vr-button-primary" style={{ padding: "10px 16px", fontSize: "13px", opacity: downloading ? .6 : 1 }}>
                    {downloading ? "Preparing ZIP…" : "Download ZIP"}
                  </button>
                  <button type="button" onClick={handlePreviewCurrent} className="vr-button vr-button-secondary" style={{ padding: "10px 16px", fontSize: "13px" }}>
                    Watch preview
                  </button>
                  <Link to="/review" className="vr-button vr-button-secondary" style={{ padding: "10px 16px", fontSize: "13px" }}>Open review</Link>
                </div>
              </div>
            </div>
          )}
          {result && !loading && !approval && <CompletionReport result={result} />}

          {/* Live run: tracker + console */}
          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.2fr)", gap: "20px", marginTop: "20px" }} className="vr-run-grid">
            {/* Agent tracker */}
            <div className="vr-card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                <div>
                  <div className="vr-section-label">Live agents</div>
                  <h2 style={{ margin: "7px 0 0", color: "#f8fafc", fontSize: "18px" }}>Completion status</h2>
                </div>
                <StatusPill tone={loading ? "warning" : entries.length ? "success" : "info"}>
                  {loading ? "Running" : entries.length ? "Done" : "Idle"}
                </StatusPill>
              </div>

              {/* Overall progress */}
              <div style={{ margin: "14px 0 6px", display: "flex", justifyContent: "space-between", fontSize: "11px", color: "#64748b" }}>
                <span>{doneCount}/{STAGES.length} stages complete</span>
                <span>{progress}%</span>
              </div>
              <div className="vr-progress-track">
                <div className="vr-progress-fill" style={{ width: `${progress}%` }} />
              </div>

              <div style={{ display: "grid", gap: "8px", marginTop: "14px" }}>
                {stageStatus.map((s, i) => (
                  <div
                    key={s.key}
                    className={s.status === "running" ? "vr-stage-running" : undefined}
                    style={{
                      display: "flex", gap: "12px", padding: "11px 13px", borderRadius: "11px",
                      border: s.status === "running" ? `1px solid ${s.color}55` : "1px solid rgba(255,255,255,.05)",
                      background: s.status === "running" ? `${s.color}11` : "rgba(255,255,255,.018)",
                    }}
                  >
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "4px" }}>
                      <StageDot status={s.status} color={s.color} />
                      <span style={{ color: "#475569", fontSize: "10px", fontWeight: 700 }}>0{i + 1}</span>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", alignItems: "center" }}>
                        <span style={{ color: "#e2e8f0", fontSize: "13px", fontWeight: 600 }}>{s.label}</span>
                        <span style={{ fontSize: "10px", fontWeight: 700, letterSpacing: ".06em", color: s.status === "done" ? "#6ee7b7" : s.status === "running" ? s.color : "#475569" }}>
                          {s.status === "done" ? "DONE" : s.status === "running" ? "RUNNING" : "QUEUED"}
                        </span>
                      </div>
                      <div style={{ color: "#475569", fontSize: "11px" }}>{s.desc}</div>
                      {s.last && (
                        <div style={{ color: "#94a3b8", fontSize: "11px", marginTop: "4px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {s.last.message}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Console */}
            <div className="vr-card" style={{ padding: 0, overflow: "hidden" }}>
              <div className="vr-console-header">
                <div style={{ display: "flex", gap: "6px" }}>
                  <span className="vr-console-dot" style={{ background: "#f87171" }} />
                  <span className="vr-console-dot" style={{ background: "#fbbf24" }} />
                  <span className="vr-console-dot" style={{ background: "#34d399" }} />
                </div>
                <span style={{ color: "#94a3b8", fontSize: "12px", fontWeight: 600 }}>
                  agent console — live {loading ? "(running)" : entries.length ? "(finished)" : "(idle)"}
                </span>
                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <button
                    type="button"
                    onClick={() => setAutoScroll((v) => !v)}
                    className="vr-console-btn"
                  >
                    {autoScroll ? "Auto-scroll on" : "Auto-scroll off"}
                  </button>
                  <button type="button" onClick={copyLogs} className="vr-console-btn">Copy</button>
                </div>
              </div>
              <div ref={consoleRef} className="vr-console">
                {entries.length === 0 && (
                  <div style={{ color: "#475569", fontSize: "12px" }}>
                    $ waiting for task… describe what the agents should build above.
                  </div>
                )}
                {entries.map((e) => (
                  <div key={e.id} className="vr-console-line">
                    <span className="vr-console-time">{formatClock(e.time)}</span>
                    <span
                      className="vr-console-stage"
                      style={{
                        color: STAGE_COLOR[e.stage] || "#94a3b8",
                        borderColor: `${STAGE_COLOR[e.stage] || "#94a3b8"}44`,
                        background: `${STAGE_COLOR[e.stage] || "#94a3b8"}11`,
                      }}
                    >
                      {e.stage.toUpperCase()}
                    </span>
                    <span style={{ color: e.fail ? "#fca5a5" : "#cbd5e1" }}>{e.message}</span>
                  </div>
                ))}
                {loading && <div className="vr-console-cursor">$ ▊</div>}
              </div>
              <div className="vr-console-footer">
                {entries.length} log line(s) · elapsed {elapsed}
                {result && (
                  <span style={{ marginLeft: "8px" }}>
                    · TEST {result.test_passed ? "PASS" : "FAIL"} · VERIFY {result.requirements_met ? "PASS" : "FAIL"} · {findings.length} finding(s)
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Work viewer */}
          <div className="vr-card" style={{ marginTop: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "12px", flexWrap: "wrap", alignItems: "center" }}>
              <div>
                <div className="vr-section-label">Work produced</div>
                <h2 style={{ margin: "7px 0 0", color: "#f8fafc", fontSize: "18px" }}>See what the agents did</h2>
              </div>
              {result && (
                <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                  <Link to="/review" className="vr-button vr-button-secondary" style={{ padding: "9px 13px", fontSize: "12px" }}>Open review</Link>
                  <button type="button" onClick={handlePreviewCurrent} className="vr-button vr-button-secondary" style={{ padding: "9px 13px", fontSize: "12px" }}>Watch preview</button>
                  <button type="button" onClick={() => handleDownload(result.id)} disabled={downloading} className="vr-button vr-button-primary" style={{ padding: "9px 13px", fontSize: "12px", opacity: downloading ? .6 : 1 }}>
                    {downloading ? "Preparing…" : "Download ZIP"}
                  </button>
                </div>
              )}
            </div>
            <div className="vr-tabs">
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setActiveTab(t)}
                  className={`vr-tab${activeTab === t ? " vr-tab-active" : ""}`}
                >
                  {t}
                </button>
              ))}
            </div>
            <div style={{ marginTop: "12px" }}>{renderTab()}</div>
          </div>

          {/* Recent runs */}
          <div className="vr-card" style={{ marginTop: "20px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "12px" }}>
              <div>
                <div className="vr-section-label">Workspace activity</div>
                <h2 style={{ margin: "7px 0 0", color: "#f8fafc", fontSize: "18px" }}>Recent engineering runs</h2>
              </div>
              <Link to="/history" className="vr-button vr-button-secondary" style={{ padding: "9px 13px", fontSize: "12px" }}>View history</Link>
            </div>
            {runs.length === 0 ? (
              <div style={{ marginTop: "16px", padding: "22px", textAlign: "center", border: "1px dashed rgba(255,255,255,.07)", borderRadius: "11px", color: "#64748b", fontSize: "12px" }}>
                No completed runs yet.
              </div>
            ) : (
              <div style={{ marginTop: "12px", display: "grid", gap: "8px" }}>
                {runs.map((r) => (
                  <div key={r.id} style={{ display: "flex", justifyContent: "space-between", gap: "12px", padding: "12px 14px", borderRadius: "10px", border: "1px solid rgba(255,255,255,.06)", flexWrap: "wrap", alignItems: "center" }}>
                    <div style={{ color: "#e2e8f0", fontSize: "13px", flex: "1 1 220px", minWidth: 0 }}>
                      #{r.id} — {(r.task || "").slice(0, 80)}
                      <div style={{ color: "#475569", fontSize: "11px", marginTop: "4px" }}>
                        {r.created_at ? new Date(r.created_at).toLocaleString() : ""} · {r.verified_findings_count ?? 0} findings · {r.revision_count ?? 0} revisions
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                      <StatusPill tone={r.status === "completed" ? "success" : r.status === "awaiting_approval" ? "warning" : "info"}>
                        {r.status === "awaiting_approval" ? "needs approval" : r.status}
                      </StatusPill>
                      {r.status === "awaiting_approval" ? (
                        <Link to={`/dashboard?resume=${r.id}`} className="vr-console-btn">Resume</Link>
                      ) : (
                        <>
                          <button type="button" onClick={() => handlePreviewRun(r)} className="vr-console-btn">Preview</button>
                          <button type="button" onClick={() => handleDownload(r.id)} className="vr-console-btn">ZIP</button>
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
        onClose={() => setShowPreview(false)}
        onDownload={previewTaskId ? () => handleDownload(previewTaskId) : undefined}
      />
    </div>
  );
}
