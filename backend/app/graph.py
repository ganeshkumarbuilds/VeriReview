import json
import time
from langgraph.graph import StateGraph, END
from app.state import ReviewState
from app.config import get_llm, FREE_MODELS
from app.rag import retrieve_context
from app.file_utils import parse_files


def _clean_json_text(raw_text: str) -> str:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].strip()
    return raw_text


def _clean_code_text(raw_text: str) -> str:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        parts = raw_text.split("```")
        raw_text = parts[1] if len(parts) > 1 else raw_text
        for lang in ("java", "jsx", "javascript", "js", "markdown", "yaml"):
            if raw_text.lower().startswith(lang):
                raw_text = raw_text[len(lang):].strip()
    return raw_text.strip()


def _invoke_with_fallback(prompt: str, temperature: float = 0.2):
    last_error = None
    for model_name in FREE_MODELS:
        llm = get_llm(model_name, temperature=temperature)
        try:
            print(f"[llm] Trying model: {model_name}")
            response = llm.invoke(prompt)
            print(f"[llm] Success with model: {model_name}")
            return response
        except Exception as e:
            print(f"[llm] {model_name} failed: {e}")
            last_error = e
            time.sleep(1)
    raise last_error


DEFAULT_STACK = "Spring Boot + React"


def detect_family(tech_stack: str) -> str:
    """Map a free-text tech stack to a backend family for prompts + ZIP layout."""
    s = (tech_stack or "").lower()
    if "django" in s:
        return "django"
    if "flask" in s or "fastapi" in s:
        return "python"
    if "node" in s or "express" in s or "nestjs" in s or "nest.js" in s:
        return "node"
    if "spring" in s or "java" in s:
        return "spring"
    if "python" in s:
        return "python"
    if "javascript" in s or "typescript" in s:
        return "node"
    return "generic"


def normalize_stack(tech_stack: str) -> str:
    cleaned = (tech_stack or "").strip()
    return cleaned or DEFAULT_STACK


def friendly_llm_error(e: Exception) -> str:
    msg = str(e)
    if "429" in msg or "Rate limit" in msg or "rate limit" in msg:
        return ("AI model quota exhausted (OpenRouter free-tier daily limit). "
                "Wait for the daily reset or add credits, then run again.")
    if "401" in msg or "Unauthorized" in msg or "invalid" in msg.lower():
        return "AI API key rejected. Check OPENROUTER_API_KEY on the backend."
    return f"AI call failed: {msg[:200]}"


def mark_generation_failed(state: dict, e: Exception) -> None:
    state["generation_failed"] = True
    err = friendly_llm_error(e)
    prev = state.get("generation_error") or ""
    state["generation_error"] = (prev + " | " + err) if prev and err not in prev else (prev or err)


# --- Agent 1: Product Manager ---
def product_manager_node(state: ReviewState) -> ReviewState:
    prompt = f"""You are a product manager. Turn this idea into a precise, buildable spec.

Idea: {state['task']}

Tech stack to use: {state.get('tech_stack') or DEFAULT_STACK}

List: core features (5-8 bullets), primary user flows, and out-of-scope items.
Be concise and concrete.
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.3)
        spec = response.content.strip()
    except Exception as e:
        spec = f"Product spec unavailable: {friendly_llm_error(e)}"

    state["product_spec"] = spec
    state["revision_count"] = 0
    state["max_revisions"] = 1
    state["revision_history"] = []
    state["test_passed"] = False
    state["requirements_met"] = False
    state["review_passed"] = False
    state["test_report"] = ""
    state["verification_report"] = ""
    state["steps_log"].append("PLAN: Product Manager turned the idea into a product spec")
    return state


# --- Agent 2: Architect ---
def architect_node(state: ReviewState) -> ReviewState:
    tech_stack = state.get('tech_stack') or DEFAULT_STACK
    prompt = f"""You are a software architect specializing in {tech_stack}.

Product spec:
{state['product_spec']}

Design the system architecture: module/package structure, REST API endpoints
(method, path, purpose), and key frontend pages/components. 8-12 bullets, no code.
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.3)
        architecture = response.content.strip()
    except Exception as e:
        architecture = f"Architecture unavailable: {friendly_llm_error(e)}"

    state["architecture"] = architecture
    state["steps_log"].append("ARCHITECT: Architect designed the system architecture")
    return state


