from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.connection import Base


class ArtifactType(str, Enum):
    PROJECT_ZIP = "PROJECT_ZIP"
    BUILD_OUTPUT = "BUILD_OUTPUT"
    PREVIEW = "PREVIEW"


class ArtifactStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class ProjectArtifact(Base):
    __tablename__ = "project_artifacts"

    __table_args__ = (
        Index(
            "ix_project_artifacts_project_created",
            "project_id",
            "created_at",
        ),
        CheckConstraint(
            "file_size IS NULL OR file_size >= 0",
            name="ck_project_artifacts_file_size_nonnegative",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_project_artifacts_expiration_after_creation",
        ),
        CheckConstraint(
            "length(trim(file_name)) > 0",
            name="ck_project_artifacts_file_name_not_empty",
        ),
        CheckConstraint(
            "length(trim(storage_path)) > 0",
            name="ck_project_artifacts_storage_path_not_empty",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    project_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    artifact_type: Mapped[ArtifactType] = mapped_column(
        SQLAlchemyEnum(
            ArtifactType,
            name="artifact_type",
        ),
        nullable=False,
    )

    status: Mapped[ArtifactStatus] = mapped_column(
        SQLAlchemyEnum(
            ArtifactStatus,
            name="artifact_status",
        ),
        default=ArtifactStatus.PENDING,
        nullable=False,
    )

    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    storage_path: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
    )

    file_size: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    checksum: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    preview_url: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="artifacts",
    )