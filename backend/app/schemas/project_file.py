from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.project_file import FileOrigin


class ProjectFileResponse(BaseModel):
    id: UUID
    project_id: UUID
    file_path: str
    file_name: str
    file_extension: str | None
    mime_type: str | None
    file_size: int
    origin: FileOrigin
    checksum: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectFileListResponse(BaseModel):
    files: list[ProjectFileResponse]
    total: int