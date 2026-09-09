import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import PreviewModal from "../components/PreviewModal";
import { downloadProjectZip } from "../utils/download";
import { humanizeReport } from "../utils/techstack";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function severityToLabel(severity) {
  if (severity === "high") return "Critical";
  if (severity === "medium") return "Warning";
  return "Info";
}

function Finding({
  severity,
  title,
  location,
  description,
  type,
  fixed,
  onFix,
}) {
  const severityClass =
    severity === "Critical"
      ? "vr-status-danger"
      : severity === "Warning"
        ? "vr-status-warning"
        : "vr-status-info";

  return (
    <div
      className="vr-finding"
      style={{
        opacity: fixed ? 0.65 : 1,
      }}
    >
      <div className="vr-finding-header">
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "9px",
            minWidth: 0,
          }}
        >
          <span className={`vr-status ${severityClass}`}>
            {severity}
          </span>

          <span
            style={{
              color: "#475569",
              fontSize: "10px",
            }}
          >
            {type}
          </span>
        </div>

        {fixed && (
          <span className="vr-status vr-status-success">
            Fixed
          </span>
        )}
      </div>

      <div className="vr-finding-title">
        {title}
      </div>

      <div className="vr-finding-location">
        {location}
      </div>

      <div className="vr-finding-description">
        {description}
      </div>

      <div className="vr-finding-actions">
        {!fixed ? (
          <button
            type="button"
            className="vr-fix-button"
            onClick={onFix}
          >
            Fix with AI
          </button>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "7px",
              color: "#6ee7b7",
              fontSize: "11px",
              fontWeight: 600,
            }}
          >
            Sent to Coding Agent
          </div>
        )}
      </div>
    </div>
  );
}