# --- Agent 3: Database Engineer ---
def database_engineer_node(state: ReviewState) -> ReviewState:
    prompt = f"""You are a database engineer. Design the data model.

Architecture:
{state['architecture']}

List entities, fields, types, and relationships. Note any indexes needed.
Concise bullet list, no code.
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.2)
        db_design = response.content.strip()
    except Exception as e:
        db_design = f"Database design unavailable: {friendly_llm_error(e)}"

    state["database_design"] = db_design
    state["steps_log"].append("ARCHITECT: Database Engineer designed the data model")
    return state


# --- Agent 4: Backend Engineer (BUILD) ---
# Also acts as the CODING AGENT FIX step when looping back after a FAIL.
# Stack-aware: the file markers and framework expectations follow the
# user-selected tech stack (Java: `// FILE:`, Python/JS: `# FILE:`).
def _backend_instructions(family: str) -> tuple:
    if family == "django":
        return (
            "Django REST framework backend engineer",
            "Write the complete backend as multiple Python files (models, serializers, "
            "views, urls). For EACH file, start with a line exactly like: # FILE: app/models.py\n"
            "Use relative paths. Include models, serializers, viewsets and URL routes.",
            "# FILE: app/models.py\n# Backend generation failed: ",
        )
    if family == "python":
        return (
            "Python backend engineer (Flask/FastAPI)",
            "Write the complete backend as multiple Python files (models, routes, app entrypoint). "
            "For EACH file, start with a line exactly like: # FILE: app.py\n"
            "Use relative paths. Include models, route handlers and the app entrypoint.",
            "# FILE: app.py\n# Backend generation failed: ",
        )
    if family == "node":
        return (
            "Node.js + Express backend engineer",
            "Write the complete backend as multiple JavaScript files (models, routes, controllers, "
            "server entrypoint). For EACH file, start with a line exactly like: # FILE: server.js\n"
            "Use relative paths. Include models, route handlers and the server entrypoint.",
            "# FILE: server.js\n// Backend generation failed: ",
        )
    if family == "generic":
        return (
            "senior backend engineer",
            "Write the complete backend as multiple source files. For EACH file, start with a line "
            "exactly like: // FILE: path/to/File.ext (or # FILE: path/to/file.ext for # comments).\n"
            "Use relative paths. Cover models, business logic and API/controllers.",
            "// FILE: backend.txt\n// Backend generation failed: ",
        )
    return (
        "Spring Boot backend engineer",
        "Write the complete backend as multiple Java files. For EACH file, start with a line\n"
        "exactly like: // FILE: ClassName.java\n"
        "Include Entity, Repository, Service, and Controller classes.",
        "// FILE: Error.java\n// Backend generation failed: ",
    )


def backend_engineer_node(state: ReviewState) -> ReviewState:
    tech_stack = state.get('tech_stack') or DEFAULT_STACK
    family = state.get('stack_family') or detect_family(tech_stack)
    role, instructions, error_prefix = _backend_instructions(family)
    feedback_section = ""
    if state["verified_findings"] or not state.get("requirements_met", True) or not state.get("test_passed", True):
        issues_text = "\n".join(
            f"- [{f['severity'].upper()}] ({f.get('file', 'unknown')}) {f['category']}: {f['issue']}"
            for f in state["verified_findings"]
        )
        test_section = f"\nTest report:\n{state.get('test_report', '')}" if not state.get("test_passed", True) else ""
        verify_section = f"\nVerification report:\n{state.get('verification_report', '')}" if not state.get("requirements_met", True) else ""
        feedback_section = f"""

Your PREVIOUS version FAILED (revision {state['revision_count']} of {state['max_revisions']}).
Fix ALL confirmed issues below, plus any test/verification failures:
{issues_text}{test_section}{verify_section}

Previous backend code:
{state['backend_code']}
"""

    prompt = f"""You are a {role}.

Tech stack: {tech_stack}

Product spec: {state['product_spec']}
Architecture: {state['architecture']}
Database design: {state['database_design']}
{feedback_section}

{instructions}
Respond with ONLY the code (using the FILE: markers), no explanation.
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.2)
        code = _clean_code_text(response.content)
    except Exception as e:
        code = f"{error_prefix}{friendly_llm_error(e)}"
        mark_generation_failed(state, e)

    state["backend_code"] = code
    state["diff"] = code

    attempt_label = "initial backend" if state["revision_count"] == 0 else f"backend revision {state['revision_count']}"
    state["steps_log"].append(f"BUILD: Backend Engineer (Coding Agent) generated {attempt_label}")
    return state


