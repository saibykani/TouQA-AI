"""Records imported from external systems. The external system stays authoritative;
these rows are a local, synchronised copy keyed by (project_id, external_id)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JsonType, UTCDateTime, utcnow


class SyncedMixin:
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    external_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    content_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    raw: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    custom_properties: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    is_deleted_externally: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Release(SyncedMixin, Base):
    __tablename__ = "releases"
    __table_args__ = (UniqueConstraint("project_id", "external_id", name="uq_release_ext"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    version_number: Mapped[str | None] = mapped_column(String(100))
    indent_level: Mapped[str | None] = mapped_column(String(200))
    is_iteration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    type_name: Mapped[str | None] = mapped_column(String(100))
    status_name: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(UTCDateTime())
    end_date: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Requirement(SyncedMixin, Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("project_id", "external_id", name="uq_requirement_ext"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    indent_level: Mapped[str | None] = mapped_column(String(200), index=True)
    is_summary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_name: Mapped[str | None] = mapped_column(String(100), index=True)
    type_name: Mapped[str | None] = mapped_column(String(100))
    importance_name: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(200))
    author_name: Mapped[str | None] = mapped_column(String(200))
    release_external_id: Mapped[str | None] = mapped_column(String(64))
    release_version: Mapped[str | None] = mapped_column(String(100))
    component_external_id: Mapped[str | None] = mapped_column(String(64))
    tags: Mapped[str | None] = mapped_column(String(1000))
    steps: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    coverage: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    parent: Mapped["Requirement | None"] = relationship(remote_side="Requirement.id")


class Folder(SyncedMixin, Base):
    """Test case folders and test set folders."""

    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("project_id", "folder_type", "external_id", name="uq_folder_ext"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_type: Mapped[str] = mapped_column(String(20), nullable=False)  # test_case | test_set
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_external_id: Mapped[str | None] = mapped_column(String(64))
    indent_level: Mapped[str | None] = mapped_column(String(200))


class TestCase(SyncedMixin, Base):
    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("project_id", "external_id", name="uq_test_case_ext"),)
    __test__ = False  # not a pytest class
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_external_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    status_name: Mapped[str | None] = mapped_column(String(100))
    type_name: Mapped[str | None] = mapped_column(String(100))
    priority_name: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(200))
    author_name: Mapped[str | None] = mapped_column(String(200))
    execution_status_name: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[str | None] = mapped_column(String(1000))
    origin: Mapped[str] = mapped_column(String(30), default="imported", nullable=False)  # imported | touqa
    steps: Mapped[list["TestStep"]] = relationship(
        back_populates="test_case", cascade="all, delete-orphan", order_by="TestStep.position"
    )


class TestStep(Base):
    __tablename__ = "test_steps"
    __table_args__ = (UniqueConstraint("test_case_id", "external_id", name="uq_test_step_ext"),)
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expected_result: Mapped[str | None] = mapped_column(Text)
    sample_data: Mapped[str | None] = mapped_column(Text)
    precondition: Mapped[str | None] = mapped_column(Text)
    linked_test_case_external_id: Mapped[str | None] = mapped_column(String(64))
    test_case: Mapped[TestCase] = relationship(back_populates="steps")


class RequirementTestCase(Base):
    """Coverage link. Stored by external IDs so links survive partial imports; FKs resolve when both exist."""

    __tablename__ = "requirement_test_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "requirement_external_id", "test_case_external_id", name="uq_req_tc"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_external_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    test_case_external_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class TestSet(SyncedMixin, Base):
    __tablename__ = "test_sets"
    __table_args__ = (UniqueConstraint("project_id", "external_id", name="uq_test_set_ext"),)
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    folder_external_id: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    status_name: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(200))
    release_external_id: Mapped[str | None] = mapped_column(String(64))
    release_version: Mapped[str | None] = mapped_column(String(100))
    planned_date: Mapped[datetime | None] = mapped_column(UTCDateTime())
    counts: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(1000))


class TestSetTestCase(Base):
    __tablename__ = "test_set_test_cases"
    __table_args__ = (UniqueConstraint("test_set_id", "external_id", name="uq_tstc_ext"),)
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    test_set_id: Mapped[int] = mapped_column(ForeignKey("test_sets.id", ondelete="CASCADE"), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)  # TestSetTestCaseId
    test_case_external_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    position: Mapped[int | None] = mapped_column(Integer)
    owner_external_id: Mapped[str | None] = mapped_column(String(64))


class Incident(SyncedMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (UniqueConstraint("project_id", "platform", "external_id", name="uq_incident_ext"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(20), default="spira", nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(1000), nullable=False)
    description_html: Mapped[str | None] = mapped_column(Text)
    description_text: Mapped[str | None] = mapped_column(Text)
    status_name: Mapped[str | None] = mapped_column(String(100), index=True)
    is_open: Mapped[bool | None] = mapped_column(Boolean)
    type_name: Mapped[str | None] = mapped_column(String(100))
    priority_name: Mapped[str | None] = mapped_column(String(100))
    severity_name: Mapped[str | None] = mapped_column(String(100))
    owner_name: Mapped[str | None] = mapped_column(String(200))
    opener_name: Mapped[str | None] = mapped_column(String(200))
    detected_release_external_id: Mapped[str | None] = mapped_column(String(64))
    detected_release_version: Mapped[str | None] = mapped_column(String(100))
    resolved_release_external_id: Mapped[str | None] = mapped_column(String(64))
    resolved_release_version: Mapped[str | None] = mapped_column(String(100))
    component_external_ids: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    tags: Mapped[str | None] = mapped_column(String(1000))
    url: Mapped[str | None] = mapped_column(String(1000))


class ExternalAttachment(Base):
    """Metadata of attachments that exist in the external system (content is not downloaded)."""

    __tablename__ = "external_attachments"
    __table_args__ = (
        UniqueConstraint("project_id", "artifact_type", "artifact_external_id", "external_id", name="uq_ext_attach"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    artifact_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(1000), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    author_name: Mapped[str | None] = mapped_column(String(200))
    uploaded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


Index("ix_requirements_project_name", Requirement.project_id, Requirement.name)
Index("ix_test_cases_project_name", TestCase.project_id, TestCase.name)
