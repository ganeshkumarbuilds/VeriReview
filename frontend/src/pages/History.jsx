import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import PreviewModal from "../components/PreviewModal";
import { downloadProjectZip } from "../utils/download";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

function HistoryRow({
  title,
  description,
  status,
  statusClass,
  findings,
  revisions,
  date,
  pending,
  onDownload,
  onPreview,
  onResume,
  downloading,
}) {
  return (
    <div
      style={{
        padding: "20px",
        borderBottom:
          "1px solid rgba(255,255,255,.055)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: "20px",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "14px",
            minWidth: 0,
          }}
        >
          <div
            style={{
              width: "10px",
              height: "10px",
              borderRadius: "50%",
              background: "#818cf8",
              marginTop: "4px",
              flexShrink: 0,
            }}
          />

          <div>
            <h3
              style={{
                margin: 0,
                color: "#f8fafc",
                fontSize: "14px",
                lineHeight: 1.4,
              }}
            >
              {title}
            </h3>

            <p
              style={{
                margin: "6px 0 0",
                color: "#64748b",
                fontSize: "11px",
                lineHeight: 1.55,
                maxWidth: "650px",
              }}
            >
              {description}
            </p>
          </div>
        </div>

        <span className={`vr-status ${statusClass}`}>
          {status}
        </span>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "18px",
          flexWrap: "wrap",
          marginTop: "15px",
          marginLeft: "56px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            color: "#64748b",
            fontSize: "10px",
          }}
        >
          {date}
        </div>

        <div
          style={{
            color: "#334155",
            fontSize: "10px",
          }}
        >
          •
        </div>

        <div
          style={{
            color: "#64748b",
            fontSize: "10px",
          }}
        >
          Revisions:{" "}
          <span style={{ color: "#94a3b8" }}>
            {revisions}
          </span>
        </div>

        <div
          style={{
            color: "#64748b",
            fontSize: "10px",
          }}
        >
          Findings:{" "}
          <span
            style={{
              color:
                findings === 0
                  ? "#6ee7b7"
                  : "#fbbf24",
            }}
          >
            {findings}
          </span>
        </div>

        {pending ? (
          <button type="button" onClick={onResume} className="vr-button vr-button-primary" style={{ marginLeft: "auto", minHeight: "34px", padding: "0 14px", fontSize: "11px" }}>
            Review & approve →
          </button>
        ) : (
          <Link
            to="/review"
            style={{
              marginLeft: "auto",
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              color: "#818cf8",
              textDecoration: "none",
              fontSize: "10px",
              fontWeight: 600,
            }}
          >
            View review →
          </Link>
        )}
        {onPreview && (
          <button type="button" onClick={onPreview} className="vr-console-btn">
            Watch preview
          </button>
        )}
        {!pending && onDownload && (
          <button type="button" onClick={onDownload} disabled={downloading} className="vr-console-btn" style={{ opacity: downloading ? .6 : 1 }}>
            {downloading ? "Preparing…" : "Download ZIP"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function History() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const ownerEmail = (user?.email || "").trim().toLowerCase();
  const ownerQuery = ownerEmail ? `?owner=${encodeURIComponent(ownerEmail)}` : "";
  const ownerHeaders = ownerEmail ? { "X-User-Email": ownerEmail } : {};
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [runs, setRuns] = useState([]);
  const [stats, setStats] = useState({ total_projects: 0, total_verified_findings: 0, total_revisions: 0 });
  const [showPreview, setShowPreview] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("");
  const [previewCode, setPreviewCode] = useState("");
  const [previewTaskId, setPreviewTaskId] = useState(null);
  const [downloadingId, setDownloadingId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [hRes, sRes] = await Promise.all([
          fetch(`${API_BASE}/history${ownerQuery}`, { headers: ownerHeaders }),
          fetch(`${API_BASE}/stats${ownerQuery}`, { headers: ownerHeaders }),
        ]);
        if (!hRes.ok || !sRes.ok) throw new Error("Backend error");
        const [history, statsData] = await Promise.all([hRes.json(), sRes.json()]);
        if (!cancelled) {
          setRuns(Array.isArray(history) ? history : []);
          setStats(statsData || {});
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError("Could not load history. Is the backend running on :8000?");
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [ownerQuery]);

  const totalRuns = stats.total_projects ?? runs.length;
  const completedRuns = runs.filter((r) => r.status === "completed").length;
  const successRate = totalRuns > 0 ? `${Math.round((completedRuns / totalRuns) * 100)}%` : "—";

  const handleDownload = async (taskId) => {
    if (!taskId || downloadingId) return;
    setDownloadingId(taskId);
    try {
      await downloadProjectZip({ taskId, ownerQuery, ownerHeaders });
    } catch (e) {
      setError(e.message || "Download failed");
    } finally {
      setDownloadingId(null);
    }
  };

  const handlePreview = async (run) => {
    try {
      const res = await fetch(`${API_BASE}/task/${run.id}${ownerQuery}`, { headers: ownerHeaders });
      if (!res.ok) throw new Error(`Backend responded ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error("Project not found");
      setPreviewTitle(`Run #${run.id} preview`);
      setPreviewCode(data.frontend_code || "");
      setPreviewTaskId(run.id);
      setShowPreview(true);
    } catch (e) {
      setError(e.message || "Could not load preview");
    }
  };

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
            top: "-280px",
            left: "-120px",
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(99,102,241,.09), transparent 68%)",
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
                Workspace history
              </div>

              <h1 className="vr-dashboard-title">
                Engineering History
              </h1>

              <p className="vr-dashboard-subtitle">
                Review previous agent runs, verification results,
                findings, and completed engineering tasks.
              </p>
            </div>

            <Link
              to="/dashboard"
              className="vr-button vr-button-primary"
            >
              New task →
            </Link>
          </div>

          {/* =====================================================
              SUMMARY
          ====================================================== */}
          <div className="vr-dashboard-grid">
            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Total runs
              </div>

              <div className="vr-stat-value">
                {String(totalRuns).padStart(2, "0")}
              </div>

              <div className="vr-status vr-status-info">
                All time
              </div>
            </div>

            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Completed
              </div>

              <div className="vr-stat-value">
                {String(completedRuns).padStart(2, "0")}
              </div>

              <div className="vr-status vr-status-success">
                Verified
              </div>
            </div>

            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Verified findings
              </div>

              <div className="vr-stat-value">
                {String(stats.total_verified_findings ?? 0).padStart(2, "0")}
              </div>

              <div className="vr-status vr-status-info">
                AI assisted
              </div>
            </div>

            <div className="vr-stat-card">
              <div className="vr-stat-label">
                Success rate
              </div>

              <div className="vr-stat-value">
                {successRate}
              </div>

              <div className={`vr-status ${totalRuns > 0 ? "vr-status-success" : "vr-status-warning"}`}>
                {totalRuns > 0 ? "Completed runs" : "No runs yet"}
              </div>
            </div>
          </div>

          {/* =====================================================
              HISTORY
          ====================================================== */}
          <div
            className="vr-card"
            style={{
              marginTop: "20px",
              padding: 0,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "20px",
                borderBottom:
                  "1px solid rgba(255,255,255,.055)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "15px",
                flexWrap: "wrap",
              }}
            >
              <div>
                <div className="vr-section-label">
                  Agent runs
                </div>

                <h2
                  style={{
                    margin: "7px 0 0",
                    color: "#f8fafc",
                    fontSize: "18px",
                  }}
                >
                  Recent engineering tasks
                </h2>
              </div>

              <div className="vr-status vr-status-info">
                {runs.length} runs
              </div>
            </div>

            {loading && (
              <div style={{ padding: "40px 25px", textAlign: "center", color: "#94a3b8", fontSize: "13px" }}>
                Loading history from backend…
              </div>
            )}

            {error && (
              <div role="alert" style={{ padding: "40px 25px", textAlign: "center", color: "#fca5a5", fontSize: "13px" }}>
                {error}
              </div>
            )}

            {!loading && !error && runs.length === 0 && (
              <div
                style={{
                  padding: "70px 25px",
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    width: "58px",
                    height: "58px",
                    margin: "0 auto 18px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    borderRadius: "16px",
                    background:
                      "rgba(99,102,241,.08)",
                    border:
                      "1px solid rgba(99,102,241,.14)",
                    color: "#818cf8",
                  }}
                >
                  ◇
                </div>

                <h3
                  style={{
                    margin: "0 0 8px",
                    color: "#e2e8f0",
                    fontSize: "16px",
                  }}
                >
                  No engineering runs yet
                </h3>

                <p
                  style={{
                    maxWidth: "460px",
                    margin: "0 auto 22px",
                    color: "#64748b",
                    fontSize: "12px",
                    lineHeight: 1.65,
                  }}
                >
                  Once you give VeriReview a software engineering
                  task, completed agent runs and their verification
                  history will appear here.
                </p>

                <Link
                  to="/dashboard"
                  className="vr-button vr-button-primary"
                >
                  Create your first task
                </Link>
              </div>
            )}

            {!loading && !error && runs.length > 0 && (
              <div>
                {runs.map((r) => {
                  const pending = r.status === "awaiting_approval";
                  return (
                    <HistoryRow
                      key={r.id}
                      title={`#${r.id} — ${(r.task || "").slice(0, 100)}`}
                      description={pending ? "Verify + review finished — waiting for your approval to fix." : (r.task || "")}
                      status={pending ? "needs approval" : (r.status || "completed")}
                      statusClass={pending ? "vr-status-warning" : (r.status === "completed" ? "vr-status-success" : "vr-status-info")}
                      findings={r.verified_findings_count ?? 0}
                      revisions={r.revision_count ?? 0}
                      date={r.created_at ? new Date(r.created_at).toLocaleString() : ""}
                      pending={pending}
                      downloading={downloadingId === r.id}
                      onDownload={() => handleDownload(r.id)}
                      onPreview={() => handlePreview(r)}
                      onResume={() => navigate(`/dashboard?resume=${r.id}`)}
                    />
                  );
                })}
              </div>
            )}
          </div>

          {/* =====================================================
              WHAT WILL BE STORED
          ====================================================== */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "12px",
              marginTop: "20px",
              marginBottom: "20px",
            }}
          >
            <div className="vr-card">
              <div className="vr-section-label">
                Verification
              </div>

              <h3
                style={{
                  margin: "8px 0 7px",
                  color: "#f8fafc",
                  fontSize: "15px",
                }}
              >
                Verification history
              </h3>

              <p
                style={{
                  margin: 0,
                  color: "#64748b",
                  fontSize: "11px",
                  lineHeight: 1.6,
                }}
              >
                Track whether each implementation satisfied the
                original task and passed the verification checks.
              </p>
            </div>

            <div className="vr-card">
              <div className="vr-section-label">
                Findings
              </div>

              <h3
                style={{
                  margin: "8px 0 7px",
                  color: "#f8fafc",
                  fontSize: "15px",
                }}
              >
                Review history
              </h3>

              <p
                style={{
                  margin: 0,
                  color: "#64748b",
                  fontSize: "11px",
                  lineHeight: 1.6,
                }}
              >
                Preserve discovered bugs, warnings, vulnerabilities,
                fixes, and the state of each review cycle.
              </p>
            </div>

            <div className="vr-card">
              <div className="vr-section-label">
                Agent activity
              </div>

              <h3
                style={{
                  margin: "8px 0 7px",
                  color: "#f8fafc",
                  fontSize: "15px",
                }}
              >
                Execution timeline
              </h3>

              <p
                style={{
                  margin: 0,
                  color: "#64748b",
                  fontSize: "11px",
                  lineHeight: 1.6,
                }}
              >
                See how Planner, Architect, Coding, Testing,
                Verified, and Review agents contributed to each run.
              </p>
            </div>
          </div>
        </div>
      </main>
      <PreviewModal
        open={showPreview}
        title={previewTitle}
        frontendCode={previewCode}
        downloading={downloadingId === previewTaskId}
        onClose={() => setShowPreview(false)}
        onDownload={previewTaskId ? () => handleDownload(previewTaskId) : undefined}
      />
    </div>
  );
}
