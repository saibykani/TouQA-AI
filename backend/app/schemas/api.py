"""Pydantic request and response models for the v1 API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Ok(BaseModel):
    ok: bool = True


# ------------------------------------------------------------------- auth
class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=500)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str
    role: str


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str | None = None
    auth_enabled: bool


# ---------------------------------------------------------- integrations
class SpiraConfigIn(BaseModel):
    base_url: str = Field(min_length=4, max_length=500)
    username: str = Field(min_length=1, max_length=320)
    api_key: str | None = Field(default=None, max_length=500, description="RSS token / API key; omit to keep the stored one")


class JiraConfigIn(BaseModel):
    base_url: str = Field(min_length=4, max_length=500)
    flavor: Literal["cloud", "datacenter"] = "cloud"
    email: str = Field(default="", max_length=320)
    api_token: str | None = Field(default=None, max_length=1000)
    project_key: str | None = Field(default=None, max_length=50)
    issue_type_id: str | None = Field(default=None, max_length=50)


class AISettingsIn(BaseModel):
    provider: Literal["anthropic", "openai_compatible", "local", "simulated"] | None = None
    model: str | None = Field(default=None, max_length=200)
    vision_model: str | None = Field(default=None, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    vision_enabled: bool | None = None


# --------------------------------------------------------------- projects
class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: str
    external_id: str
    name: str
    description: str | None
    template_id: str | None
    is_demo: bool
    last_synced_at: datetime | None
    settings: dict


class ProjectImportIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=64)


class ProjectSettingsIn(BaseModel):
    acceptance_criteria_field: str | None = Field(default=None, max_length=200)
    default_test_case_status_id: str | None = None
    default_test_case_type_id: str | None = None


class MappingIn(BaseModel):
    platform: Literal["spira", "jira"]
    field: str = Field(max_length=60)
    canonical_value: str = Field(max_length=200)
    external_value_id: str | None = Field(default=None, max_length=200)
    external_value_name: str | None = Field(default=None, max_length=500)


# ------------------------------------------------------------------- sync
SyncEntity = Literal["metadata", "releases", "folders", "requirements", "test_cases", "test_sets", "incidents"]


class SyncOptions(BaseModel):
    include_test_steps: bool = True
    include_requirement_coverage: bool = True
    include_requirement_steps: bool = False
    include_test_set_membership: bool = True
    include_incident_attachments: bool = False


class SyncStartIn(BaseModel):
    project_id: int
    entities: list[SyncEntity] | None = None
    options: SyncOptions = SyncOptions()


class JobOut(BaseModel):
    id: int
    kind: str
    status: str
    project_id: int | None
    progress: int
    message: str | None
    params: dict
    result: dict
    error: str | None
    cancel_requested: bool
    is_demo: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ---------------------------------------------------------------- AI work
class AnalysisUpdateIn(BaseModel):
    content: dict[str, Any]


class GenerationConfig(BaseModel):
    counts: dict[str, int] = Field(description="category -> number of test cases")
    max_steps: int | None = Field(default=None, ge=1, le=50)
    avoid_existing_duplicates: bool = True


class GenerationStartIn(BaseModel):
    project_id: int
    requirement_ids: list[int] = Field(min_length=1, max_length=10)
    config: GenerationConfig
    instructions: str | None = Field(default=None, max_length=20000)
    require_approved_analysis: bool = False


class DraftUpdateIn(BaseModel):
    content: dict[str, Any] | None = None
    status: Literal["draft", "approved", "rejected"] | None = None
    duplicate_decision: Literal["keep", "merge", "remove"] | None = None


class FolderPreviewIn(BaseModel):
    project_id: int
    name: str = Field(max_length=300)
    parent_external_id: str | None = None


class FolderCreateIn(FolderPreviewIn):
    confirm: bool = False
    description: str | None = Field(default=None, max_length=2000)


class SubmissionOptions(BaseModel):
    status_id: str | None = None
    type_id: str | None = None
    include_tags: bool = True


class SubmissionPreviewIn(BaseModel):
    project_id: int
    draft_ids: list[int] = Field(min_length=1, max_length=100)
    folder_external_id: str | None = None
    options: SubmissionOptions = SubmissionOptions()


class SubmissionIn(SubmissionPreviewIn):
    confirm: bool
    payload_hash: str = Field(min_length=64, max_length=64)


# --------------------------------------------------------------- incidents
class EnvironmentIn(BaseModel):
    environment: str | None = None
    browser: str | None = None
    operating_system: str | None = None
    device: str | None = None
    application_version: str | None = None
    release: str | None = None


class EvidenceIn(BaseModel):
    environment: EnvironmentIn = EnvironmentIn()
    expected_behavior: str | None = Field(default=None, max_length=10000)
    actual_behavior: str | None = Field(default=None, max_length=10000)
    reproduction_notes: str | None = Field(default=None, max_length=20000)
    logs: str | None = Field(default=None, max_length=100000)
    api_details: str | None = Field(default=None, max_length=100000)
    related_requirement_ids: list[str] = []
    related_test_case_ids: list[str] = []
    related_test_set_ids: list[str] = []


class IncidentDraftCreateIn(BaseModel):
    project_id: int
    raw_notes: str = Field(default="", max_length=50000)
    evidence: EvidenceIn = EvidenceIn()
    destinations: list[Literal["spira", "jira"]] = ["spira"]


class IncidentDraftUpdateIn(BaseModel):
    raw_notes: str | None = Field(default=None, max_length=50000)
    evidence: EvidenceIn | None = None
    content: dict[str, Any] | None = None
    classification: dict[str, Any] | None = None
    destinations: list[Literal["spira", "jira"]] | None = None
    title: str | None = Field(default=None, max_length=500)


class AttachmentUpdateIn(BaseModel):
    include_in_submission: bool


class IncidentSubmitIn(BaseModel):
    confirm: bool
    payload_hash: str = Field(min_length=64, max_length=64)
    destinations: list[Literal["spira", "jira"]] | None = None
