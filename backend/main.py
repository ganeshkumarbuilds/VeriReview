import asyncio
import io
import zipfile
from typing import Optional
from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.graph import (
    build_graph,
    initial_state as _graph_initial_state,
    normalize_stack,
    detect_family,
    run_phase1,
    run_fix_loop,
    needs_fix,
    is_clean,
    approval_summary,
    PHASE1_NODES,
    FIX_NODES,
    run_finalize,
)
from app.database import init_db, get_db, TaskRecord, SessionLocal
from app.scaffold import build_project_zip
from app.file_utils import parse_files

app = FastAPI(title="VeriReview")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

graph = build_graph()
init_db()

# Pre-warm the local RAG index (embedding model + knowledge base) at startup
# so the first task doesn't pay that one-time init cost mid-run.
try:
    from app.rag import get_collection
    get_collection()
    print("[rag] knowledge index warmed")
except Exception as e:
    print(f"[rag] warm-up skipped: {e}")


class TaskRequest(BaseModel):
    task: str
    owner_email: Optional[str] = None
    tech_stack: Optional[str] = None
    db_url: Optional[str] = None
    api_keys: Optional[dict] = None


def _normalize_secrets(db_url: Optional[str], api_keys: Optional[dict]) -> tuple:
    clean_url = (db_url or "").strip()
    clean_keys = {}
    if isinstance(api_keys, dict):
        for k, v in api_keys.items():
            key = str(k or "").strip()
            if key and v is not None and str(v).strip():
                clean_keys[key] = str(v).strip()
    return clean_url, clean_keys


def _normalize_email(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _resolve_owner(
    body_email: Optional[str] = None,
    header_email: Optional[str] = None,
    query_email: Optional[str] = None,
) -> Optional[str]:
    return _normalize_email(body_email) or _normalize_email(header_email) or _normalize_email(query_email)


def _initial_state(task: str, tech_stack: str = "", db_url: str = "", api_keys: dict = None) -> dict:
    return _graph_initial_state(task, tech_stack=tech_stack, db_url=db_url, api_keys=api_keys)


def _record_to_dict(result: dict, record_id: int, status: str = "completed") -> dict:
    return {
        "id": record_id,
        "status": status,
        "tech_stack": result.get("tech_stack", ""),
        "generation_failed": bool(result.get("generation_failed")),
        "generation_error": result.get("generation_error", ""),
        "is_clean": is_clean(result),
        "product_spec": result["product_spec"],
        "architecture": result["architecture"],
        "database_design": result["database_design"],
        "backend_code": result["backend_code"],
        "frontend_code": result["frontend_code"],
        "qa_notes": result["qa_notes"],
        "test_report": result.get("test_report", ""),
        "test_passed": result.get("test_passed", False),
        "verification_report": result.get("verification_report", ""),
        "requirements_met": result.get("requirements_met", False),
        "documentation": result["documentation"],
        "deployment_config": result["deployment_config"],
        "steps_log": result["steps_log"],
        "verified_findings": result["verified_findings"],
        "review_passed": result.get("review_passed", True),
        "revision_count": result["revision_count"],
        "revision_history": result["revision_history"],
    }


@app.get("/")
def root():
    return {"status": "VeriReview backend is running", "code_version": _code_version()}


def _code_version() -> float:
    """Max mtime of core sources — verifies the running code is current."""
    try:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "main.py"),
            os.path.join(here, "app", "graph.py"),
            os.path.join(here, "app", "scaffold.py"),
            os.path.join(here, "app", "database.py"),
        ]
        return max(os.path.getmtime(f) for f in candidates if os.path.exists(f))
    except Exception:
        return 0


