from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.agent_execution import (
    AgentExecutionStatus,
    AgentType,
)


class AgentExecutionResponse(BaseModel):
    id: UUID
    project_id: UUID
    agent_type: AgentType
    status: AgentExecutionStatus
    execution_number: int
    progress_percentage: int
    input_data: dict | None
    output_data: dict | None
    error_message: str | None
    model_name: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentExecutionListResponse(BaseModel):
    executions: list[AgentExecutionResponse]
    total: int