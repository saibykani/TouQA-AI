"""Users, sessions, integrations, credentials, projects, metadata and field mappings."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JsonType, UTCDateTime, utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="admin", nullable=False)  # admin | member | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AppSession(Base):
    __tablename__ = "app_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    user: Mapped[User] = relationship()


class CredentialSecret(Base):
    """Encrypted secret material. Integrations reference this row; plaintext never leaves the server."""

    __tablename__ = "credential_secrets"
    id: Mapped[int] = mapped_column(primary_key=True)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class IntegrationConfig(TimestampMixin, Base):
    __tablename__ = "integration_configs"
    __table_args__ = (UniqueConstraint("platform", name="uq_integration_platform"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # spira | jira | ai
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    auth_type: Mapped[str] = mapped_column(String(30), nullable=False, default="api_key")
    flavor: Mapped[str] = mapped_column(String(20), nullable=False, default="cloud")  # jira: cloud | datacenter
    secret_id: Mapped[int | None] = mapped_column(ForeignKey("credential_secrets.id", ondelete="SET NULL"))
    settings: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="unconfigured", nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)
    api_version: Mapped[str | None] = mapped_column(String(50))
    capabilities: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    secret: Mapped[CredentialSecret | None] = relationship()


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("platform", "external_id", "is_demo", name="uq_project_platform_ext"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[str | None] = mapped_column(String(64))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    settings: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    raw: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)


class ProjectMetadata(Base):
    """Allowed values discovered from the external project (priorities, users, statuses...)."""

    __tablename__ = "project_metadata"
    __table_args__ = (UniqueConstraint("project_id", "kind", "external_id", name="uq_project_meta"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)


class FieldMapping(TimestampMixin, Base):
    """Maps a canonical TouQA value (e.g. priority 'high') to an external allowed value."""

    __tablename__ = "field_mappings"
    __table_args__ = (
        UniqueConstraint("platform", "project_id", "field", "canonical_value", name="uq_field_mapping"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    field: Mapped[str] = mapped_column(String(60), nullable=False)
    canonical_value: Mapped[str] = mapped_column(String(200), nullable=False)
    external_value_id: Mapped[str | None] = mapped_column(String(200))
    external_value_name: Mapped[str | None] = mapped_column(String(500))
    extra: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)


Index("ix_project_metadata_kind", ProjectMetadata.project_id, ProjectMetadata.kind)