# --- Retrieval (RAG tool) ---
def retrieve_context_node(state: ReviewState) -> ReviewState:
    context = retrieve_context(state["diff"])
    state["context"] = context
    state["steps_log"].append("Retrieved relevant backend/OWASP context for review")
    return state


# --- REVIEW stage: Reviewer (single batched scan) + finding verifier ---
# Perf: one LLM call for ALL files instead of one call per file.
def reviewer_node(state: ReviewState) -> ReviewState:
    files = {name: content for name, content in parse_files(state["diff"]).items() if content.strip()}
    if not files:
        state["raw_findings"] = []
        state["steps_log"].append("REVIEW: Reviewer scanned 0 file(s), found 0 candidate issue(s)")
        return state

    bundle = "\n\n".join(f"===== FILE: {name} =====\n{content[:4000]}" for name, content in files.items())
    tech_stack = state.get('tech_stack') or DEFAULT_STACK
    prompt = f"""You are a senior {tech_stack} code reviewer.

Relevant knowledge:
{state['context']}

Review ALL files below and list potential issues.
Respond ONLY with valid JSON, a list of objects (include the file for each):
[{{"file": "ClassName.java", "line": null, "category": "Security Issue", "issue": "short description", "severity": "high"}}]
Valid categories: "Security Issue", "Error Handling Missing", "Performance", "Suggestion".
Valid severities: "high", "medium", "low".
If none, respond with []

Files:
{bundle}
"""
    all_findings = []
    try:
        response = _invoke_with_fallback(prompt, temperature=0.2)
        raw_text = _clean_json_text(response.content)
        findings = json.loads(raw_text)
        for f in findings:
            if not f.get("file"):
                f["file"] = next(iter(files))
            all_findings.append(f)
    except Exception as e:
        state["steps_log"].append(f"Analysis failed: {friendly_llm_error(e)}")

    state["raw_findings"] = all_findings
    state["steps_log"].append(f"REVIEW: Reviewer scanned {len(files)} file(s), found {len(all_findings)} candidate issue(s)")
    return state


# --- VERIFY stage: Verified Agent ---
# Checks the implementation against the original task/requirements.
# Sets requirements_met used by the PASS/FAIL gate.
def verifier_node(state: ReviewState) -> ReviewState:
    prompt = f"""You are a verification engineer checking whether the implementation satisfies the original task.

Original task:
{state['task']}

Product spec:
{state['product_spec']}

Backend code (summary):
{state['backend_code'][:1500]}

Frontend code (summary):
{(state.get('frontend_code') or '')[:800]}

Test report:
{state.get('test_report', '')[:800]}

Does the implementation satisfy the task requirements?
Respond ONLY with valid JSON: {{"verdict": "PASS", "reasoning": "one sentence"}} or {{"verdict": "FAIL", "reasoning": "one sentence"}}
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.0)
        raw_text = _clean_json_text(response.content)
        verdict = json.loads(raw_text)
    except Exception as e:
        verdict = {"verdict": "FAIL", "reasoning": f"Verification unavailable: {friendly_llm_error(e)}"}

    requirements_met = verdict.get("verdict") == "PASS"
    state["verification_report"] = verdict.get("reasoning", "")
    state["requirements_met"] = requirements_met
    state["steps_log"].append(
        f"VERIFY: Verified agent checked requirements: {'PASS' if requirements_met else 'FAIL'} - {state['verification_report']}"
    )
    return state


def route_after_verification(state: ReviewState) -> str:
    # Legacy hook kept for compatibility; the real PASS/FAIL gate is after REVIEW.
    if not state.get("requirements_met", True) and state["revision_count"] < state["max_revisions"]:
        return "revise"
    return "done"


def increment_revision_node(state: ReviewState) -> ReviewState:
    state["revision_count"] += 1
    state["steps_log"].append(
        f"FAIL: Review gate failed - sending back to Coding Agent for FIX "
        f"(revision {state['revision_count']} of {state['max_revisions']})"
    )
    return state


def finding_verifier_node(state: ReviewState) -> ReviewState:
    """Second half of REVIEW: confirm/reject all candidates in ONE batched call."""
    candidates = state["raw_findings"] or []
    verified = []

    if candidates:
        files = parse_files(state["diff"])
        code_ctx = "\n\n".join(
            f"===== FILE: {name} =====\n{content[:2500]}" for name, content in files.items()
        )[:12000]
        prompt = f"""You are a skeptical senior reviewer double-checking a junior reviewer's findings.

Relevant knowledge:
{state['context']}

Code under review:
{code_ctx}