@app.post("/review")
def review_code(
    request: TaskRequest,
    db: Session = Depends(get_db),
    x_user_email: Optional[str] = Header(default=None),
):
    owner_email = _resolve_owner(request.owner_email, x_user_email)
    tech_stack = normalize_stack(request.tech_stack)
    db_url, api_keys = _normalize_secrets(request.db_url, request.api_keys)
    result = graph.invoke(_initial_state(
        request.task, tech_stack=tech_stack, db_url=db_url, api_keys=api_keys))

    record = TaskRecord(
        task=request.task,
        owner_email=owner_email,
        tech_stack=tech_stack,
        db_url=db_url,
        api_keys=api_keys,
        product_spec=result["product_spec"],
        architecture=result["architecture"],
        database_design=result["database_design"],
        backend_code=result["backend_code"],
        frontend_code=result["frontend_code"],
        qa_notes=result["qa_notes"],
        test_report=result.get("test_report", ""),
        test_passed=result.get("test_passed", False),
        verification_report=result.get("verification_report", ""),
        requirements_met=result.get("requirements_met", False),
        documentation=result["documentation"],
        deployment_config=result["deployment_config"],
        verified_findings=result["verified_findings"],
        revision_count=result["revision_count"],
        revision_history=result["revision_history"],
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return _record_to_dict(result, record.id)


class DecideRequest(BaseModel):
    run_id: int
    approved: bool
    owner_email: Optional[str] = None


def _apply_state_to_record(record: TaskRecord, state: dict, status: str) -> None:
    record.status = status
    record.tech_stack = state.get("tech_stack", "")
    record.db_url = state.get("db_url", "")
    record.api_keys = state.get("api_keys", {})
    record.product_spec = state.get("product_spec", "")
    record.architecture = state.get("architecture", "")
    record.database_design = state.get("database_design", "")
    record.backend_code = state.get("backend_code", "")
    record.frontend_code = state.get("frontend_code", "")
    record.qa_notes = state.get("qa_notes", "")
    record.test_report = state.get("test_report", "")
    record.test_passed = state.get("test_passed", False)
    record.verification_report = state.get("verification_report", "")
    record.requirements_met = state.get("requirements_met", False)
    record.documentation = state.get("documentation", "")
    record.deployment_config = state.get("deployment_config", "")
    record.verified_findings = state.get("verified_findings", [])
    record.revision_count = state.get("revision_count", 0)
    record.revision_history = state.get("revision_history", [])


def _pending_payload(record: TaskRecord) -> dict:
    state = record.phase_state or {}
    summary = approval_summary(state) if state else approval_summary({})
    return {
        "run_id": record.id,
        "task": record.task,
        "status": record.status,
        "tech_stack": record.tech_stack or state.get("tech_stack", ""),
        **summary,
    }


@app.post("/review/phase1")
def review_phase1(
    request: TaskRequest,
    db: Session = Depends(get_db),
    x_user_email: Optional[str] = Header(default=None),
):
    """Run build -> test -> verify -> review, then PAUSE for user approval."""
    owner_email = _resolve_owner(request.owner_email, x_user_email)
    tech_stack = normalize_stack(request.tech_stack)
    db_url, api_keys = _normalize_secrets(request.db_url, request.api_keys)
    state = run_phase1(request.task, tech_stack=tech_stack, db_url=db_url, api_keys=api_keys)

    record = TaskRecord(
        task=request.task,
        owner_email=owner_email,
        status="awaiting_approval",
        tech_stack=tech_stack,
        db_url=db_url,
        api_keys=api_keys,
        product_spec=state["product_spec"],
        architecture=state["architecture"],
        database_design=state["database_design"],
        backend_code=state["backend_code"],
        frontend_code=state["frontend_code"],
        qa_notes=state.get("qa_notes", ""),
        test_report=state.get("test_report", ""),
        test_passed=state.get("test_passed", False),
        verification_report=state.get("verification_report", ""),
        requirements_met=state.get("requirements_met", False),
        documentation="",
        deployment_config="",
        verified_findings=state.get("verified_findings", []),
        revision_count=state.get("revision_count", 0),
        revision_history=state.get("revision_history", []),
        phase_state=dict(state),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return _pending_payload(record)


@app.get("/review/pending/{run_id}")
def get_pending(
    run_id: int,
    db: Session = Depends(get_db),
    owner: Optional[str] = Query(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner_email = _resolve_owner(query_email=owner, header_email=x_user_email)
    r = db.query(TaskRecord).filter(TaskRecord.id == run_id).first()
    if not r:
        return {"error": "not found"}
    record_owner = _normalize_email(r.owner_email)
    if owner_email:
        if record_owner != owner_email:
            return {"error": "not found"}
    elif record_owner:
        return {"error": "not found"}
    if r.status != "awaiting_approval":
        return {"error": "not pending", "status": r.status}
    return _pending_payload(r)


@app.post("/review/decide")
def review_decide(
    request: DecideRequest,
    db: Session = Depends(get_db),
    x_user_email: Optional[str] = Header(default=None),
):
    """User approved (fix + re-verify + re-review, then package) or skipped fixing."""
    owner_email = _resolve_owner(request.owner_email, x_user_email)
    r = db.query(TaskRecord).filter(TaskRecord.id == request.run_id).first()
    if not r:
        return {"error": "not found"}
    record_owner = _normalize_email(r.owner_email)
    if owner_email:
        if record_owner != owner_email:
            return {"error": "not found"}
    elif record_owner:
        return {"error": "not found"}
    if r.status != "awaiting_approval" or not r.phase_state:
        return {"error": "not pending", "status": r.status}

    state = dict(r.phase_state)
    if request.approved and needs_fix(state):
        state = run_fix_loop(state)
    state = run_finalize(state)

    _apply_state_to_record(r, state, status="completed")
    r.phase_state = None
    db.commit()
    db.refresh(r)

    return _record_to_dict(state, r.id, status="completed")


@app.get("/history")
def get_history(
    db: Session = Depends(get_db),
    owner: Optional[str] = Query(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner_email = _resolve_owner(query_email=owner, header_email=x_user_email)
    if not owner_email:
        # Strict per-user isolation: never leak the global task list.
        # Unauthenticated callers get an empty history.
        return []
    records = (
        db.query(TaskRecord)
        .filter(TaskRecord.owner_email == owner_email)
        .order_by(TaskRecord.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "task": r.task,
            "status": r.status,
            "revision_count": r.revision_count,
            "verified_findings_count": len(r.verified_findings) if r.verified_findings else 0,
            "created_at": r.created_at.isoformat(),
        }
        for r in records
    ]


@app.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    owner: Optional[str] = Query(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    owner_email = _resolve_owner(query_email=owner, header_email=x_user_email)
    if not owner_email:
        return {
            "total_projects": 0,
            "total_verified_findings": 0,
            "total_revisions": 0,
        }
    records = db.query(TaskRecord).filter(TaskRecord.owner_email == owner_email).all()
    total = len(records)
    total_findings = sum(len(r.verified_findings) if r.verified_findings else 0 for r in records)
    total_revisions = sum(r.revision_count or 0 for r in records)
    return {
        "total_projects": total,
        "total_verified_findings": total_findings,
        "total_revisions": total_revisions,
    }


@app.get("/task/{task_id}")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    owner: Optional[str] = Query(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    r = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    if not r:
        return {"error": "not found"}
    owner_email = _resolve_owner(query_email=owner, header_email=x_user_email)
    record_owner = _normalize_email(r.owner_email)
    if owner_email:
        if record_owner != owner_email:
            return {"error": "not found"}
    elif record_owner:
        return {"error": "not found"}
    return {
        "id": r.id,
        "task": r.task,
        "tech_stack": r.tech_stack or "",
        "generation_failed": "generation failed" in (r.backend_code or "").lower() or "generation failed" in (r.frontend_code or "").lower(),
        "db_configured": bool(r.db_url),
        "api_key_names": sorted((r.api_keys or {}).keys()) if isinstance(r.api_keys, dict) else [],
        "product_spec": r.product_spec,
        "architecture": r.architecture,
        "database_design": r.database_design,
        "backend_code": r.backend_code,
        "frontend_code": r.frontend_code,
        "qa_notes": r.qa_notes,
        "test_report": r.test_report,
        "test_passed": r.test_passed,
        "verification_report": r.verification_report,
        "requirements_met": r.requirements_met,
        "documentation": r.documentation,
        "deployment_config": r.deployment_config,
        "verified_findings": r.verified_findings,
        "revision_count": r.revision_count,
        "revision_history": r.revision_history,
        "status": r.status,
    }


@app.get("/export/{task_id}")
def export_project(
    task_id: int,
    db: Session = Depends(get_db),
    owner: Optional[str] = Query(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    r = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    if not r:
        return {"error": "not found"}
    owner_email = _resolve_owner(query_email=owner, header_email=x_user_email)
    record_owner = _normalize_email(r.owner_email)
    if owner_email:
        if record_owner != owner_email:
            return {"error": "not found"}
    elif record_owner:
        return {"error": "not found"}

    tech_stack = normalize_stack(r.tech_stack)
    family = detect_family(tech_stack)
    preview_html = _build_standalone_preview(r.frontend_code or "", r.task or f"Project {r.id}")
    payload = build_project_zip(
        task=r.task or "",
        tech_stack=tech_stack,
        family=family,
        backend_code=r.backend_code or "",
        frontend_code=r.frontend_code or "",
        documentation=r.documentation or "",
        deployment_config=r.deployment_config or "",
        db_url=r.db_url or "",
        api_keys=r.api_keys if isinstance(r.api_keys, dict) else {},
        test_report=r.test_report or "",
        verification_report=r.verification_report or "",
        test_passed=bool(r.test_passed),
        requirements_met=bool(r.requirements_met),
        verified_findings=r.verified_findings or [],
        revision_count=r.revision_count or 0,
        record_id=r.id,
        preview_html=preview_html,
    )
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=verireview_project_{task_id}.zip"},
    )


@app.get("/preview/{task_id}")
def preview_project(
    task_id: int,
    db: Session = Depends(get_db),
    owner: Optional[str] = Query(default=None),
    x_user_email: Optional[str] = Header(default=None),
):
    from fastapi.responses import HTMLResponse
    r = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
    if not r:
        return HTMLResponse("<h3>Project not found</h3>", status_code=404)
    owner_email = _resolve_owner(query_email=owner, header_email=x_user_email)
    record_owner = _normalize_email(r.owner_email)
    if owner_email:
        if record_owner != owner_email:
            return HTMLResponse("<h3>Project not found</h3>", status_code=404)
    elif record_owner:
        return HTMLResponse("<h3>Project not found</h3>", status_code=404)
    return HTMLResponse(_build_standalone_preview(r.frontend_code or "", r.task or f"Project {r.id}"))


def _sanitize_frontend_for_preview(code: str) -> str:
    """Strip imports/exports so raw App.jsx can run under Babel in a browser."""
    lines = []
    for line in (code or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") and " from " in stripped:
            continue
        if stripped.startswith("import{") or stripped.startswith("import{"):
            continue
        if stripped.startswith("export default"):
            lines.append(stripped.replace("export default", ""))
            continue
        if stripped.startswith("export "):
            lines.append(line.replace("export ", "", 1))
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if "function App" not in cleaned and "const App" not in cleaned and "class App" not in cleaned:
        # Wrap unknown snippets so preview still renders something.
        cleaned = f"function App() {{\n  return (<div style={{{{padding:24}}}}><pre>{{`{cleaned[:2000]}`}}</pre></div>);\n}}"
    return cleaned


_PREVIEW_MOCK_JS = """window.__VR_PREVIEW__ = (function() {
  function ph(seed) {
    var s = String(seed || "VR").slice(0, 16);
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='300'>"
      + "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
      + "<stop offset='0' stop-color='#c7d2fe'/><stop offset='1' stop-color='#818cf8'/>"
      + "</linearGradient></defs>"
      + "<rect width='400' height='300' fill='url(#g)'/>"
      + "<text x='200' y='155' font-size='22' text-anchor='middle' fill='#312e81'>" + s + "</text></svg>";
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  }
  function products() {
    var names = ["Aurora Headphones", "Nimbus Sneakers", "Vertex Watch", "Lumen Lamp", "Orbit Backpack", "Pulse Speaker"];
    var cats = ["Electronics", "Fashion", "Wearables", "Home", "Travel", "Audio"];
    var prices = [49.99, 89.99, 199.99, 39.99, 59.99, 129.99];
    var ratings = [4.8, 4.6, 4.9, 4.5, 4.7, 4.8];
    return names.map(function(n, i) {
      return { id: i + 1, name: n, title: n, price: prices[i], image: ph(n.split(" ")[0]),
        description: "Top-rated " + n.toLowerCase() + " with free shipping and easy returns.",
        category: cats[i], rating: ratings[i], stock: [12, 5, 8, 20, 15, 7][i] };
    });
  }
  function books() {
    var data = [["The Silent API", "Ada Lovelace"], ["Refactoring Reality", "Martin Fowler"], ["Clean Previews", "Grace Hopper"], ["Domain Patterns", "Eric Evans"]];
    return data.map(function(b, i) {
      return { id: i + 1, title: b[0], name: b[0], author: b[1], price: [19.99, 29.99, 24.99, 34.99][i],
        cover: ph("Book"), image: ph("Book"), description: "A must-read for every software shelf.", category: "Books", rating: 4.7 };
    });
  }
  function users() {
    var data = [["Aarav Sharma", "Admin"], ["Sofia Reyes", "Customer"], ["Liam Carter", "Seller"], ["Mia Khan", "Support"]];
    return data.map(function(u, i) {
      return { id: i + 1, name: u[0], username: u[0].toLowerCase().replace(/ /g, "."), email: u[0].toLowerCase().replace(/ /g, ".") + "@example.com",
        role: u[1], avatar: ph(u[0].split(" ")[0]), image: ph(u[0].split(" ")[0]) };
    });
  }
  function todos() {
    var data = ["Design the home page", "Wire up product listings", "Add cart checkout", "Write API docs"];
    return data.map(function(t, i) {
      return { id: i + 1, title: t, name: t, completed: i < 2, status: i < 2 ? "done" : "open" };
    });
  }
  function orders() {
    return [101, 102, 103].map(function(n, i) {
      return { id: n, total: [59.98, 129.99, 24.99][i], status: ["delivered", "shipped", "processing"][i],
        product: ["Aurora Headphones", "Vertex Watch", "Lumen Lamp"][i], name: "Order #" + n, date: "2026-09-0" + (i + 1) };
    });
  }
  function generic() {
    return [1, 2, 3, 4].map(function(i) {
      return { id: i, name: "Item " + i, title: "Item " + i, description: "Sample record " + i + " for preview.",
        image: ph("Item " + i), status: "active", price: i * 10 + 9.99 };
    });
  }
  function pick(u) {
    u = String(u || "").toLowerCase();
    if (u.indexOf("product") >= 0 || u.indexOf("shop") >= 0 || u.indexOf("store") >= 0 || u.indexOf("cart") >= 0 || u.indexOf("categor") >= 0) return products();
    if (u.indexOf("book") >= 0) return books();
    if (u.indexOf("user") >= 0 || u.indexOf("employee") >= 0 || u.indexOf("customer") >= 0 || u.indexOf("member") >= 0) return users();
    if (u.indexOf("todo") >= 0 || u.indexOf("task") >= 0) return todos();
    if (u.indexOf("order") >= 0) return orders();
    return generic();
  }
  function envelope(items) {
    var arr = items.slice();
    var keys = ["products", "items", "data", "results", "content", "books", "users", "orders", "todos", "tasks"];
    for (var i = 0; i < keys.length; i++) arr[keys[i]] = arr;
    return arr;
  }
  var origFetch = window.fetch;
  window.fetch = function(url, opts) {
    try {
      var raw = (url && url.url) || url || "";
      var u = String(raw);
      var low = u.toLowerCase();
      var method = ((opts && opts.method) || "GET").toUpperCase();
      var isApi = low.indexOf("/api/") >= 0 || u.charAt(0) === "/" || low.indexOf("localhost") >= 0
        || low.indexOf(":8080") >= 0 || low.indexOf(":8000") >= 0 || low.indexOf(":5000") >= 0 || low.indexOf(":3000") >= 0;
      if (isApi) {
        if (method === "POST" || method === "PUT" || method === "PATCH") {
          var created = { id: Date.now(), ok: true };
          try { created = Object.assign({ id: Date.now() }, JSON.parse(opts.body || "{}")); } catch (e) {}
          return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve(created); }, text: function() { return Promise.resolve(JSON.stringify(created)); } });
        }
        if (method === "DELETE") {
          return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve({ ok: true }); }, text: function() { return Promise.resolve("{}"); } });
        }
        var items = envelope(pick(u));
        return Promise.resolve({ ok: true, status: 200, json: function() { return Promise.resolve(items); }, text: function() { return Promise.resolve(JSON.stringify(items.slice())); } });
      }
    } catch (e) {}
    return origFetch.apply(this, arguments);
  };
  document.addEventListener("error", function(e) {
    var t = e.target;
    if (t && t.tagName === "IMG" && !t.__vrFixed) { t.__vrFixed = true; t.src = ph(t.alt || "image"); }
  }, true);
  window.addEventListener("error", function(e) {
    var box = document.getElementById("preview-error");
    if (box) { box.style.display = "block"; box.textContent = "Preview error: " + (e.message || e.error); }
  });
})();"""

_PREVIEW_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{TITLE} - Preview</title>
<style>
  body { margin: 0; font-family: Inter, system-ui, sans-serif; background: #f8fafc; color: #0f172a; }
  #preview-note { background: #4f46e5; color: #fff; font-size: 12px; padding: 8px 14px; }
  #root { padding: 24px; max-width: 1100px; margin: 0 auto; min-height: 200px; }
  #preview-loading { color: #64748b; font-size: 13px; padding: 24px 0; }
  #preview-error { display: none; margin: 16px; padding: 12px; background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; border-radius: 8px; font-size: 13px; white-space: pre-wrap; }
  #root img { max-width: 100%; }
</style>
</head>
<body>
<div id="preview-note">VeriReview UI preview - backend API calls are mocked with realistic sample data.</div>
<div id="preview-error"></div>
<div id="root"><div id="preview-loading">Loading preview…</div></div>
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<script>
__MOCK__
</script>
<script type="text/babel" data-presets="react">
const { useState, useEffect, useRef, useMemo } = React;
__APP__
try {
  const root = ReactDOM.createRoot(document.getElementById("root"));
  root.render(React.createElement(typeof App !== "undefined" ? App : function() { return React.createElement("div", null, "No App component found"); }));
} catch (err) {
  document.getElementById("preview-error").style.display = "block";
  document.getElementById("preview-error").textContent = "Preview error: " + err.message;
}
</script>
</body>
</html>"""


def _build_standalone_preview(frontend_code: str, task_title: str) -> str:
    app_body = _sanitize_frontend_for_preview(frontend_code or "// No frontend generated")
    # Escape closing script tag inside generated code.
    app_body = app_body.replace("</script>", "<\\/script>")
    safe_title = (task_title or "VeriReview Preview").replace("<", "&lt;").replace(">", "&gt;")[:120]
    return (
        _PREVIEW_SHELL
        .replace("__MOCK__", _PREVIEW_MOCK_JS)
        .replace("__APP__", app_body)
        .replace("{TITLE}", safe_title)
    )


def _stage_for_message(message: str) -> str:
    upper = (message or "").upper()
    for stage in ("PLAN:", "ARCHITECT:", "BUILD:", "TEST:", "VERIFY:", "REVIEW:", "COMPLETE:", "FAIL:"):
        if stage in upper:
            return stage.replace(":", "").lower()
    return "info"


def _partial_snapshot(state_update: dict) -> dict:
    return {
        "tech_stack": state_update.get("tech_stack", ""),
        "product_spec": state_update.get("product_spec", ""),
        "architecture": state_update.get("architecture", ""),
        "database_design": state_update.get("database_design", ""),
        "backend_code": state_update.get("backend_code", ""),
        "frontend_code": state_update.get("frontend_code", ""),
        "qa_notes": state_update.get("qa_notes", ""),
        "test_report": state_update.get("test_report", ""),
        "test_passed": state_update.get("test_passed", False),
        "verification_report": state_update.get("verification_report", ""),
        "requirements_met": state_update.get("requirements_met", False),
        "raw_findings_count": len(state_update.get("raw_findings", []) or []),
        "verified_findings": state_update.get("verified_findings", []),
        "review_passed": state_update.get("review_passed", False),
        "revision_count": state_update.get("revision_count", 0),
    }


@app.websocket("/ws/review")
async def review_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
        task = data.get("task", "")
        owner_email = _normalize_email(data.get("owner_email") or data.get("owner") or data.get("user_email"))
        tech_stack = normalize_stack(data.get("tech_stack"))
        db_url, api_keys = _normalize_secrets(data.get("db_url"), data.get("api_keys"))

        state = _initial_state(task, tech_stack=tech_stack, db_url=db_url, api_keys=api_keys)
        last_log_count = 0

        async def emit_new_logs():
            nonlocal last_log_count
            current_logs = state.get("steps_log", [])
            while last_log_count < len(current_logs):
                message = current_logs[last_log_count]
                await websocket.send_json({
                    "type": "step",
                    "message": message,
                    "stage": _stage_for_message(message),
                    "partial": _partial_snapshot(state),
                })
                last_log_count += 1

        # Phase 1: build -> test -> verify -> review, then PAUSE for approval.
        for node in PHASE1_NODES:
            state = node(state)
            await emit_new_logs()

        # Persist the paused run so approval can resume even after reconnect.
        db = SessionLocal()
        try:
            record = TaskRecord(
                task=task,
                owner_email=owner_email,
                status="awaiting_approval",
                tech_stack=tech_stack,
                db_url=db_url,
                api_keys=api_keys,
                product_spec=state["product_spec"],
                architecture=state["architecture"],
                database_design=state["database_design"],
                backend_code=state["backend_code"],
                frontend_code=state["frontend_code"],
                qa_notes=state.get("qa_notes", ""),
                test_report=state.get("test_report", ""),
                test_passed=state.get("test_passed", False),
                verification_report=state.get("verification_report", ""),
                requirements_met=state.get("requirements_met", False),
                documentation="",
                deployment_config="",
                verified_findings=state.get("verified_findings", []),
                revision_count=state.get("revision_count", 0),
                revision_history=state.get("revision_history", []),
                phase_state=dict(state),
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            run_id = record.id
        finally:
            db.close()

        await websocket.send_json({
            "type": "awaiting_approval",
            "run_id": run_id,
            **approval_summary(state),
            "partial": _partial_snapshot(state),
        })

        # Wait for the user: approve the AI fix or finish without fixing.
        try:
            decision = await asyncio.wait_for(websocket.receive_json(), timeout=15 * 60)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "approval_timeout", "run_id": run_id})
            return
        approved = (decision.get("action") or "").lower() == "approve"

        if approved and needs_fix(state):
            await websocket.send_json({"type": "fixing", "run_id": run_id})
            while needs_fix(state):
                for node in FIX_NODES:
                    state = node(state)
                    await emit_new_logs()

        state = run_finalize(state)
        await emit_new_logs()

        db = SessionLocal()
        try:
            record = db.query(TaskRecord).filter(TaskRecord.id == run_id).first()
            if record is not None:
                _apply_state_to_record(record, state, status="completed")
                record.phase_state = None
                db.commit()
                db.refresh(record)
                record_id = record.id
            else:
                record = TaskRecord(
                    task=task,
                    owner_email=owner_email,
                    status="completed",
                    tech_stack=tech_stack,
                    db_url=db_url,
                    api_keys=api_keys,
                    product_spec=state["product_spec"],
                    architecture=state["architecture"],
                    database_design=state["database_design"],
                    backend_code=state["backend_code"],
                    frontend_code=state["frontend_code"],
                    qa_notes=state.get("qa_notes", ""),
                    test_report=state.get("test_report", ""),
                    test_passed=state.get("test_passed", False),
                    verification_report=state.get("verification_report", ""),
                    requirements_met=state.get("requirements_met", False),
                    documentation=state.get("documentation", ""),
                    deployment_config=state.get("deployment_config", ""),
                    verified_findings=state.get("verified_findings", []),
                    revision_count=state.get("revision_count", 0),
                    revision_history=state.get("revision_history", []),
                )
                db.add(record)
                db.commit()
                db.refresh(record)
                record_id = record.id
        finally:
            db.close()

        await websocket.send_json({
            "type": "done",
            "result": _record_to_dict(state, record_id, status="completed"),
        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass