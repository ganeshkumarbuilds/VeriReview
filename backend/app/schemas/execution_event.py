from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.execution_event import ExecutionEventType


class ExecutionEventResponse(BaseModel):
    id: UUID
    project_id: UUID
    agent_execution_id: UUID | None
    event_type: ExecutionEventType
    message: str
    event_data: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExecutionEventListResponse(BaseModel):
    events: list[ExecutionEventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int