Candidate findings:
{json.dumps(candidates)}

For EACH candidate, decide: REAL justified issue (CONFIRMED) or FALSE ALARM (REJECTED)?
Respond ONLY with valid JSON: {{"confirmed": [{{"index": 0, "reasoning": "one sentence"}}]}}
Use the 0-based index into the candidate list. Omit rejected ones.
"""
        try:
            response = _invoke_with_fallback(prompt, temperature=0.0)
            raw_text = _clean_json_text(response.content)
            verdict = json.loads(raw_text)
            confirmed_map = {
                item.get("index"): item.get("reasoning", "")
                for item in (verdict.get("confirmed") or [])
                if isinstance(item, dict) and isinstance(item.get("index"), int)
            }
            for i, finding in enumerate(candidates):
                if i in confirmed_map:
                    finding["verification"] = confirmed_map[i]
                    verified.append(finding)
        except Exception as e:
            state["steps_log"].append(f"Finding verification unavailable: {friendly_llm_error(e)}")

    state["verified_findings"] = verified
    has_high = any(f.get("severity") == "high" for f in verified)
    state["review_passed"] = not has_high
    state["revision_history"].append({
        "attempt": state["revision_count"] + 1,
        "backend_code": state["diff"],
        "test_passed": state.get("test_passed", False),
        "requirements_met": state.get("requirements_met", False),
        "review_passed": state["review_passed"],
        "verified_findings": verified,
    })
    state["steps_log"].append(
        f"REVIEW: Review agent confirmed {len(verified)} of {len(state['raw_findings'])} finding(s): "
        f"{'PASS' if state['review_passed'] else 'FAIL'}"
    )
    return state


def route_after_review(state: ReviewState) -> str:
    """PASS/FAIL gate from the diagram. FAIL loops to CODING AGENT FIX."""
    test_ok = state.get("test_passed", False)
    verify_ok = state.get("requirements_met", False)
    review_ok = state.get("review_passed", True)
    can_still_revise = state["revision_count"] < state["max_revisions"]
    if test_ok and verify_ok and review_ok:
        return "pass"
    if can_still_revise:
        return "fail"
    return "pass"


# --- Agent 7: Frontend Engineer ---
def frontend_engineer_node(state: ReviewState) -> ReviewState:
    tech_stack = state.get('tech_stack') or DEFAULT_STACK
    prompt = f"""You are a React frontend engineer.

Product spec: {state['product_spec']}
Architecture: {state['architecture']}

Backend ({tech_stack}) API (for reference, call these endpoints with fetch):
{state['backend_code'][:1500]}

Write a single React functional component (App.jsx style) using fetch to call the
backend API described above. Plain CSS classNames, no external UI libraries.
Import nothing except React. Keep the component compact (under ~200 lines).
Respond with ONLY the code, no explanation.
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.3)
        code = _clean_code_text(response.content)
    except Exception as e:
        code = f"// Frontend generation failed: {friendly_llm_error(e)}"
        mark_generation_failed(state, e)

    state["frontend_code"] = code
    state["steps_log"].append("BUILD: Frontend Engineer built the React UI")
    return state


