const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function downloadProjectZip({ taskId, ownerQuery = "", ownerHeaders = {} }) {
  const res = await fetch(`${API_BASE}/export/${taskId}${ownerQuery}`, {
    headers: { ...ownerHeaders },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `verireview_project_${taskId}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

export function previewUrl(taskId, ownerQuery = "") {
  return `${API_BASE}/preview/${taskId}${ownerQuery}`;
}
