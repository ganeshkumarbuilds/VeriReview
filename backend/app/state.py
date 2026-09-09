from typing import TypedDict, List, Dict, Optional


class ReviewState(TypedDict):
    task: str
    tech_stack: str
    stack_family: str
    db_url: str
    api_keys: Dict[str, str]
    generation_failed: bool
    generation_error: str
    product_spec: str
    architecture: str
    database_design: str
    backend_code: str
    frontend_code: str
    qa_notes: str
    test_report: str
    test_passed: bool
    verification_report: str
    requirements_met: bool
    documentation: str
    deployment_config: str
    diff: str
    context: str
    raw_findings: List[Dict]
    verified_findings: List[Dict]
    review_passed: bool
    revision_count: int
    max_revisions: int
    revision_history: List[Dict]
    steps_log: List[str]