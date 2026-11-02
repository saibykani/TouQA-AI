"""Stateful fake Spira v7.0 and Jira Cloud servers for tests (sanitised, synthetic data).

Response shapes follow the schemas in docs/spira-openapi-v7_0.json and Atlassian's v3 spec.
Failure injection lets tests exercise auth errors, rate limits, server errors and timeouts.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

import httpx

SPIRA = "https://spira.example.com"
API = "/services/v7_0/RestService.svc/"
JIRA = "https://example.atlassian.net"


class FakeSpira:
    def __init__(self, n_requirements: int = 5, n_test_cases: int = 4):
        self.username, self.api_key = "tester", "{11111111-2222-3333-4444-555555555555}"
        self.calls: list[tuple[str, str]] = []
        self.fail: dict[str, list] = defaultdict(list)  # path regex -> queue of status codes or "timeout"
        self.next_id = 1000
        self.project = {"ProjectId": 1, "ProjectTemplateId": 7, "Name": "Payments", "Description": "<p>Demo</p>", "Active": True}
        self.requirements = []
        for i in range(n_requirements):
            rid = 10 + i
            self.requirements.append({
                "RequirementId": rid, "Name": f"Requirement {rid}", "IndentLevel": "AAA" if i == 0 else f"AAA{chr(65 + i)}AA",
                "Summary": i == 0, "StatusName": "Accepted", "RequirementTypeName": "User Story", "ImportanceName": "2 - High",
                "Description": f"<p>The user must be able to do thing {rid}.</p><p>When input is invalid the system shall show an error.</p>",
                "CoverageCountTotal": 1 if rid == 11 else 0, "ReleaseId": 1, "ReleaseVersionNumber": "1.0",
                "LastUpdateDate": "2026-10-01T10:00:00.000", "CreationDate": "2026-09-01T10:00:00", "CustomProperties": [
                    {"PropertyNumber": 1, "StringValue": "<p>AC: The total must equal the sum of items.</p>"}],
            })
        self.folders = [{"TestCaseFolderId": 5, "Name": "Checkout", "ParentTestCaseFolderId": None, "IndentLevel": "AAA"},
                        {"TestCaseFolderId": 6, "Name": "Cards", "ParentTestCaseFolderId": 5, "IndentLevel": "AAAAAA"}]
        self.test_cases = [{"TestCaseId": 100 + i, "Name": f"Existing test {i}", "TestCaseFolderId": 5, "Description": "<p>d</p>",
                            "TestCaseStatusName": "Approved", "IsTestSteps": True, "LastUpdateDate": "2026-10-02T00:00:00"}
                           for i in range(n_test_cases)]
        self.steps = {100 + i: [{"TestStepId": 900 + 10 * i + j, "TestCaseId": 100 + i, "Position": j + 1,
                                 "Description": f"Do step {j + 1}", "ExpectedResult": f"Result {j + 1}"} for j in range(2)]
                      for i in range(n_test_cases)}
        self.coverage = {11: [100]}
        self.test_sets = [{"TestSetId": 300, "Name": "Regression", "TestSetStatusName": "Not Started", "TestSetFolderId": 40}]
        self.test_set_folders = [{"TestSetFolderId": 40, "Name": "Sets", "IndentLevel": "AAA"}]
        self.mappings = {300: [{"TestSetTestCaseId": 3001, "TestSetId": 300, "TestCaseId": 100, "Position": 1}]}
        self.incidents = [{"IncidentId": 500 + i, "Name": f"Bug {i}", "Description": "<p>Broken</p>", "IncidentStatusName": "New",
                           "IncidentStatusOpenStatus": True, "PriorityName": "2 - High", "IsAttachments": False} for i in range(3)]
        self.releases = [{"ReleaseId": 1, "Name": "R1", "VersionNumber": "1.0", "IndentLevel": "AAA", "ReleaseTypeName": "Major Release", "Active": True},
                         {"ReleaseId": 2, "Name": "Sprint 1", "VersionNumber": "1.0.1", "IndentLevel": "AAAAAA", "ReleaseTypeName": "Iteration", "Active": True}]
        self.documents: list[dict] = []
        self.workflow_required: list[str] = []

    # ------------------------------------------------------------- plumbing
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def inject(self, pattern: str, *outcomes):
        self.fail[pattern].extend(outcomes)

    def _id(self) -> int:
        self.next_id += 1
        return self.next_id

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlparse(str(request.url))
        path = url.path.split(API, 1)[-1]
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.calls.append((request.method, path))
        for pattern, queue in self.fail.items():
            if queue and re.fullmatch(pattern, f"{request.method} {path}"):
                outcome = queue.pop(0)
                if outcome == "timeout":
                    raise httpx.ReadTimeout("simulated timeout", request=request)
                if outcome == "timeout_after_apply":
                    self._route(request, path, q)  # the write lands, but the client never sees the response
                    raise httpx.ReadTimeout("simulated timeout after apply", request=request)
                return httpx.Response(outcome, json={"Message": f"injected {outcome}"},
                                      headers={"Retry-After": "0"} if outcome == 429 else {})
        if request.headers.get("username") != self.username or request.headers.get("api-key") != self.api_key:
            return httpx.Response(401, text="Unauthorized")
        return self._route(request, path, q)

    def _page(self, rows, q, start_key, size_key):
        start = int(q.get(start_key, 1))
        size = int(q.get(size_key, 1000))
        return httpx.Response(200, json=rows[start - 1:start - 1 + size])

    def _route(self, request, path, q) -> httpx.Response:
        m, body = request.method, (json.loads(request.content) if request.content else None)
        R = lambda data, status=200: httpx.Response(status, json=data)  # noqa: E731
        if m == "GET" and path == "users":
            return R({"UserId": 1, "UserName": "tester", "FullName": "Test User"})
        if m == "GET" and path == "system/product-version":
            return R("7.4.0.1")
        if m == "GET" and path == "projects":
            return R([self.project])
        if m == "GET" and path == "projects/1":
            return R(self.project)
        if m == "GET" and path == "projects/1/requirements":
            return self._page(self.requirements, q, "starting_row", "number_of_rows")
        if m == "GET" and path == "projects/1/requirements/count":
            return R(len(self.requirements))
        if mm := re.fullmatch(r"projects/1/requirements/(\d+)/test-cases", path):
            return R([{"RequirementId": int(mm[1]), "TestCaseId": t} for t in self.coverage.get(int(mm[1]), [])])
        if m == "POST" and path == "projects/1/requirements/test-cases":
            self.coverage.setdefault(body["RequirementId"], [])
            if body["TestCaseId"] not in self.coverage[body["RequirementId"]]:
                self.coverage[body["RequirementId"]].append(body["TestCaseId"])
            return R(None)
        if m == "GET" and path == "projects/1/test-cases":
            return self._page(self.test_cases, q, "starting_row", "number_of_rows")
        if m == "GET" and path == "projects/1/test-cases/count":
            return R(len(self.test_cases))
        if mm := re.fullmatch(r"projects/1/test-cases/(\d+)/test-steps", path):
            tid = int(mm[1])
            if m == "GET":
                return R(self.steps.get(tid, []))
            step = {**body, "TestStepId": self._id()}
            self.steps.setdefault(tid, []).append(step)
            return R(step)
        if m == "POST" and path == "projects/1/test-cases":
            assert body.get("TestCaseStatusId") and body.get("TestCaseTypeId"), "required by Spira"
            tc = {**body, "TestCaseId": self._id()}
            self.test_cases.append(tc)
            return R(tc)
        if m == "POST" and path == "projects/1/test-cases/search":
            name = next((f["StringValue"] for f in body if f["PropertyName"] == "Name"), "")
            return R([t for t in self.test_cases if name in t["Name"]])
        if path == "projects/1/test-folders":
            if m == "GET":
                return R(self.folders)
            f = {"TestCaseFolderId": self._id(), "Name": body["Name"], "ParentTestCaseFolderId": body.get("ParentTestCaseFolderId"), "IndentLevel": "ZZZ"}
            self.folders.append(f)
            return R(f)
        if m == "GET" and path == "projects/1/test-set-folders":
            return R(self.test_set_folders)
        if m == "GET" and path == "projects/1/test-sets":
            return self._page(self.test_sets, q, "starting_row", "number_of_rows")
        if mm := re.fullmatch(r"projects/1/test-sets/(\d+)/test-case-mapping", path):
            return R(self.mappings.get(int(mm[1]), []))
        if path == "projects/1/incidents/search":
            if m == "GET":
                return self._page(self.incidents, q, "start_row", "number_rows")
            name = next((f["StringValue"] for f in body if f["PropertyName"] == "Name"), "")
            return R([i for i in self.incidents if name in i["Name"]])
        if m == "GET" and path == "projects/1/incidents/count":
            return R(len(self.incidents))
        if m == "POST" and path == "projects/1/incidents":
            missing = [f for f in self.workflow_required if f not in body]
            if missing:
                return R({"Message": f"Required: {missing}"}, 400)
            inc = {**body, "IncidentId": self._id()}
            self.incidents.append(inc)
            return R(inc)
        if m == "POST" and path == "projects/1/releases/search":
            return self._page(self.releases, q, "start_row", "number_rows")
        if m == "GET" and path == "projects/1/users":
            return R([{"UserId": 1, "FullName": "Test User", "UserName": "tester", "Active": True}])
        if m == "GET" and path == "projects/1/components":
            return R([{"ComponentId": 1, "Name": "Checkout", "IsActive": True, "IsDeleted": False}])
        if m == "POST" and path == "projects/1/documents/file":
            assert isinstance(body["BinaryData"], str) and body["AttachedArtifacts"][0]["ArtifactTypeId"] == 3
            d = {"AttachmentId": self._id(), "FilenameOrUrl": body["FilenameOrUrl"]}
            self.documents.append(d)
            return R(d)
        if mm := re.fullmatch(r"project-templates/7/(incidents|test-cases|requirements)/(\w+)", path):
            art, kind = mm[1], mm[2]
            data = {
                ("incidents", "priorities"): [{"PriorityId": 1, "Name": "1 - Critical", "Active": True}, {"PriorityId": 2, "Name": "2 - High", "Active": True},
                                              {"PriorityId": 3, "Name": "3 - Medium", "Active": True}, {"PriorityId": 4, "Name": "4 - Low", "Active": True}],
                ("incidents", "severities"): [{"SeverityId": 1, "Name": "1 - Critical", "Active": True}, {"SeverityId": 2, "Name": "2 - High", "Active": True}],
                ("incidents", "types"): [{"IncidentTypeId": 1, "Name": "Bug", "Active": True}],
                ("incidents", "statuses"): [{"IncidentStatusId": 1, "Name": "New", "Active": True, "Open": True}],
                ("test-cases", "priorities"): [{"TestCasePriorityId": 1, "Name": "1 - Critical", "Active": True},
                                               {"TestCasePriorityId": 2, "Name": "2 - High", "Active": True},
                                               {"TestCasePriorityId": 3, "Name": "3 - Medium", "Active": True}],
                ("test-cases", "statuses"): [{"TestCaseStatusId": 1, "Name": "Draft", "Active": True}, {"TestCaseStatusId": 4, "Name": "Approved", "Active": True}],
                ("test-cases", "types"): [{"TestCaseTypeId": 3, "Name": "Functional", "Active": True}],
                ("requirements", "statuses"): [{"RequirementStatusId": 1, "Name": "Accepted", "Active": True}],
                ("requirements", "types"): [{"RequirementTypeId": 1, "Name": "User Story", "Active": True}],
                ("requirements", "importances"): [{"ImportanceId": 1, "Name": "2 - High", "Active": True}],
            }.get((art, kind))
            if data is not None:
                return R(data)
        if path == "project-templates/7/incidents/statuses/default":
            return R({"IncidentStatusId": 1, "Name": "New"})
        if path == "project-templates/7/incidents/types/default":
            return R({"IncidentTypeId": 1, "Name": "Bug"})
        if re.fullmatch(r"project-templates/7/incidents/types/\d+/workflow/fields", path):
            return R([{"FieldName": f, "FieldStateId": 2, "ArtifactStatusId": 1} for f in self.workflow_required])
        if mm := re.fullmatch(r"project-templates/7/custom-properties/(\w+)", path):
            if mm[1] == "Requirement":
                return R([{"CustomPropertyId": 1, "PropertyNumber": 1, "Name": "Acceptance Criteria", "CustomPropertyTypeName": "Text"}])
            return R([])
        return httpx.Response(404, json={"Message": f"no route {m} {path}"})


class FakeJira:
    def __init__(self):
        self.issues: list[dict] = []
        self.attachments: list[dict] = []
        self.fail: dict[str, list] = defaultdict(list)
        self.required_extra: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def inject(self, pattern: str, *outcomes):
        self.fail[pattern].extend(outcomes)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        for pattern, queue in self.fail.items():
            if queue and re.fullmatch(pattern, f"{request.method} {path}"):
                outcome = queue.pop(0)
                if outcome == "timeout":
                    raise httpx.ReadTimeout("timeout", request=request)
                return httpx.Response(outcome, json={"errorMessages": [f"injected {outcome}"]})
        if not request.headers.get("Authorization", "").startswith("Basic "):
            return httpx.Response(401)
        R = lambda d, s=200: httpx.Response(s, json=d)  # noqa: E731
        if path == "/rest/api/3/myself":
            return R({"accountId": "abc", "displayName": "Jira Tester"})
        if path == "/rest/api/3/serverInfo":
            return R({"deploymentType": "Cloud", "version": "1001.0.0"})
        if path == "/rest/api/3/project/QA":
            return R({"id": "10000", "key": "QA", "name": "QA Project"})
        if path == "/rest/api/3/issue/createmeta/QA/issuetypes":
            return R({"issueTypes": [{"id": "10001", "name": "Bug"}], "total": 1})
        if path == "/rest/api/3/issue/createmeta/QA/issuetypes/10001":
            fields = [{"fieldId": "summary", "name": "Summary", "required": True}, {"fieldId": "issuetype", "name": "Issue Type", "required": True},
                      {"fieldId": "project", "name": "Project", "required": True}, {"fieldId": "description", "name": "Description", "required": False},
                      {"fieldId": "priority", "name": "Priority", "required": False, "allowedValues": [{"id": "2", "name": "High"}]},
                      {"fieldId": "labels", "name": "Labels", "required": False}] + self.required_extra
            return R({"fields": fields, "total": len(fields)})
        if path == "/rest/api/3/issue" and request.method == "POST":
            body = json.loads(request.content)
            assert body["fields"]["description"]["type"] == "doc"
            key = f"QA-{len(self.issues) + 1}"
            self.issues.append({"key": key, "id": str(20000 + len(self.issues)), "fields": body["fields"]})
            return R({"id": self.issues[-1]["id"], "key": key, "self": f"{JIRA}/rest/api/3/issue/{key}"}, 201)
        if path == "/rest/api/3/search/jql":
            body = json.loads(request.content)
            m = re.search(r'summary ~ "\\"(.*)\\""', body["jql"])
            term = m[1] if m else ""
            hits = [{"key": i["key"], "id": i["id"], "fields": {"summary": i["fields"]["summary"]}} for i in self.issues if term in i["fields"]["summary"]]
            return R({"issues": hits, "isLast": True})
        if (mm := re.fullmatch(r"/rest/api/3/issue/([A-Z]+-\d+)/attachments", path)) and request.method == "POST":
            assert request.headers.get("X-Atlassian-Token") == "no-check"
            self.attachments.append({"issue": mm[1]})
            return R([{"id": str(len(self.attachments)), "filename": "x"}])
        return httpx.Response(404, json={"errorMessages": [f"no route {path}"]})
