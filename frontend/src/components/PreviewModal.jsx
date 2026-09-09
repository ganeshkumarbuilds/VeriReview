import { useMemo } from "react";
import { buildPreviewHtml } from "../utils/preview";

export default function PreviewModal({ open, title, frontendCode, onClose, onDownload, downloading }) {
  const srcDoc = useMemo(() => {
    if (!open) return "";
    return buildPreviewHtml(frontendCode || "", title || "Project");
  }, [open, frontendCode, title]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Project preview"
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 200,
        background: "rgba(2,4,10,.72)", backdropFilter: "blur(6px)",
        display: "flex", alignItems: "center", justifyContent: "center", padding: "20px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(1100px, 100%)", height: "min(82vh, 800px)",
          display: "flex", flexDirection: "column", overflow: "hidden",
          borderRadius: "16px", border: "1px solid rgba(148,163,184,.2)",
          background: "#0b0d17", boxShadow: "0 30px 90px rgba(0,0,0,.5)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "14px 16px", borderBottom: "1px solid rgba(148,163,184,.14)", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: "#818cf8", fontSize: "11px", fontWeight: 700, letterSpacing: ".12em", textTransform: "uppercase" }}>Live UI preview</div>
            <div style={{ color: "#f8fafc", fontSize: "14px", fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {title || "Generated UI"}
            </div>
          </div>
          {onDownload && (
            <button type="button" onClick={onDownload} disabled={downloading} className="vr-button vr-button-primary" style={{ minHeight: "38px", padding: "0 14px", fontSize: "12px", opacity: downloading ? .6 : 1 }}>
              {downloading ? "Preparing ZIP…" : "Download ZIP"}
            </button>
          )}
          <button type="button" onClick={onClose} className="vr-button vr-button-secondary" style={{ minHeight: "38px", padding: "0 14px", fontSize: "12px" }}>
            Close
          </button>
        </div>
        {!frontendCode ? (
          <div style={{ padding: "32px", color: "#94a3b8", fontSize: "13px" }}>No frontend code was generated for this run yet.</div>
        ) : (
          <iframe
            title="project-preview"
            srcDoc={srcDoc}
            sandbox="allow-scripts"
            style={{ flex: 1, width: "100%", border: 0, background: "#f8fafc" }}
          />
        )}
        <div style={{ padding: "10px 16px", borderTop: "1px solid rgba(148,163,184,.14)", color: "#64748b", fontSize: "11px" }}>
          Preview renders the generated <span style={{ color: "#94a3b8" }}>App.jsx</span> with mocked API data. Backend calls return sample items.
        </div>
      </div>
    </div>
  );
}
