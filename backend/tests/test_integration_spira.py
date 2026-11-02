"""Spira connection, import/sync, folders and approved test case creation (mocked Spira)."""
from app.models import ApiOperation, AuditLog, IntegrationConfig, Requirement, RequirementTestCase, TestCase, TestStep
from tests.fakes import SPIRA


def test_connection_success_and_secret_never_returned(client, connected):
    r = client.post("/api/v1/integrations/spira/test")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["project_count"] == 1
    view = client.get("/api/v1/integrations").json()["spira"]
    assert view["status"] == "connected" and view["has_secret"]
    assert connected.api_key not in str(view) and "api_key" not in view
    assert "REST v7_0" in view["api_version"]


def test_connection_failed_auth(client, spira, db):
    client.put("/api/v1/integrations/spira", json={"base_url": SPIRA, "username": spira.username, "api_key": "{wrong}"})
    r = client.post("/api/v1/integrations/spira/test")
    assert r.status_code == 502 and r.json()["error"]["code"] == "integration_auth_failed"
    assert "{wrong}" not in r.text
    cfg = db.query(IntegrationConfig).filter_by(platform="spira").one()
    assert cfg.status == "error"
    assert db.query(AuditLog).filter_by(action="spira.connection_test", outcome="failure").count() == 1


def test_credentials_stored_encrypted(client, connected, db):
    cfg = db.query(IntegrationConfig).filter_by(platform="spira").one()
    assert connected.api_key not in cfg.secret.ciphertext


def test_full_import_with_pagination(client, connected, db, monkeypatch):
    from app.integrations.spira import client as sc
    monkeypatch.setattr(sc, "PAGE_SIZE", 2)  # force several pages
    p = client.post("/api/v1/projects/import", json={"external_id": "1"}).json()
    job = client.post("/api/v1/sync/jobs", json={"project_id": p["id"]}).json()
    detail = client.get(f"/api/v1/sync/jobs/{job['id']}").json()
    assert detail["status"] == "COMPLETED", detail
    ents = {e["entity_type"]: e for e in detail["entities"]}
    assert ents["requirements"]["imported"] == 5 and ents["requirements"]["created"] == 5
    assert ents["test_cases"]["imported"] == 4 and ents["test_sets"]["imported"] == 1
    assert ents["incidents"]["imported"] == 3 and ents["releases"]["imported"] == 2
    assert ents["folders"]["imported"] == 3
    # hierarchy resolved from IndentLevel, coverage and steps imported
    child = db.query(Requirement).filter_by(external_id="11").one()
    assert child.parent_id == db.query(Requirement).filter_by(external_id="10").one().id
    assert db.query(RequirementTestCase).filter_by(requirement_external_id="11", test_case_external_id="100").count() == 1
    assert db.query(TestStep).count() == 8
    # list API with search/filter/pagination
    r = client.get("/api/v1/requirements", params={"project_id": p["id"], "q": "RQ:12"}).json()
    assert r["total"] == 1 and r["items"][0]["external_id"] == "12"
    d = client.get(f"/api/v1/requirements/{child.id}").json()
    assert d["linked_test_cases"][0]["external_id"] == "100"
    assert any(cp["name"] == "Acceptance Criteria" for cp in d["custom_properties"])


def test_resync_is_idempotent_and_incremental(client, synced, connected, db):
    calls_before = len(connected.calls)
    job = client.post("/api/v1/sync/jobs", json={"project_id": synced["id"]}).json()
    ents = {e["entity_type"]: e for e in client.get(f"/api/v1/sync/jobs/{job['id']}").json()["entities"]}
    assert ents["requirements"]["created"] == 0 and ents["requirements"]["skipped"] == 5
    assert db.query(TestCase).count() == 4  # no duplicates
    step_calls = [c for c in connected.calls[calls_before:] if c[1].endswith("/test-steps")]
    assert step_calls == []  # unchanged test cases -> steps not re-fetched


def test_partial_failure_and_retry(client, connected, db):
    connected.inject(r"GET projects/1/test-cases/101/test-steps", 500, 500, 500, 500, 500)
    connected.inject(r"GET projects/1/incidents/search", 403)
    p = client.post("/api/v1/projects/import", json={"external_id": "1"}).json()
    job = client.post("/api/v1/sync/jobs", json={"project_id": p["id"]}).json()
    detail = client.get(f"/api/v1/sync/jobs/{job['id']}").json()
    assert detail["status"] == "PARTIALLY_COMPLETED"
    ents = {e["entity_type"]: e for e in detail["entities"]}
    assert ents["test_cases"]["status"] == "PARTIALLY_COMPLETED" and ents["test_cases"]["failed"] == 1
    assert ents["test_cases"]["errors"][0]["external_id"] == "101"
    assert ents["incidents"]["status"] == "FAILED" and ents["requirements"]["status"] == "COMPLETED"
    retry = client.post(f"/api/v1/sync/jobs/{job['id']}/retry").json()
    assert set(retry["params"]["entities"]) == {"test_cases", "incidents"}
    assert client.get(f"/api/v1/sync/jobs/{retry['id']}").json()["status"] == "COMPLETED"


