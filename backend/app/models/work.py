"""Operational records: jobs, AI outputs, drafts, attachments, approvals, audit and API operations.

Drafts are deliberately separate from imported (authoritative) records.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JsonType, UTCDateTime, utcnow

JOB_STATUSES = (
    "QUEUED", "RUNNING", "NEEDS_REVIEW", "APPROVED", "COMPLETED",
    "PARTIALLY_COMPLETED", "FAILED", "CANCELLED",
)
TERMINAL_JOB_STATUSES = {"COMPLETED", "PARTIALLY_COMPLETED", "FAILED", "CANCELLED", "NEEDS_REVIEW"}


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    result: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class SyncEntityResult(Base):
    __tablename__ = "sync_entity_results"
    __table_args__ = (UniqueConstraint("job_id", "entity_type", name="uq_sync_entity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", nullable=False)
    discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    notes: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RequirementAnalysis(Base):
    __tablename__ = "requirement_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | approved | superseded
    content: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class GenerationBatch(Base):
    __tablename__ = "generation_batches"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    requirement_ids: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    analysis_ids: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    drafts: Mapped[list["TestCaseDraft"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="TestCaseDraft.position"
    )


class TestCaseDraft(Base):
    __tablename__ = "test_case_drafts"
    __test__ = False
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("generation_batches.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id", ondelete="SET NULL"))
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # draft | approved | rejected | submitting | submitted | failed
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False, index=True)
    content: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duplicate_info: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    duplicate_decision: Mapped[str | None] = mapped_column(String(20))  # keep | merge | remove
    validation_errors: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    external_test_case_id: Mapped[str | None] = mapped_column(String(64))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)
    batch: Mapped[GenerationBatch] = relationship(back_populates="drafts")


class IncidentDraft(Base):
    __tablename__ = "incident_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # draft | analyzed | approved | submitting | submitted | partially_submitted | failed
    status: Mapped[str] = mapped_column(String(30), default="draft", nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    raw_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    content: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    classification: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    destinations: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    ai_provider: Mapped[str | None] = mapped_column(String(40))
    ai_model: Mapped[str | None] = mapped_column(String(100))
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    results: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="incident_draft", cascade="all, delete-orphan")


class Attachment(Base):
    """User-uploaded evidence stored locally. Never sent externally before approval."""

    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_draft_id: Mapped[int | None] = mapped_column(ForeignKey("incident_drafts.id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    include_in_submission: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    analysis: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    upload_results: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    incident_draft: Mapped[IncidentDraft | None] = relationship(back_populates="attachments")


class ApprovalEvent(Base):
    __tablename__ = "approval_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # import|ai|external_write|config|auth|draft
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    platform: Mapped[str | None] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failure | partial | info
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ApiOperation(Base):
    """One external write. The unique idempotency key prevents duplicate creation on retry."""

    __tablename__ = "api_operations"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    local_entity_type: Mapped[str | None] = mapped_column(String(40))
    local_entity_id: Mapped[int | None] = mapped_column(Integer)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    # pending | in_flight | succeeded | failed | unknown
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_summary: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    external_id: Mapped[str | None] = mapped_column(String(64))
    external_key: Mapped[str | None] = mapped_column(String(64))
    external_url: Mapped[str | None] = mapped_column(String(1000))
    error: Mapped[str | None] = mapped_column(Text)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class ExternalRecordRef(Base):
    """Links a local entity (draft) to the record it produced in an external system."""

    __tablename__ = "external_record_refs"
    __table_args__ = (UniqueConstraint("platform", "record_type", "external_id", "project_id", name="uq_ext_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    record_type: Mapped[str] = mapped_column(String(40), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(64))
    url: Mapped[str | None] = mapped_column(String(1000))
    local_entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    local_entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


Index("ix_api_operations_entity", ApiOperation.local_entity_type, ApiOperation.local_entity_id)
