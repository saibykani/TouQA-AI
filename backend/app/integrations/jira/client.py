"""Jira adapter.

Cloud (REST v3): Basic auth with account email + API token; descriptions in ADF.
Endpoints verified against Atlassian's published OpenAPI document (swagger-v3.v3.json):
  GET  /rest/api/3/myself, /rest/api/3/serverInfo, /rest/api/3/project/{key}
  POST /rest/api/3/search/jql             (enhanced search; /rest/api/3/search is deprecated)
  GET  /rest/api/3/issue/createmeta/{project}/issuetypes[/{issueTypeId}]
  POST /rest/api/3/issue                   -> {id, key, self}
  POST /rest/api/3/issue/{key}/attachments (multipart 'file', header X-Atlassian-Token: no-check)

Data Center (REST v2): Bearer personal access token; description is wiki-markup text.
Search uses /rest/api/2/search with startAt pagination.
"""
from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from app.integrations.http import ResilientClient


class JiraClient:
    def __init__(
        self,
        base_url: str,
        *,
        flavor: str = "cloud",
        email: str = "",
        api_token: str = "",
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.flavor = flavor
        self.api = "/rest/api/3" if flavor == "cloud" else "/rest/api/2"
        headers = {"Accept": "application/json"}
        if flavor == "cloud":
            token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        else:
            headers["Authorization"] = f"Bearer {api_token}"
        kwargs: dict[str, Any] = {}
        if sleep is not None:
            kwargs["sleep"] = sleep
        self.http = ResilientClient(self.base_url, headers=headers, platform="jira", transport=transport, **kwargs)

    def close(self) -> None:
        self.http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _get(self, path: str, params: dict | None = None) -> Any:
        return self.http.request("GET", f"{self.api}{path}", params=params).data

    # ----------------------------------------------------------------- reads
    def myself(self) -> dict:
        return self._get("/myself")

    def server_info(self) -> dict:
        return self._get("/serverInfo")

    def get_project(self, key: str) -> dict:
        return self._get(f"/project/{key}")

    def list_projects(self, max_results: int = 100) -> list[dict]:
        if self.flavor == "cloud":
            out, start = [], 0
            while True:
                page = self._get("/project/search", {"startAt": start, "maxResults": max_results}) or {}
                values = page.get("values", [])
                out.extend(values)
                if page.get("isLast", True) or not values:
                    return out
                start += len(values)
        return self._get("/project") or []

    def create_issue_types(self, project_key: str) -> list[dict]:
        out, start = [], 0
        while True:
            page = self._get(f"/issue/createmeta/{project_key}/issuetypes", {"startAt": start, "maxResults": 50}) or {}
            values = page.get("issueTypes") or page.get("values") or []
            out.extend(values)
            total = page.get("total")
            start += len(values)
            if not values or (total is not None and start >= total):
                return out

    def create_fields(self, project_key: str, issue_type_id: str) -> list[dict]:
        out, start = [], 0
        while True:
            page = self._get(f"/issue/createmeta/{project_key}/issuetypes/{issue_type_id}",
                             {"startAt": start, "maxResults": 100}) or {}
            values = page.get("fields") or page.get("results") or page.get("values") or []
            out.extend(values)
            total = page.get("total")
            start += len(values)
            if not values or (total is not None and start >= total):
                return out

    def iter_search(self, jql: str, fields: list[str], page_size: int = 100, cancel_check=None) -> Iterator[list[dict]]:
        if self.flavor == "cloud":
            token: str | None = None
            while True:
                body: dict[str, Any] = {"jql": jql, "maxResults": page_size, "fields": fields}
                if token:
                    body["nextPageToken"] = token
                data = self.http.request("POST", f"{self.api}/search/jql", json=body, safe_retry=True,
                                         cancel_check=cancel_check).data or {}
                issues = data.get("issues", [])
                if issues:
                    yield issues
                token = data.get("nextPageToken")
                if data.get("isLast", not token) or not token:
                    return
        else:
            start = 0
            while True:
                data = self.http.request("POST", f"{self.api}/search", safe_retry=True, cancel_check=cancel_check,
                                         json={"jql": jql, "startAt": start, "maxResults": page_size,
                                               "fields": fields}).data or {}
                issues = data.get("issues", [])
                if issues:
                    yield issues
                start += len(issues)
                if not issues or start >= int(data.get("total", 0)):
                    return

    def search_by_summary(self, project_key: str, summary: str) -> list[dict]:
        escaped = summary.replace("\\", "\\\\").replace('"', '\\"')
        jql = f'project = "{project_key}" AND summary ~ "\\"{escaped}\\"" ORDER BY created DESC'
        found: list[dict] = []
        for page in self.iter_search(jql, ["summary", "created"], page_size=20):
            found.extend(i for i in page if (i.get("fields", {}).get("summary") or "").strip() == summary.strip())
            break
        return found

    # ---------------------------------------------------------------- writes
    def create_issue(self, fields: dict) -> dict:
        return self.http.request("POST", f"{self.api}/issue", json={"fields": fields}).data

    def add_attachment(self, issue_key: str, filename: str, data: bytes, content_type: str) -> list[dict]:
        return self.http.request(
            "POST", f"{self.api}/issue/{issue_key}/attachments",
            files={"file": (filename, data, content_type)},
            headers={"X-Atlassian-Token": "no-check"},
        ).data or []

    def browse_url(self, key: str) -> str:
        return f"{self.base_url}/browse/{key}"