# --- TEST stage: QA / Testing Agent ---
# Generates test cases (LLM) + runs lightweight automated checks.
# Sets test_passed used by the PASS/FAIL gate.
def qa_engineer_node(state: ReviewState) -> ReviewState:
    prompt = f"""You are a QA engineer. Review this app for test coverage gaps.

Backend code (summary):
{state['backend_code'][:1200]}

Frontend code (summary):
{(state.get('frontend_code') or '')[:600]}

List 5-8 test cases that should exist (unit or integration), as short bullet points.
Do not write actual test code, just the list.
"""
    try:
        response = _invoke_with_fallback(prompt, temperature=0.3)
        qa_notes = response.content.strip()
        llm_ok = True
    except Exception as e:
        qa_notes = f"QA review unavailable: {friendly_llm_error(e)}"
        llm_ok = False

    # Lightweight automated checks (deterministic, no external runner needed)
    family = state.get("stack_family") or detect_family(state.get("tech_stack"))
    auto_checks = []
    backend_files = parse_files(state.get("backend_code") or "")
    if not backend_files:
        auto_checks.append("FAIL: no backend files parsed")
    else:
        auto_checks.append(f"PASS: parsed {len(backend_files)} backend file(s)")
    blob = (state.get("backend_code") or "").lower()
    if family == "spring":
        structure_ok = ("class" in blob and ("controller" in blob or "service" in blob)) or len(backend_files) >= 2
        structure_msg = "entity/service/controller structure present"
    elif family == "django":
        structure_ok = ("model" in blob and ("view" in blob or "url" in blob)) or len(backend_files) >= 2
        structure_msg = "models/views/urls structure present"
    elif family == "node":
        structure_ok = ("express" in blob or "route" in blob) or len(backend_files) >= 2
        structure_msg = "routes/server structure present"
    elif family == "python":
        structure_ok = ("route" in blob or "app" in blob or "def " in blob) or len(backend_files) >= 1
        structure_msg = "routes/app structure present"
    else:
        structure_ok = len(backend_files) >= 1
        structure_msg = "backend files present"
    if structure_ok:
        auto_checks.append(f"PASS: {structure_msg}")
    else:
        auto_checks.append(f"FAIL: expected backend structure missing ({structure_msg})")
    if (state.get("frontend_code") or "").strip():
        auto_checks.append("PASS: frontend code present")
    else:
        auto_checks.append("FAIL: frontend code empty")

    test_passed = llm_ok and all(c.startswith("PASS") for c in auto_checks)
    test_report = qa_notes + "\n\nAutomated checks:\n" + "\n".join(f"- {c}" for c in auto_checks)

    state["qa_notes"] = qa_notes
    state["test_report"] = test_report
    state["test_passed"] = test_passed
    state["steps_log"].append(f"TEST: Testing agent ran tests: {'PASS' if test_passed else 'FAIL'}")
    return state


# --- COMPLETE stage: docs + deployment in PARALLEL (independent prompts) ---
def finalize_node(state: ReviewState) -> ReviewState:
    from concurrent.futures import ThreadPoolExecutor

    tech_stack = state.get('tech_stack') or DEFAULT_STACK
    docs_prompt = f"""You are a documentation engineer. Write a concise README.md for this project.

Product spec: {state['product_spec']}
Architecture: {state['architecture']}

Include: project overview, tech stack, setup steps. Keep it under 300 words. Markdown format.
"""
    deploy_prompt = f"""You are a deployment engineer. Write a simple Dockerfile for this backend ({tech_stack}).

Backend code (summary):
{state['backend_code'][:800]}

Respond with ONLY the Dockerfile content, no explanation.
"""

    def run_docs():
        try:
            return _clean_code_text(_invoke_with_fallback(docs_prompt, temperature=0.3).content)
        except Exception as e:
            return f"# Documentation generation failed: {e}"

    def run_deploy():
        try:
            return _clean_code_text(_invoke_with_fallback(deploy_prompt, temperature=0.2).content)
        except Exception as e:
            return f"# Deployment config generation failed: {e}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        docs_future = pool.submit(run_docs)
        deploy_future = pool.submit(run_deploy)
        state["documentation"] = docs_future.result()
        state["deployment_config"] = deploy_future.result()

    state["steps_log"].append("COMPLETE: Documentation Engineer wrote the README")
    state["steps_log"].append("COMPLETE: Deployment Engineer created Docker configuration")
    state["steps_log"].append("COMPLETE: Packager assembled project, ready for export")
    return state


def build_graph():
    # USER TASK -> PLAN -> ARCHITECT -> BUILD -> TEST -> VERIFY -> REVIEW
    #            REVIEW -> PASS -> COMPLETE
    #            REVIEW -> FAIL -> CODING AGENT FIX -> TEST -> VERIFY -> REVIEW (repeat)
    workflow = StateGraph(ReviewState)

    workflow.add_node("product_manager", product_manager_node)
    workflow.add_node("architect", architect_node)
    workflow.add_node("database_engineer", database_engineer_node)
    workflow.add_node("backend_engineer", backend_engineer_node)
    workflow.add_node("frontend_engineer", frontend_engineer_node)
    workflow.add_node("qa_engineer", qa_engineer_node)
    workflow.add_node("verifier", verifier_node)
    workflow.add_node("retrieve_context", retrieve_context_node)
    workflow.add_node("reviewer", reviewer_node)
    workflow.add_node("finding_verifier", finding_verifier_node)
    workflow.add_node("increment_revision", increment_revision_node)
    workflow.add_node("finalize", finalize_node)

    workflow.set_entry_point("product_manager")
    workflow.add_edge("product_manager", "architect")
    workflow.add_edge("architect", "database_engineer")
    workflow.add_edge("database_engineer", "backend_engineer")
    workflow.add_edge("backend_engineer", "frontend_engineer")
    workflow.add_edge("frontend_engineer", "qa_engineer")
    workflow.add_edge("qa_engineer", "verifier")
    workflow.add_edge("verifier", "retrieve_context")
    workflow.add_edge("retrieve_context", "reviewer")
    workflow.add_edge("reviewer", "finding_verifier")

    workflow.add_conditional_edges(
        "finding_verifier",
        route_after_review,
        {
            "pass": "finalize",
            "fail": "increment_revision",
        },
    )

    workflow.add_edge("increment_revision", "backend_engineer")
    workflow.add_edge("finalize", END)

    return workflow.compile()


