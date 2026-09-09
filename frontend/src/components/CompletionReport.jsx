function parseMarkers(code) {
  const names = [];
  for (const line of (code || "").split("\n")) {
    const t = line.trim();
    for (const prefix of ["// FILE:", "# FILE:"]) {
      if (t.startsWith(prefix)) {
        const name = t.slice(prefix.length).trim();
        if (name) names.push(name);
        break;
      }
    }
  }
  return names;
}

function Pill({ tone, children }) {
  return <span className={`vr-status vr-status-${tone}`}>{children}</span>;
}

export default function CompletionReport({ result }) {
  if (!result) return null;
  const failed = !!result.generation_failed;
  const backendFiles = failed ? [] : parseMarkers(result.backend_code);
  const frontendOk = !failed && !!(result.frontend_code || "").trim()
    && !(result.frontend_code || "").toLowerCase().includes("generation failed");
  const findings = result.verified_findings || [];
  const rounds = result.revision_history || [];
  const fixedRounds = result.revision_count ?? 0;

  return (
    <div className="vr-card" style={{ marginTop: "20px" }}>
      <div className="vr-section-label">Completion report</div>
      <h2 style={{ margin: "7px 0 0", color: "#f8fafc", fontSize: "18px" }}>
        What the agents checked, found and fixed
      </h2>

      {failed && (
        <div role="alert" style={{ marginTop: "12px", padding: "12px", borderRadius: "10px", border: "1px solid rgba(248,113,113,.3)", background: "rgba(248,113,113,.07)", color: "#fca5a5", fontSize: "12px", lineHeight: 1.6 }}>
          AI generation failed for this run{result.generation_error ? ` — ${result.generation_error}` : "."} The files below are error stubs, not real code. Fix the quota/key issue and run the task again.
        </div>
      )}

      <div className="vr-dashboard-grid" style={{ marginTop: "14px", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        <div className="vr-stat-card">
          <div className="vr-stat-label">Files checked</div>
          <div className="vr-stat-value">{String(backendFiles.length + (frontendOk ? 1 : 0)).padStart(2, "0")}</div>
          <Pill tone="info">{backendFiles.length} backend · {frontendOk ? 1 : 0} frontend</Pill>
        </div>
        <div className="vr-stat-card">
          <div className="vr-stat-label">Bugs reviewed & verified</div>
          <div className="vr-stat-value">{failed ? "—" : String(findings.length).padStart(2, "0")}</div>
          <Pill tone={failed ? "warning" : findings.length ? "warning" : "success"}>{failed ? "No real review ran" : findings.length ? "Needs attention" : "None confirmed"}</Pill>
        </div>
        <div className="vr-stat-card">
          <div className="vr-stat-label">Fix rounds approved</div>
          <div className="vr-stat-value">{String(fixedRounds).padStart(2, "0")}</div>
          <Pill tone="info">{fixedRounds} approved fix round(s)</Pill>
        </div>
        <div className="vr-stat-card">
          <div className="vr-stat-label">Bugs remaining now</div>
          <div className="vr-stat-value">{failed ? "—" : String(findings.length).padStart(2, "0")}</div>
          <Pill tone={failed ? "warning" : findings.length ? "danger" : "success"}>{failed ? "Unknown — no real review ran" : findings.length ? "Still open" : "Zero — clean"}</Pill>
        </div>
      </div>

      {backendFiles.length > 0 && (
        <div style={{ marginTop: "14px" }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>Checked files</div>
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {backendFiles.map((n) => (
              <span key={n} className="vr-console-stage" style={{ color: "#a5b4fc", borderColor: "rgba(129,140,248,.3)", background: "rgba(99,102,241,.08)" }}>{n}</span>
            ))}
            {frontendOk && (
              <span className="vr-console-stage" style={{ color: "#6ee7b7", borderColor: "rgba(52,211,153,.3)", background: "rgba(52,211,153,.08)" }}>App.jsx</span>
            )}
          </div>
        </div>
      )}

      {rounds.length > 0 && (
        <div style={{ marginTop: "14px" }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>Fix history per round</div>
          <div style={{ display: "grid", gap: "6px" }}>
            {rounds.map((h, i) => (
              <div key={i} style={{ display: "flex", gap: "10px", fontSize: "12px", color: "#94a3b8", flexWrap: "wrap" }}>
                <span style={{ color: "#e2e8f0", fontWeight: 600 }}>Round {h.attempt ?? i + 1}</span>
                <span>TEST {(h.test_passed ?? h.testPassed) ? "PASS" : "FAIL"}</span>
                <span>VERIFY {(h.requirements_met ?? h.requirementsMet) ? "PASS" : "FAIL"}</span>
                <span>{(h.verified_findings || []).length} finding(s) at the time</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {findings.length > 0 ? (
        <div style={{ marginTop: "14px" }}>
          <div style={{ color: "#94a3b8", fontSize: "12px", fontWeight: 600, marginBottom: "6px" }}>Verified bugs — what they are</div>
          <div style={{ display: "grid", gap: "8px" }}>
            {findings.map((f, i) => (
              <div key={i} style={{ display: "flex", gap: "10px", padding: "10px 12px", borderRadius: "10px", border: "1px solid rgba(255,255,255,.06)", flexWrap: "wrap", alignItems: "center" }}>
                <Pill tone={f.severity === "high" ? "danger" : f.severity === "medium" ? "warning" : "info"}>{f.severity}</Pill>
                <div style={{ flex: "1 1 200px", minWidth: 0 }}>
                  <div style={{ color: "#e2e8f0", fontSize: "13px", fontWeight: 600 }}>{f.category}</div>
                  <div style={{ color: "#64748b", fontSize: "11px" }}>{f.file}</div>
                </div>
                <div style={{ flex: "2 1 280px", color: "#94a3b8", fontSize: "12px" }}>{f.issue}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        !failed && (
          <div style={{ marginTop: "14px", color: "#6ee7b7", fontSize: "13px" }}>
            No bugs remaining — review PASS. Safe to download the ZIP.
          </div>
        )
      )}
    </div>
  );
}
