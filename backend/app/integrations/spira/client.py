"""Spira REST API v7.0 adapter.

Every endpoint used here was verified against the OpenAPI document published by the
instance itself (``/services/v7_0/RestServiceOpenApi.ashx``; a copy lives in
``docs/spira-openapi-v7_0.json``). Authentication uses the documented ``username`` and
``api-key`` headers (the api-key is the user's RSS token, including braces).

Pagination: list endpoints take a 1-based ``starting_row`` / ``start_row`` and a page size.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from app.integrations.http import (
    IntegrationValidationError,
    ResilientClient,
)

log = logging.getLogger("touqa.spira")

API_VERSION = "v7_0"
PAGE_SIZE = 250

# Artifact type IDs documented on the instance's REST help page.
ARTIFACT_TYPE_IDS = {
    "requirement": 1, "test_case": 2, "incident": 3, "release": 4, "test_run": 5,
    "task": 6, "test_step": 7, "test_set": 8,
}

# Spira workflow field states (RemoteWorkflowField.FieldStateId)
WORKFLOW_FIELD_STATES = {1: "inactive", 2: "required", 3: "hidden"}


def spira_api_base(instance_url: str) -> str:
    return f"{instance_url.rstrip('/')}/services/{API_VERSION}/RestService.svc"


def spira_artifact_url(instance_url: str, project_id: int | str, artifact: str, artifact_id: int | str) -> str:
    """Browser URL for an artifact (Spira's standard ``/{project}/{Artifact}/{id}.aspx`` route)."""
    segment = {"requirement": "Requirement", "test_case": "TestCase", "incident": "Incident",
               "test_set": "TestSet", "release": "Release"}[artifact]
    return f"{instance_url.rstrip('/')}/{project_id}/{segment}/{artifact_id}.aspx"


class SpiraClient:
    def __init__(
        self,
        instance_url: str,
        username: str,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        page_size: int = PAGE_SIZE,
    ):
        self.instance_url = instance_url.rstrip("/")
        self.page_size = page_size
        kwargs: dict[str, Any] = {}
        if sleep is not None:
            kwargs["sleep"] = sleep
        self.http = ResilientClient(
            spira_api_base(self.instance_url),
            headers={
                "username": username,
                "api-key": api_key,
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            platform="spira",
            transport=transport,
            **kwargs,
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ----------------------------------------------------------------- basics
    def get(self, path: str, params: dict | None = None, cancel_check=None) -> Any:
        return self.http.request("GET", path, params=params, cancel_check=cancel_check).data

    def current_user(self) -> dict:
        return self.get("users")

    def product_version(self) -> Any:
        return self.get("system/product-version")

    def list_projects(self) -> list[dict]:
        return self.get("projects") or []

    def get_project(self, project_id: int) -> dict:
        return self.get(f"projects/{project_id}")

    # ------------------------------------------------------------- pagination
    def _paged(
        self,
        path: str,
        *,
        start_param: str,
        size_param: str,
        extra: dict | None = None,
        method: str = "GET",
        body: Any = None,
        cancel_check=None,
        max_pages: int = 10_000,
    ) -> Iterator[list[dict]]:
        start = 1
        for _ in range(max_pages):
            params = {start_param: start, size_param: self.page_size, **(extra or {})}
            resp = self.http.request(method, path, params=params, json=body, safe_retry=True, cancel_check=cancel_check)
            page = resp.data or []
            if not isinstance(page, list):
                raise IntegrationValidationError(f"Unexpected response shape from Spira for {path}")
            if page:
                yield page
            if len(page) < self.page_size:
                return
            start += self.page_size

    def iter_requirements(self, project_id: int, cancel_check=None) -> Iterator[list[dict]]:
        return self._paged(f"projects/{project_id}/requirements", start_param="starting_row",
                           size_param="number_of_rows", cancel_check=cancel_check)

    def count_requirements(self, project_id: int) -> int | None:
        return _as_int(self.get(f"projects/{project_id}/requirements/count"))

    def requirement_coverage(self, project_id: int, requirement_id: int, cancel_check=None) -> list[dict]:
        return self.get(f"projects/{project_id}/requirements/{requirement_id}/test-cases", cancel_check=cancel_check) or []

    def requirement_steps(self, project_id: int, requirement_id: int, cancel_check=None) -> list[dict]:
        return self.get(f"projects/{project_id}/requirements/{requirement_id}/steps", cancel_check=cancel_check) or []

    def iter_test_cases(self, project_id: int, cancel_check=None) -> Iterator[list[dict]]:
        return self._paged(
            f"projects/{project_id}/test-cases", start_param="starting_row", size_param="number_of_rows",
            extra={"sort_field": "TestCaseId", "sort_direction": "ASC"}, cancel_check=cancel_check,
        )

    def iter_test_cases_in_folder(self, project_id: int, folder_id: int, cancel_check=None) -> Iterator[list[dict]]:
        return self._paged(
            f"projects/{project_id}/test-folders/{folder_id}/test-cases", start_param="starting_row",
            size_param="number_of_rows", extra={"sort_field": "TestCaseId", "sort_direction": "ASC"},
            cancel_check=cancel_check,
        )

    def count_test_cases(self, project_id: int) -> int | None:
        return _as_int(self.get(f"projects/{project_id}/test-cases/count"))

    def test_steps(self, project_id: int, test_case_id: int, cancel_check=None) -> list[dict]:
        return self.get(f"projects/{project_id}/test-cases/{test_case_id}/test-steps", cancel_check=cancel_check) or []

    def test_case_folders(self, project_id: int) -> list[dict]:
        return self.get(f"projects/{project_id}/test-folders") or []

    def test_set_folders(self, project_id: int) -> list[dict]:
        return self.get(f"projects/{project_id}/test-set-folders") or []

    def iter_test_sets(self, project_id: int, cancel_check=None) -> Iterator[list[dict]]:
        return self._paged(
            f"projects/{project_id}/test-sets", start_param="starting_row", size_param="number_of_rows",
            extra={"sort_field": "TestSetId", "sort_direction": "ASC"}, cancel_check=cancel_check,
        )

    def test_set_mappings(self, project_id: int, test_set_id: int, cancel_check=None) -> list[dict]:
        return self.get(f"projects/{project_id}/test-sets/{test_set_id}/test-case-mapping", cancel_check=cancel_check) or []

    def iter_incidents(self, project_id: int, cancel_check=None) -> Iterator[list[dict]]:
        """Paged incidents. The documented ``sort_by`` takes a column name; fall back if rejected."""
        try:
            first = True
            for page in self._paged(f"projects/{project_id}/incidents/search", start_param="start_row",
                                    size_param="number_rows", extra={"sort_by": "IncidentId"},
                                    cancel_check=cancel_check):
                first = False
                yield page
        except IntegrationValidationError:
            if not first:
                raise
            log.info("Spira rejected sort_by=IncidentId; retrying incident search with 'IncidentId ASC'")
            yield from self._paged(f"projects/{project_id}/incidents/search", start_param="start_row",
                                   size_param="number_rows", extra={"sort_by": "IncidentId ASC"},
                                   cancel_check=cancel_check)

    def count_incidents(self, project_id: int) -> int | None:
        return _as_int(self.get(f"projects/{project_id}/incidents/count"))

    def releases(self, project_id: int, cancel_check=None) -> list[dict]:
        """Releases and iterations via the filterable search (GET /releases excludes iterations)."""
        out: list[dict] = []
        try:
            for page in self._paged(f"projects/{project_id}/releases/search", start_param="start_row",
                                    size_param="number_rows", method="POST", body=[], cancel_check=cancel_check):
                out.extend(page)
            return out
        except IntegrationValidationError:
            log.info("Release search unavailable; falling back to GET /releases (iterations excluded)")
            return self.get(f"projects/{project_id}/releases", params={"active_only": "false"}) or []

    def artifact_documents(self, project_id: int, artifact: str, artifact_id: int, cancel_check=None) -> list[dict]:
        type_id = ARTIFACT_TYPE_IDS[artifact]
        return self.get(f"projects/{project_id}/artifact-types/{type_id}/artifacts/{artifact_id}/documents",
                        cancel_check=cancel_check) or []

    # --------------------------------------------------------------- metadata
    def project_users(self, project_id: int) -> list[dict]:
        return self.get(f"projects/{project_id}/users") or []

    def components(self, project_id: int) -> list[dict]:
        return self.get(f"projects/{project_id}/components") or []

    def template_list(self, template_id: int, artifact: str, kind: str) -> list[dict]:
        """e.g. artifact='incidents', kind='priorities' -> /project-templates/{id}/incidents/priorities"""
        return self.get(f"project-templates/{template_id}/{artifact}/{kind}") or []

    def default_incident_status(self, template_id: int) -> dict | None:
        return self.get(f"project-templates/{template_id}/incidents/statuses/default")

    def default_incident_type(self, template_id: int) -> dict | None:
        return self.get(f"project-templates/{template_id}/incidents/types/default")

    def incident_type_workflow_fields(self, template_id: int, incident_type_id: int) -> list[dict]:
        return self.get(f"project-templates/{template_id}/incidents/types/{incident_type_id}/workflow/fields") or []

    def test_case_type_workflow_fields(self, template_id: int, test_case_type_id: int) -> list[dict]:
        return self.get(f"project-templates/{template_id}/test-cases/types/{test_case_type_id}/workflow/fields") or []

    def custom_property_definitions(self, template_id: int, artifact_type_name: str) -> list[dict]:
        return self.get(f"project-templates/{template_id}/custom-properties/{artifact_type_name}") or []

    # ------------------------------------------------------------------ writes
    # Writes are not retried automatically; see ResilientClient for OutcomeUnknownError semantics.
    def create_test_case_folder(self, project_id: int, name: str, parent_folder_id: int | None,
                                description: str | None = None) -> dict:
        body: dict[str, Any] = {"Name": name, "ProjectId": project_id}
        if parent_folder_id:
            body["ParentTestCaseFolderId"] = parent_folder_id
        if description:
            body["Description"] = description
        return self.http.request("POST", f"projects/{project_id}/test-folders", json=body).data

    def create_test_case(self, project_id: int, body: dict) -> dict:
        return self.http.request("POST", f"projects/{project_id}/test-cases", json=body).data

    def add_test_step(self, project_id: int, test_case_id: int, body: dict) -> dict:
        return self.http.request("POST", f"projects/{project_id}/test-cases/{test_case_id}/test-steps", json=body).data

    def link_requirement_test_case(self, project_id: int, requirement_id: int, test_case_id: int) -> None:
        # Documented as idempotent: "If the coverage record already exists no error is raised".
        self.http.request("POST", f"projects/{project_id}/requirements/test-cases",
                          json={"RequirementId": requirement_id, "TestCaseId": test_case_id}, safe_retry=True)

    def create_incident(self, project_id: int, body: dict) -> dict:
        return self.http.request("POST", f"projects/{project_id}/incidents", json=body).data

    def upload_document(self, project_id: int, filename: str, data: bytes, *, description: str | None,
                        artifact: str, artifact_id: int) -> dict:
        body = {
            "FilenameOrUrl": filename,
            "AttachmentTypeId": 1,  # File
            "BinaryData": base64.b64encode(data).decode("ascii"),
            "AttachedArtifacts": [{"ArtifactId": artifact_id, "ArtifactTypeId": ARTIFACT_TYPE_IDS[artifact]}],
        }
        if description:
            body["Description"] = description
        return self.http.request("POST", f"projects/{project_id}/documents/file", json=body).data

    # -------------------------------------------------------- reconciliation
    def search_test_cases_by_name(self, project_id: int, name: str) -> list[dict]:
        resp = self.http.request(
            "POST", f"projects/{project_id}/test-cases/search",
            params={"starting_row": 1, "number_of_rows": 50, "sort_field": "TestCaseId", "sort_direction": "DESC"},
            json=[{"PropertyName": "Name", "StringValue": name}], safe_retry=True,
        )
        return [tc for tc in (resp.data or []) if (tc.get("Name") or "").strip() == name.strip()]

    def search_incidents_by_name(self, project_id: int, name: str) -> list[dict]:
        resp = self.http.request(
            "POST", f"projects/{project_id}/incidents/search",
            params={"start_row": 1, "number_rows": 50, "sort_by": "IncidentId"},
            json=[{"PropertyName": "Name", "StringValue": name}], safe_retry=True,
        )
        return [i for i in (resp.data or []) if (i.get("Name") or "").strip() == name.strip()]


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