def test_rate_limited_sync_recovers(client, connected):
    connected.inject(r"GET projects/1/requirements", 429, 429)
    p = client.post("/api/v1/projects/import", json={"external_id": "1"}).json()
    job = client.post("/api/v1/sync/jobs", json={"project_id": p["id"], "entities": ["requirements"]}).json()
    assert client.get(f"/api/v1/sync/jobs/{job['id']}").json()["status"] == "COMPLETED"


def test_deleted_records_are_flagged(client, synced, connected, db):
    connected.incidents.pop()
    client.post("/api/v1/sync/jobs", json={"project_id": synced["id"], "entities": ["incidents"]})
    from app.models import Incident
    assert db.query(Incident).filter_by(is_deleted_externally=True).count() == 1


# ---------------------------------------------------------------- folders
def test_folder_preview_duplicate_and_create(client, synced, connected):
    pid = synced["id"]
    pre = client.post("/api/v1/folders/preview", json={"project_id": pid, "name": "cards", "parent_external_id": "5"}).json()
    assert pre["duplicate"]["external_id"] == "6" and pre["path"] == ["Checkout", "cards"]
    r = client.post("/api/v1/folders", json={"project_id": pid, "name": "Cards", "parent_external_id": "5", "confirm": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "folder_duplicate"
    r = client.post("/api/v1/folders", json={"project_id": pid, "name": "Wallets", "parent_external_id": "5"})
    assert r.status_code == 400  # confirmation required
    r = client.post("/api/v1/folders", json={"project_id": pid, "name": "Wallets", "parent_external_id": "5", "confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["folder"]["name"] == "Wallets" and r.json()["folder"]["parent_external_id"] == "5"
    assert len([f for f in connected.folders if f["Name"] == "Wallets"]) == 1
    r = client.post("/api/v1/folders/preview", json={"project_id": pid, "name": "   "})
    assert r.status_code == 422


# ----------------------------------------------------- generation & submission
def _generate(client, project_id, db):
    req = db.query(Requirement).filter_by(external_id="11").one()
    job = client.post(f"/api/v1/requirements/{req.id}/analyses").json()
    assert job["status"] == "NEEDS_REVIEW", job
    analysis_id = job["result"]["analysis_id"]
    assert client.post(f"/api/v1/analyses/{analysis_id}/approve").json()["status"] == "approved"
    job = client.post("/api/v1/generation", json={"project_id": project_id, "requirement_ids": [req.id],
                                                  "config": {"counts": {"positive": 2, "negative": 1}}}).json()
    assert job["status"] == "NEEDS_REVIEW", job
    batch = client.get(f"/api/v1/generation/batches/{job['result']['batch_id']}").json()
    return req, batch


def test_generate_preview_and_create(client, synced, connected, db):
    req, batch = _generate(client, synced["id"], db)
    assert len(batch["drafts"]) == 3 and batch["is_simulated"]
    assert all(d["duplicate_info"].get("checked") for d in batch["drafts"])
    writes_before = [c for c in connected.calls if c[0] == "POST" and "test-cases" in c[1]]
    assert writes_before == []  # generation never writes to Spira
    ids = [d["id"] for d in batch["drafts"][:2]]
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": ids, "folder_external_id": "6"}).json()
    assert not pre["blocking"] and pre["folder_path"] == ["Checkout", "Cards"]
    body = pre["payloads"][0]["test_case"]
    assert body["TestCaseStatusId"] == 1 and body["TestCaseTypeId"] == 3 and body["TestCaseFolderId"] == 6
    assert pre["payloads"][0]["coverage_link"] == {"RequirementId": 11}
    r = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "folder_external_id": "6",
                                                            "confirm": True, "payload_hash": "0" * 64})
    assert r.status_code == 409  # hash mismatch => user must review the current payload
    job = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "folder_external_id": "6",
                                                              "confirm": True, "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "COMPLETED", job
    created = [r["external_id"] for r in job["result"]["results"]]
    assert len(created) == 2 and all(created)
    assert all(int(c) in connected.steps and len(connected.steps[int(c)]) == 3 for c in created)
    assert all(int(c) in connected.coverage[11] for c in created)
    assert db.query(TestCase).filter_by(origin="touqa").count() == 2
    assert db.query(AuditLog).filter_by(action="spira.test_case.create", outcome="success").count() == 2
    # re-submitting the same drafts never creates duplicates
    pre2 = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": ids, "folder_external_id": "6"}).json()
    assert len(pre2["already_created"]) == 2
    n = len(connected.test_cases)
    job2 = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "folder_external_id": "6",
                                                               "confirm": True, "payload_hash": pre2["payload_hash"]})
    assert job2.status_code in (200, 409)
    assert len(connected.test_cases) == n


