function Pill({ tone, children }) {
  return <span className={`vr-status vr-status-${tone}`}>{children}</span>;
}

function humanizeReport(text) {
  const s = String(text || "");
  if (!s.trim()) return "—";
  if (/rate limit exceeded|free-models-per-day|daily reset/i.test(s)) {
    return "AI models unavailable: the OpenRouter free-tier daily quota is exhausted (50 calls/day, resets midnight UTC). Add $10 credits for 1000/day, or wait for reset and run again.";
  }
  if (/api key rejected|OPENROUTER_API_KEY|unauthorized|401/i.test(s)) {
    return "AI models unavailable: the backend API key was rejected. Check OPENROUTER_API_KEY and run again.";
  }
  if (s.includes("user_id")) return s.split("\n")[0].slice(0, 220);
  return s;
}

export default function ApprovalCard({ approval, deciding, onApprove, onSkip }) {
  if (!approval) return null;
  const findings = approval.verified_findings || [];
  const clean = approval.is_clean;
  const runNo = approval.runId ?? approval.run_id;
  const quotaBlocked = !!approval.generation_failed;

  return (
    <div
      className="vr-card"
      role="dialog"
      aria-label="Review approval"
      style={{ marginTop: "20px", border: "1px solid rgba(251,191,36,.3)", background: "linear-gradient(145deg, rgba(251,191,36,.07), rgba(255,255,255,.02))" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "16px", flexWrap: "wrap", alignItems: "center" }}>
        <div>
          <div className="vr-section-label" style={{ color: "#fcd34d" }}>Human approval required — run #{runNo}</div>
          <h2 style={{ margin: "7px 0 6px", color: "#f8fafc", fontSize: "18px" }}>
            {quotaBlocked
              ? "AI models unavailable — fix blocked until quota recovers"
              : clean ? "Verified clean — no bugs found" : `Review found ${findings.length} issue(s) — approve the AI fix?`}
          </h2>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
            <Pill tone={approval.test_passed ? "success" : "danger"}>TEST {approval.test_passed ? "PASS" : "FAIL"}</Pill>
            <Pill tone={approval.requirements_met ? "success" : "danger"}>VERIFY {approval.requirements_met ? "PASS" : "FAIL"}</Pill>
            <Pill tone={findings.length ? "warning" : "success"}>REVIEW {findings.length} finding(s)</Pill>
          </div>
          {approval.verification_report && (
            <div style={{ color: "#94a3b8", fontSize: "12px", marginTop: "8px", maxWidth: "640px" }}>{humanizeReport(approval.verification_report)}</div>
          )}
        </div>
        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
          {!clean && approval.needs_fix && !quotaBlocked && (
            <button type="button" onClick={onApprove} disabled={deciding} className="vr-button vr-button-primary" style={{ padding: "10px 16px", fontSize: "13px", opacity: deciding ? .6 : 1 }}>
              {deciding ? "Working…" : "Approve AI fix"}
            </button>
          )}
          <button type="button" onClick={onSkip} disabled={deciding} className="vr-button vr-button-secondary" style={{ padding: "10px 16px", fontSize: "13px", opacity: deciding ? .6 : 1 }}>
            {clean ? "Proceed to download" : quotaBlocked ? "Close & finish" : "Finish without fixing"}
          </button>
        </div>
      </div>

      {!clean && findings.length > 0 && (
        <div style={{ marginTop: "14px", display: "grid", gap: "8px" }}>
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
      )}

      <div style={{ color: "#64748b", fontSize: "11px", marginTop: "12px" }}>
        {quotaBlocked
          ? "The AI quota is exhausted (OpenRouter free tier: 50 calls/day, resets midnight UTC) or the key is invalid — approving would just fail again. Close this, add $10 credits or wait for reset, then run again."
          : clean
          ? "All checks passed. Continue to package the build and download the ZIP."
          : "The coding agent will update the existing files to remove these errors, then verify + review will re-test and show the result."}
      </div>
    </div>
  );
}
