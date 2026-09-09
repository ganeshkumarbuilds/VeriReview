from typing import TypedDict, List, Dict


class ReviewState(TypedDict):

    # ============================================================
    # REQUEST
    # ============================================================

    task: str
    tech_stack: str
    stack_family: str

    # ============================================================
    # USER CONFIGURATION
    # ============================================================

    db_url: str

    # Runtime API keys supplied by the user.
    # Raw secrets should not be persisted permanently.
    api_keys: Dict[str, str]

    # ============================================================
    # AI / PIPELINE HEALTH
    # ============================================================

    # True when an AI generation step failed.
    generation_failed: bool

    # Human-readable explanation of the AI failure.
    generation_error: str

    # Overall AI availability for the current run.
    #
    # Possible values:
    #   "available"
    #   "unavailable"
    ai_status: str

    # Error returned by the AI provider, if any.
    ai_error: str

    # Pipeline stage where the AI became unavailable.
    #
    # Examples:
    #   "plan"
    #   "architect"
    #   "build"
    #   "test"
    #   "verify"
    #   "review"
    #   ""
    ai_failed_stage: str

    # ============================================================
    # PLAN / ARCHITECTURE
    # ============================================================

    product_spec: str
    architecture: str
    database_design: str

    # ============================================================
    # GENERATED APPLICATION
    # ============================================================

    backend_code: str
    frontend_code: str

    # ============================================================
    # TESTING
    # ============================================================

    qa_notes: str
    test_report: str
    test_passed: bool

    # ============================================================
    # VERIFICATION
    # ============================================================

    verification_report: str
    requirements_met: bool

    # ============================================================
    # COMPLETION
    # ============================================================

    documentation: str
    deployment_config: str

    # ============================================================
    # REVIEW
    # ============================================================

    diff: str
    context: str

    # Findings produced by the first review pass.
    raw_findings: List[Dict]

    # Findings confirmed by the finding-verification pass.
    verified_findings: List[Dict]

    # True only when the review actually completed successfully
    # and no blocking findings remain.
    review_passed: bool

    # ============================================================
    # REVISION / FIX LOOP
    # ============================================================

    revision_count: int
    max_revisions: int
    revision_history: List[Dict]

    # ============================================================
    # LIVE PIPELINE LOG
    # ============================================================

    steps_log: List[str]