def test_partial_failure_resumes_without_duplicate(client, synced, connected, db):
    _, batch = _generate(client, synced["id"], db)
    ids = [batch["drafts"][0]["id"]]
    # Let step 2 fail with a server error
    original = connected._route
    count = {"n": 0}
    def flaky(request, path, q):
        if request.method == "POST" and path.endswith("/test-steps"):
            count["n"] += 1
            if count["n"] == 2:
                import httpx
                return httpx.Response(500, json={"Message": "boom"})
        return original(request, path, q)
    connected._route = flaky
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": ids}).json()
    job = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "confirm": True,
                                                              "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "FAILED"
    res = job["result"]["results"][0]
    assert res["status"] == "partial" and res["steps_created"] == 1
    tc_count = len(connected.test_cases)
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": ids}).json()
    job = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "confirm": True,
                                                              "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "COMPLETED", job
    assert len(connected.test_cases) == tc_count  # resumed, not re-created
    tc_id = int(job["result"]["results"][0]["external_id"])
    assert [s["Position"] for s in connected.steps[tc_id]] == [1, 2, 3]
    op = db.query(ApiOperation).filter_by(idempotency_key=f"spira:create_test_case:draft:{ids[0]}").one()
    assert op.status == "succeeded" and op.attempts == 2


def test_timeout_after_create_is_reconciled(client, synced, connected, db):
    _, batch = _generate(client, synced["id"], db)
    ids = [batch["drafts"][0]["id"]]
    connected.inject(r"POST projects/1/test-cases", "timeout_after_apply")
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": ids}).json()
    job = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "confirm": True,
                                                              "payload_hash": pre["payload_hash"]}).json()
    assert job["result"]["results"][0]["status"] == "unknown"
    n = len(connected.test_cases)
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": ids}).json()
    job = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": ids, "confirm": True,
                                                              "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "COMPLETED", job
    assert len(connected.test_cases) == n  # found the existing record by name instead of creating another


def test_invalid_draft_blocks_submission(client, synced, connected, db):
    _, batch = _generate(client, synced["id"], db)
    d = batch["drafts"][0]
    content = {**d["content"], "steps": [{"step_number": 1, "action": "Do it", "expected_result": "Works as expected", "test_data": ""}]}
    r = client.put(f"/api/v1/drafts/{d['id']}", json={"content": content}).json()
    assert any(i["severity"] == "error" for i in r["validation_errors"])
    assert client.put(f"/api/v1/drafts/{d['id']}", json={"status": "approved"}).status_code == 422
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": synced["id"], "draft_ids": [d["id"]]}).json()
    assert pre["blocking"]
    r = client.post("/api/v1/submissions/test-cases", json={"project_id": synced["id"], "draft_ids": [d["id"]], "confirm": True,
                                                            "payload_hash": pre["payload_hash"]})
    assert r.status_code == 422


def test_analysis_grounding_and_export(client, synced, db):
    req = db.query(Requirement).filter_by(external_id="11").one()
    job = client.post(f"/api/v1/requirements/{req.id}/analyses").json()
    a = client.get(f"/api/v1/analyses/{job['result']['analysis_id']}").json()
    c = a["content"]
    assert c["requirement_id"] == "11" and a["is_simulated"]
    assert c["acceptance_criteria"] and all(ac["origin"] == "imported" for ac in c["acceptance_criteria"])
    assert c["_verification"]["unverified_criteria"] == []
    # edits are schema-validated; invalid content rejected
    bad = client.put(f"/api/v1/analyses/{a['id']}", json={"content": {**c, "testability": "excellent"}})
    assert bad.status_code == 422
    good = client.put(f"/api/v1/analyses/{a['id']}", json={"content": {**c, "summary": "Edited summary"}}).json()
    assert good["is_edited"] and good["content"]["summary"] == "Edited summary"
    md = client.get(f"/api/v1/analyses/{a['id']}/export").text
    assert "# Requirement analysis — RQ:11" in md and "Coverage matrix" in md


def test_grounding_flags_fabricated_quotes(db):
    from app.services.analysis import verify_grounding
    ctx = {"requirement": {"external_id": "1", "description": "Users must log in."}, "linked_test_cases": [{"external_id": "5"}]}
    content = {"requirement_id": "1", "acceptance_criteria": [
        {"id": "AC-1", "origin": "imported", "source_quote": "Users must log in."},
        {"id": "AC-2", "origin": "imported", "source_quote": "Passwords expire after 90 days."}],
        "coverage_matrix": [{"existing_test_case_ids": ["5", "999"]}]}
    v = verify_grounding(content, ctx)
    assert v["unverified_criteria"] == ["AC-2"] and v["removed_unknown_test_case_ids"] == ["999"]
    assert content["coverage_matrix"][0]["existing_test_case_ids"] == ["5"]
