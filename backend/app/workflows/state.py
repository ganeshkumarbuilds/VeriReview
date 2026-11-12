from typing import Any, Literal, TypedDict


WorkflowType = Literal[
    "GENERATION",
    "REVIEW",
]

WorkflowStatus = Literal[
    "RUNNING",
    "WAITING_FOR_APPROVAL",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
]

AgentName = Literal[
    "PLANNING",
    "CODING",
    "VERIFYING",
    "REVIEW",
]


ApprovalDecision = Literal[
    "APPROVED",
    "REJECTED",
]


class AgentWorkflowState(TypedDict, total=False):
    """
    Shared state passed between VeriReview agents.

    LangGraph manages workflow coordination.
    PostgreSQL and project storage remain the
    permanent source of truth.
    """

    # Workflow identity
    workflow_id: str
    workflow_type: WorkflowType
    project_id: str

    # Execution status
    current_agent: AgentName | None
    workflow_status: WorkflowStatus
    progress_percentage: int
    iteration: int

    # User requirements
    requirements: str | None
    technology_stack: str | dict[str, Any] | list[str]

    # Generation plan
    generation_plan_id: str | None
    generation_plan: dict[str, Any] | None
    architecture: dict[str, Any] | None
    folder_structure: dict[str, Any] | None
    implementation_plan: dict[str, Any] | None
    estimated_files: int

    # Generated project files
    generated_files: list[dict[str, Any]]
    project_file_ids: list[str]

    # Review information
    review_id: str | None
    review_summary: dict[str, Any] | None
    finding_ids: list[str]

    # Fix approval and execution
    pending_fix_request_ids: list[str]
    approved_fix_request_ids: list[str]
    approval_decision: ApprovalDecision | None
    user_instruction: str | None

    # Verification
    verification_results: dict[str, Any] | None

    # Agent execution references
    agent_execution_ids: dict[str, str]

    # Error tracking
    last_error: str | None