export default function Review() {
  const { user } = useAuth();
  const ownerEmail = (user?.email || "").trim().toLowerCase();
  const ownerQuery = ownerEmail ? `?owner=${encodeURIComponent(ownerEmail)}` : "";
  const ownerHeaders = ownerEmail ? { "X-User-Email": ownerEmail } : {};
  const [activeTab, setActiveTab] = useState("review");
  const [fixedFindings, setFixedFindings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [run, setRun] = useState(null);
  const [pendingRun, setPendingRun] = useState(null);
  const [showPreview, setShowPreview] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const historyRes = await fetch(`${API_BASE}/history${ownerQuery}`, { headers: ownerHeaders });
        if (!historyRes.ok) throw new Error(`Backend responded ${historyRes.status}`);
        const history = await historyRes.json();
        if (!history.length) {
          if (!cancelled) {
            setRun(null);
            setLoading(false);
          }
          return;
        }
        const latestCompleted = history.find((h) => h.status === "completed");
        const latestPending = history.find((h) => h.status === "awaiting_approval");
        if (!cancelled) setPendingRun(latestPending || null);
        if (!latestCompleted) {
          if (!cancelled) {
            setRun(null);
            setLoading(false);
          }
          return;
        }
        const latestId = latestCompleted.id;
        const taskRes = await fetch(`${API_BASE}/task/${latestId}${ownerQuery}`, { headers: ownerHeaders });
        if (!taskRes.ok) throw new Error(`Backend responded ${taskRes.status}`);
        const task = await taskRes.json();
        if (!cancelled) {
          setRun(task);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError("Could not load review data. Is the backend running on :8000?");
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [ownerQuery]);

  const findings = (run?.verified_findings || []).map((f, i) => ({
    id: i,
    severity: severityToLabel(f.severity),
    type: f.category || "Review",
    title: f.issue || "Issue",
    location: f.line ? `${f.file || "unknown"}:${f.line}` : (f.file || "unknown"),
    description: f.verification || f.issue || "",
  }));

  const handleFix = (id) => {
    setFixedFindings((previous) => {
      if (previous.includes(id)) {
        return previous;
      }

      return [...previous, id];
    });
  };

  const openCount =
    findings.length - fixedFindings.length;

  const criticalCount = findings.filter(
    (finding) =>
      finding.severity === "Critical" &&
      !fixedFindings.includes(finding.id)
  ).length;

  const warningCount = findings.filter(
    (finding) =>
      finding.severity === "Warning" &&
      !fixedFindings.includes(finding.id)
  ).length;

  const infoCount = findings.filter(
    (finding) =>
      finding.severity === "Info" &&
      !fixedFindings.includes(finding.id)
  ).length;

  const testPassed = run?.test_passed;
  const requirementsMet = run?.requirements_met;

  return (
    <div className="vr-page">
      <main
        className="vr-dashboard"
        style={{
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Background glow */}
        <div
          style={{
            position: "absolute",
            width: "500px",
            height: "500px",
            top: "-260px",
            right: "-100px",
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(99,102,241,.1), transparent 68%)",
            filter: "blur(25px)",
            pointerEvents: "none",
          }}
        />

        <div className="vr-container">
          {/* =====================================================
              HEADER
          ====================================================== */}
          <div className="vr-dashboard-header">
            <div>
              <div className="vr-section-label">
                Review Agent
              </div>

              <h1 className="vr-dashboard-title">
                Code Review
              </h1>

              <p className="vr-dashboard-subtitle">
                {run
                  ? `Run #${run.id} — ${(run.task || "").slice(0, 120)}`
                  : "Review findings from the AI engineering pipeline, with actionable fixes and re-verification."}
              </p>
            </div>

            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              <Link
                to="/dashboard"
                className="vr-button vr-button-secondary"
              >
                Workspace
              </Link>
              {run && (
                <>
                  <button
                    type="button"
                    onClick={() => setShowPreview(true)}
                    className="vr-button vr-button-secondary"
                  >
                    Watch preview
                  </button>
                  <button
                    type="button"
                    disabled={downloading}
                    onClick={async () => {
                      if (downloading) return;
                      setDownloading(true);
                      try {
                        await downloadProjectZip({ taskId: run.id, ownerQuery, ownerHeaders });
                      } catch (e) {
                        setError(e.message || "Download failed");
                      } finally {
                        setDownloading(false);
                      }
                    }}
                    className="vr-button vr-button-primary"
                    style={{ opacity: downloading ? .6 : 1 }}
                  >
                    {downloading ? "Preparing ZIP…" : "Download ZIP"}
                  </button>
                </>
              )}
            </div>
          </div>

          {loading && (
            <div className="vr-card" style={{ marginTop: "20px", color: "#94a3b8", fontSize: "13px" }}>
              Loading latest review from backend…
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="vr-card"
              style={{ marginTop: "20px", color: "#fca5a5", fontSize: "13px", border: "1px solid rgba(248,113,113,.25)" }}
            >
              {error}
            </div>
          )}

          {!loading && !error && run?.generation_failed && (
            <div
              role="alert"
              className="vr-card"
              style={{ marginTop: "20px", color: "#fca5a5", fontSize: "13px", border: "1px solid rgba(248,113,113,.3)", background: "rgba(248,113,113,.05)" }}
            >
              AI generation failed for this run (usually the OpenRouter free-tier daily quota is exhausted — 50/day — or the key is invalid). Files below are error stubs. Wait for the daily reset or add credits, then run the task again.
            </div>
          )}

          {!loading && !error && !run && (
            <div className="vr-card" style={{ marginTop: "20px", textAlign: "center", padding: "48px 24px" }}>
              {pendingRun ? (
                <>
                  <h3 style={{ margin: "0 0 8px", color: "#e2e8f0", fontSize: "16px" }}>
                    Run #{pendingRun.id} is waiting for your approval
                  </h3>
                  <p style={{ margin: "0 auto 22px", maxWidth: "460px", color: "#64748b", fontSize: "12px", lineHeight: 1.65 }}>
                    Verify + review finished. Approve the AI fix (or finish without fixing) before the final result appears here.
                  </p>
                  <Link to={`/dashboard?resume=${pendingRun.id}`} className="vr-button vr-button-primary">
                    Review & approve
                  </Link>
                </>
              ) : (
                <>
                  <h3 style={{ margin: "0 0 8px", color: "#e2e8f0", fontSize: "16px" }}>
                    No reviews yet
                  </h3>
                  <p style={{ margin: "0 auto 22px", maxWidth: "460px", color: "#64748b", fontSize: "12px", lineHeight: 1.65 }}>
                    Run your first engineering task from the workspace and its review findings will appear here.
                  </p>
                  <Link to="/dashboard" className="vr-button vr-button-primary">
                    Go to workspace
                  </Link>
                </>
              )}
            </div>
          )}

          {!loading && !error && run && (
            <>
              {/* =====================================================
                  REVIEW SUMMARY
              ====================================================== */}
              <div className="vr-dashboard-grid">
                <div className="vr-stat-card">
                  <div className="vr-stat-label">
                    Open findings
                  </div>

                  <div className="vr-stat-value">
                    {openCount.toString().padStart(2, "0")}
                  </div>

                  <div
                    className={`vr-status ${
                      openCount === 0
                        ? "vr-status-success"
                        : "vr-status-warning"
                    }`}
                  >
                    {openCount === 0
                      ? "All resolved"
                      : "Needs attention"}
                  </div>
                </div>

                <div className="vr-stat-card">
                  <div className="vr-stat-label">
                    Critical
                  </div>

                  <div className="vr-stat-value">
                    {criticalCount.toString().padStart(2, "0")}
                  </div>

                  <div className="vr-status vr-status-danger">
                    Security
                  </div>
                </div>

                <div className="vr-stat-card">
                  <div className="vr-stat-label">
                    Warnings
                  </div>

                  <div className="vr-stat-value">
                    {warningCount.toString().padStart(2, "0")}
                  </div>

                  <div className="vr-status vr-status-warning">
                    Quality
                  </div>
                </div>

                <div className="vr-stat-card">
                  <div className="vr-stat-label">
                    Informational
                  </div>

                  <div className="vr-stat-value">
                    {infoCount.toString().padStart(2, "0")}
                  </div>

                  <div className="vr-status vr-status-info">
                    Maintainability
                  </div>
                </div>
              </div>

              {/* =====================================================
                  REVIEW AGENT HEADER
              ====================================================== */}
              <div
                className="vr-card"
                style={{
                  marginTop: "20px",
                  padding: "22px",
                  background:
                    "linear-gradient(145deg, rgba(99,102,241,.065), rgba(255,255,255,.018))",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: "15px",
                    flexWrap: "wrap",
                  }}
                >
                  <div
                    style={{
                      width: "10px",
                      height: "10px",
                      borderRadius: "50%",
                      background: "#34d399",
                      marginTop: "4px",
                      flexShrink: 0,
                    }}
                  />

                  <div style={{ flex: 1 }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "10px",
                        flexWrap: "wrap",
                      }}
                    >
                      <h2
                        style={{
                          margin: 0,
                          color: "#f8fafc",
                          fontSize: "17px",
                        }}
                      >
                        Review Agent
                      </h2>

                      <span className="vr-status vr-status-success">
                        Analysis complete
                      </span>
                      {typeof testPassed === "boolean" && (
                        <span className={`vr-status ${testPassed ? "vr-status-success" : "vr-status-danger"}`}>
                          TEST {testPassed ? "PASS" : "FAIL"}
                        </span>
                      )}
                      {typeof requirementsMet === "boolean" && (
                        <span className={`vr-status ${requirementsMet ? "vr-status-success" : "vr-status-danger"}`}>
                          VERIFY {requirementsMet ? "PASS" : "FAIL"}
                        </span>
                      )}
                    </div>

                    <p
                      style={{
                        margin: "7px 0 0",
                        color: "#64748b",
                        fontSize: "12px",
                        lineHeight: 1.6,
                      }}
                    >
                      The project has been analyzed for security,
                      correctness, code quality, maintainability,
                      testing, and engineering best practices.
                    </p>
                  </div>

                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      color: "#64748b",
                      fontSize: "10px",
                    }}
                  >
                    Verification enabled
                  </div>
                </div>
              </div>

              {/* =====================================================
                  TABS
              ====================================================== */}
              <div
                style={{
                  display: "flex",
                  gap: "5px",
                  marginTop: "20px",
                  padding: "5px",
                  width: "fit-content",
                  maxWidth: "100%",
                  borderRadius: "11px",
                  background: "rgba(255,255,255,.025)",
                  border:
                    "1px solid rgba(255,255,255,.06)",
                }}
              >
                <button
                  type="button"
                  onClick={() => setActiveTab("review")}
                  style={{
                    border: 0,
                    borderRadius: "8px",
                    padding: "9px 14px",
                    background:
                      activeTab === "review"
                        ? "rgba(99,102,241,.14)"
                        : "transparent",
                    color:
                      activeTab === "review"
                        ? "#c7d2fe"
                        : "#64748b",
                    fontSize: "11px",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Findings
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab("verification")}
                  style={{
                    border: 0,
                    borderRadius: "8px",
                    padding: "9px 14px",
                    background:
                      activeTab === "verification"
                        ? "rgba(99,102,241,.14)"
                        : "transparent",
                    color:
                      activeTab === "verification"
                        ? "#c7d2fe"
                        : "#64748b",
                    fontSize: "11px",
                    fontWeight: 600,
                    cursor: "pointer",
                  }}
                >
                  Verification
                </button>
              </div>

              {/* =====================================================
                  CONTENT
              ====================================================== */}
              {activeTab === "review" ? (
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "minmax(0, 1fr) 280px",
                    gap: "20px",
                    marginTop: "15px",
                  }}
                >
                  {/* Findings */}
                  <div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: "15px",
                        marginBottom: "12px",
                      }}
                    >
                      <div>
                        <div className="vr-section-label">
                          Findings
                        </div>

                        <h2
                          style={{
                            margin: "6px 0 0",
                            color: "#f8fafc",
                            fontSize: "18px",
                          }}
                        >
                          Issues discovered
                        </h2>
                      </div>

                      <span className="vr-status vr-status-info">
                        {findings.length} total
                      </span>
                    </div>

                    {findings.length === 0 ? (
                      <div className="vr-card" style={{ color: "#6ee7b7", fontSize: "13px" }}>
                        No confirmed findings — review PASS.
                      </div>
                    ) : (
                      <div className="vr-findings">
                        {findings.map((finding) => (
                          <Finding
                            key={finding.id}
                            {...finding}
                            fixed={fixedFindings.includes(
                              finding.id
                            )}
                            onFix={() =>
                              handleFix(finding.id)
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Sidebar */}
                  <aside>
                    <div className="vr-card">
                      <div className="vr-section-label">
                        Review scope
                      </div>

                      <h3
                        style={{
                          margin: "7px 0 16px",
                          color: "#f8fafc",
                          fontSize: "16px",
                        }}
                      >
                        What was checked
                      </h3>

                      <div
                        style={{
                          display: "grid",
                          gap: "10px",
                        }}
                      >
                        {[
                          "Security",
                          "Correctness",
                          "Code quality",
                          "Testing",
                          "Maintainability",
                          "Architecture",
                        ].map((item) => (
                          <div
                            key={item}
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: "8px",
                              color: "#94a3b8",
                              fontSize: "11px",
                            }}
                          >
                            <span
                              style={{
                                display: "inline-flex",
                                width: "17px",
                                height: "17px",
                                alignItems: "center",
                                justifyContent: "center",
                                borderRadius: "5px",
                                background:
                                  "rgba(52,211,153,.08)",
                                color: "#6ee7b7",
                              }}
                            >
                              ✓
                            </span>

                            {item}
                          </div>
                        ))}
                      </div>
                    </div>

                    <div
                      className="vr-card"
                      style={{
                        marginTop: "12px",
                      }}
                    >
                      <div className="vr-section-label">
                        Fix workflow
                      </div>

                      <div
                        style={{
                          marginTop: "13px",
                          display: "grid",
                          gap: "8px",
                        }}
                      >
                        <div className="vr-status vr-status-danger">
                          Finding
                        </div>

                        <div
                          style={{
                            textAlign: "center",
                            color: "#334155",
                            fontSize: "10px",
                          }}
                        >
                          ↓
                        </div>

                        <div className="vr-status vr-status-info">
                          Coding Agent
                        </div>

                        <div
                          style={{
                            textAlign: "center",
                            color: "#334155",
                            fontSize: "10px",
                          }}
                        >
                          ↓
                        </div>

                        <div className="vr-status vr-status-warning">
                          Test
                        </div>

                        <div
                          style={{
                            textAlign: "center",
                            color: "#334155",
                            fontSize: "10px",
                          }}
                        >
                          ↓
                        </div>

                        <div className="vr-status vr-status-success">
                          Re-verify
                        </div>
                      </div>
                    </div>
                  </aside>
                </div>
              ) : (
                /* ===================================================
                   VERIFICATION TAB
                ==================================================== */
                <div
                  className="vr-card"
                  style={{
                    marginTop: "15px",
                  }}
                >
                  <div className="vr-section-label">
                    Verified Agent
                  </div>

                  <h2
                    style={{
                      margin: "8px 0 10px",
                      color: "#f8fafc",
                      fontSize: "20px",
                    }}
                  >
                    Verification result
                  </h2>

                  <p
                    style={{
                      margin: 0,
                      maxWidth: "720px",
                      color: "#94a3b8",
                      fontSize: "13px",
                      lineHeight: 1.7,
                    }}
                  >
                    {humanizeReport(run.verification_report) || "The Verified Agent checks whether the implementation actually satisfies the original software task."}
                  </p>

                  {run.test_report && (
                    <pre className="vr-code" style={{ marginTop: "16px" }}>
                      {humanizeReport(run.test_report)}
                    </pre>
                  )}

                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns:
                        "repeat(auto-fit, minmax(180px, 1fr))",
                      gap: "10px",
                      marginTop: "22px",
                    }}
                  >
                    <div
                      style={{
                        padding: "16px",
                        borderRadius: "11px",
                        background:
                          "rgba(52,211,153,.045)",
                        border:
                          "1px solid rgba(52,211,153,.13)",
                      }}
                    >
                      <div className={`vr-status ${requirementsMet ? "vr-status-success" : "vr-status-danger"}`}>
                        {requirementsMet ? "Passed" : "Failed"}
                      </div>

                      <div
                        style={{
                          marginTop: "10px",
                          color: "#e2e8f0",
                          fontSize: "12px",
                          fontWeight: 600,
                        }}
                      >
                        Requirements
                      </div>
                    </div>

                    <div
                      style={{
                        padding: "16px",
                        borderRadius: "11px",
                        background:
                          testPassed
                            ? "rgba(52,211,153,.045)"
                            : "rgba(248,113,113,.045)",
                        border:
                          testPassed
                            ? "1px solid rgba(52,211,153,.13)"
                            : "1px solid rgba(248,113,113,.13)",
                      }}
                    >
                      <div className={`vr-status ${testPassed ? "vr-status-success" : "vr-status-danger"}`}>
                        {testPassed ? "Passed" : "Failed"}
                      </div>

                      <div
                        style={{
                          marginTop: "10px",
                          color: "#e2e8f0",
                          fontSize: "12px",
                          fontWeight: 600,
                        }}
                      >
                        Test execution
                      </div>
                    </div>

                    <div
                      style={{
                        padding: "16px",
                        borderRadius: "11px",
                        background:
                          findings.length === 0
                            ? "rgba(52,211,153,.045)"
                            : "rgba(245,158,11,.045)",
                        border:
                          findings.length === 0
                            ? "1px solid rgba(52,211,153,.13)"
                            : "1px solid rgba(245,158,11,.13)",
                      }}
                    >
                      <div className={`vr-status ${findings.length === 0 ? "vr-status-success" : "vr-status-warning"}`}>
                        {findings.length === 0 ? "Passed" : "Review needed"}
                      </div>

                      <div
                        style={{
                          marginTop: "10px",
                          color: "#e2e8f0",
                          fontSize: "12px",
                          fontWeight: 600,
                        }}
                      >
                        Code quality ({findings.length} finding{findings.length === 1 ? "" : "s"})
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* =====================================================
                  FOOTER MESSAGE
              ====================================================== */}
              <div
                style={{
                  marginTop: "22px",
                  padding: "18px",
                  borderRadius: "12px",
                  border:
                    "1px solid rgba(99,102,241,.12)",
                  background:
                    "rgba(99,102,241,.025)",
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                }}
              >
                <div
                  style={{
                    width: "32px",
                    height: "32px",
                    minWidth: "32px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    borderRadius: "9px",
                    background:
                      "rgba(99,102,241,.1)",
                    color: "#818cf8",
                  }}
                >
                  ✓
                </div>

                <div>
                  <div
                    style={{
                      color: "#cbd5e1",
                      fontSize: "12px",
                      fontWeight: 600,
                    }}
                  >
                    Review is not the final step.
                  </div>

                  <div
                    style={{
                      marginTop: "3px",
                      color: "#475569",
                      fontSize: "10px",
                      lineHeight: 1.5,
                    }}
                  >
                    Every AI-generated fix should return through
                    testing, verification, and review before the task
                    is considered complete.
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </main>
      <PreviewModal
        open={showPreview}
        title={run ? `Run #${run.id} preview` : "Preview"}
        frontendCode={run?.frontend_code || ""}
        downloading={downloading}
        onClose={() => setShowPreview(false)}
        onDownload={run ? async () => {
          if (downloading) return;
          setDownloading(true);
          try {
            await downloadProjectZip({ taskId: run.id, ownerQuery, ownerHeaders });
          } catch (e) {
            setError(e.message || "Download failed");
          } finally {
            setDownloading(false);
          }
        } : undefined}
      />
    </div>
  );
}