# ------------------------------------------------------------------
# Human-in-the-loop orchestration (approval gate before auto-fix).
# Phase 1: build -> test -> verify -> review, then PAUSE and show the
# result to the user. Only after the user approves does the coding
# agent fix files, followed by re-verify + re-review, then finalize.
# ------------------------------------------------------------------

def initial_state(
    task: str,
    tech_stack: str = "",
    db_url: str = "",
    api_keys: dict = None,
) -> ReviewState:
    stack = normalize_stack(tech_stack)
    return {
        "task": task,
        "tech_stack": stack,
        "stack_family": detect_family(stack),
        "db_url": (db_url or "").strip(),
        "api_keys": dict(api_keys or {}),
        "generation_failed": False,
        "generation_error": "",
        "product_spec": "",
        "architecture": "",
        "database_design": "",
        "backend_code": "",
        "frontend_code": "",
        "qa_notes": "",
        "test_report": "",
        "test_passed": False,
        "verification_report": "",
        "requirements_met": False,
        "documentation": "",
        "deployment_config": "",
        "diff": "",
        "context": "",
        "raw_findings": [],
        "verified_findings": [],
        "review_passed": False,
        "revision_count": 0,
        "max_revisions": 1,
        "revision_history": [],
        "steps_log": [],
    }


# Verify + review are independent (both read the built code), so run them
# in parallel to cut one sequential LLM call per pass. The finding
# verifier still runs after both are done.
def verify_review_parallel_node(state: ReviewState) -> ReviewState:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        verify_future = pool.submit(verifier_node, state)
        review_future = pool.submit(reviewer_node, state)
        state = verify_future.result()
        state = review_future.result()
    return state


PHASE1_NODES = (
    product_manager_node,
    architect_node,
    database_engineer_node,
    backend_engineer_node,
    frontend_engineer_node,
    qa_engineer_node,
    retrieve_context_node,
    verify_review_parallel_node,
    finding_verifier_node,
)

# One coding-agent fix cycle: count revision, fix code, re-test,
# re-verify, re-review.
FIX_NODES = (
    increment_revision_node,
    backend_engineer_node,
    frontend_engineer_node,
    qa_engineer_node,
    retrieve_context_node,
    verify_review_parallel_node,
    finding_verifier_node,
)


def is_clean(state: dict) -> bool:
    return (
        bool(state.get("test_passed"))
        and bool(state.get("requirements_met"))
        and bool(state.get("review_passed", True))
    )


def needs_fix(state: dict) -> bool:
    return (not is_clean(state)) and state.get("revision_count", 0) < state.get("max_revisions", 1)


def run_phase1(
    task: str,
    tech_stack: str = "",
    db_url: str = "",
    api_keys: dict = None,
) -> ReviewState:
    state = initial_state(task, tech_stack=tech_stack, db_url=db_url, api_keys=api_keys)
    for node in PHASE1_NODES:
        state = node(state)
    return state


def run_fix_iteration(state: dict) -> dict:
    for node in FIX_NODES:
        state = node(state)
    return state


def run_fix_loop(state: dict) -> dict:
    while needs_fix(state):
        state = run_fix_iteration(state)
    return state


def run_finalize(state: dict) -> dict:
    return finalize_node(state)


def approval_summary(state: dict) -> dict:
    findings = state.get("verified_findings") or []
    return {
        "test_passed": bool(state.get("test_passed")),
        "requirements_met": bool(state.get("requirements_met")),
        "review_passed": bool(state.get("review_passed", True)),
        "is_clean": is_clean(state),
        "needs_fix": needs_fix(state),
        "generation_failed": bool(state.get("generation_failed")),
        "generation_error": state.get("generation_error", ""),
        "revision_count": state.get("revision_count", 0),
        "max_revisions": state.get("max_revisions", 1),
        "verified_findings": findings,
        "test_report": state.get("test_report", ""),
        "verification_report": state.get("verification_report", ""),
    }