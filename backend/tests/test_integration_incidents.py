"""Incident Studio, Jira, auth/CSRF, demo mode and migrations."""
from app.models import ApiOperation, AuditLog, IncidentDraft
from tests.test_unit import PNG

NOTES = ("When I submit a payment with an expired card, the application shows a loading spinner and never displays an error. "
         "The transaction remains pending. This happens on the UAT environment.")


def _draft(client, project_id, destinations=("spira",)):
    d = client.post("/api/v1/incident-drafts", json={"project_id": project_id, "raw_notes": NOTES,
                                                     "evidence": {"environment": {"browser": "Chrome 130"}},
                                                     "destinations": list(destinations)}).json()
    up = client.post(f"/api/v1/incident-drafts/{d['id']}/attachments", files={"file": ("shot.png", PNG, "image/png")})
    assert up.status_code == 200, up.text
    job = client.post(f"/api/v1/incident-drafts/{d['id']}/analyze").json()
    assert job["status"] == "NEEDS_REVIEW", job
    return client.get(f"/api/v1/incident-drafts/{d['id']}").json()


def test_incident_draft_does_not_invent_facts(client, synced):
    d = _draft(client, synced["id"])
    c = d["content"]
    assert c["environment"]["environment"] == "UAT" and c["environment"]["browser"] == "Chrome 130"
    assert c["expected_result"].startswith("Unknown")  # not stated by the reporter
    assert c["severity"] == "unknown" and "Expected behaviour" in c["missing_information"]
    assert all(f["source"] == "user_notes" for f in c["observed_facts"])
    assert d["is_simulated"] and d["attachments"][0]["is_image"]
    # classification only pre-fills resolvable IDs (default type from Spira metadata)
    assert d["classification"]["spira"].get("type_id") == "1"


def test_upload_rejections(client, synced):
    d = client.post("/api/v1/incident-drafts", json={"project_id": synced["id"], "raw_notes": "x"}).json()
    r = client.post(f"/api/v1/incident-drafts/{d['id']}/attachments", files={"file": ("a.exe", b"MZ\x00\x00" + b"\x00" * 64, "application/x-msdownload")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "upload_rejected"


def test_spira_incident_submission_with_attachment(client, synced, connected, db):
    d = _draft(client, synced["id"])
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    sp = pre["destinations"]["spira"]
    assert not sp["blocking"] and sp["payload"]["IncidentTypeId"] == 1 and len(sp["attachments"]) == 1
    assert "<h3>Steps to reproduce</h3>" in sp["payload"]["Description"] or "<h3>Expected result</h3>" in sp["payload"]["Description"]
    assert not [d_ for d_ in connected.documents]  # nothing uploaded before approval
    r = client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": False, "payload_hash": pre["payload_hash"]})
    assert r.status_code == 400
    job = client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": True, "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "COMPLETED", job
    res = job["result"]["results"]["spira"]
    assert res["status"] == "created" and res["url"].endswith(f"/Incident/{res['external_id']}.aspx")
    assert len(connected.documents) == 1
    assert db.query(AuditLog).filter_by(action="spira.incident.create", outcome="success").count() == 1


def test_workflow_required_field_blocks(client, synced, connected):
    connected.workflow_required = ["OwnerId"]
    d = _draft(client, synced["id"])
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    assert pre["destinations"]["spira"]["blocking"]
    assert any(i["field"] == "OwnerId" for i in pre["destinations"]["spira"]["issues"])
    cls = {**d["classification"], "spira": {**d["classification"]["spira"], "owner_id": "1"}}
    client.put(f"/api/v1/incident-drafts/{d['id']}", json={"classification": cls})
    assert not client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()["destinations"]["spira"]["blocking"]
    cls["spira"]["owner_id"] = "999"  # unknown external id is rejected, never sent
    client.put(f"/api/v1/incident-drafts/{d['id']}", json={"classification": cls})
    issues = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()["destinations"]["spira"]["issues"]
    assert any("not a known value" in i["message"] for i in issues)


def test_jira_connection_and_both_destinations_partial_failure(client, synced, connected, jira_connected, db):
    assert client.post("/api/v1/integrations/jira/test").json()["ok"]
    assert client.get("/api/v1/integrations/jira/issue-types").json()[0]["name"] == "Bug"
    d = _draft(client, synced["id"], ("spira", "jira"))
    jira_connected.inject(r"POST /rest/api/3/issue", 500)
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    assert set(pre["destinations"]) == {"spira", "jira"} and not pre["blocking"]
    job = client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": True, "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "PARTIALLY_COMPLETED", job
    r = job["result"]["results"]
    assert r["spira"]["status"] == "created" and r["jira"]["status"] == "failed"
    assert db.get(IncidentDraft, d["id"]).status == "partially_submitted"
    n_spira = len(connected.incidents)
    # retry: Spira is not re-created, Jira is created once
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    job = client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": True, "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "COMPLETED", job
    assert len(connected.incidents) == n_spira and len(jira_connected.issues) == 1
    assert job["result"]["results"]["jira"]["external_key"] == "QA-1"
    assert len(jira_connected.attachments) == 1


def test_jira_timeout_is_reconciled(client, synced, connected, jira_connected):
    d = _draft(client, synced["id"], ("jira",))
    original = jira_connected.handle
    state = {"done": False}
    def handle(req):
        if req.method == "POST" and req.url.path == "/rest/api/3/issue" and not state["done"]:
            state["done"] = True
            original(req)  # applied remotely...
            import httpx
            raise httpx.ReadTimeout("lost response", request=req)  # ...but the response is lost
        return original(req)
    from app.services import integrations as isvc
    import httpx
    isvc.TEST_TRANSPORTS["jira"] = httpx.MockTransport(handle)
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    job = client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": True, "payload_hash": pre["payload_hash"]}).json()
    assert job["result"]["results"]["jira"]["status"] == "unknown"
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    job = client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": True, "payload_hash": pre["payload_hash"]}).json()
    assert job["status"] == "COMPLETED" and len(jira_connected.issues) == 1


def test_jira_required_custom_field(client, synced, connected, jira_connected):
    jira_connected.required_extra = [{"fieldId": "customfield_10050", "name": "Environment Tier", "required": True}]
    d = _draft(client, synced["id"], ("jira",))
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    assert pre["destinations"]["jira"]["blocking"]
    assert any(i["field"] == "customfield_10050" for i in pre["destinations"]["jira"]["issues"])


def test_audit_log_api_records_external_writes(client, synced, connected):
    d = _draft(client, synced["id"])
    pre = client.get(f"/api/v1/incident-drafts/{d['id']}/preview").json()
    client.post(f"/api/v1/incident-drafts/{d['id']}/submit", json={"confirm": True, "payload_hash": pre["payload_hash"]})
    log = client.get("/api/v1/audit", params={"category": "external_write"}).json()
    assert log["total"] >= 2  # incident + attachment
    assert all(connected.api_key not in str(i) for i in log["items"])
    ops = client.get("/api/v1/operations", params={"project_id": synced["id"]}).json()
    assert {o["operation"] for o in ops} >= {"create_incident", "upload_attachment"}


def test_dashboard_metrics_from_real_data(client, synced):
    m = client.get("/api/v1/dashboard", params={"project_id": synced["id"]}).json()
    assert m["counts"]["requirements"] == 5 and m["counts"]["test_cases"] == 4 and m["counts"]["incidents"] == 3
    assert m["coverage"]["leaf_requirements"] == 4 and m["coverage"]["covered"] == 1 and m["coverage"]["reliable"]
    assert m["recent_syncs"][0]["status"] == "COMPLETED"


# --------------------------------------------------------------- auth & demo
def test_auth_and_csrf(client, settings_override):
    settings_override(auth_enabled="true", admin_password="Sup3r-secret-pw")
    from app.db import session_factory
    from app.security.auth import ensure_bootstrap_admin
    with session_factory()() as s:
        ensure_bootstrap_admin(s)
    assert client.get("/api/v1/projects").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "admin@touqa.local", "password": "nope"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "admin@touqa.local", "password": "Sup3r-secret-pw"})
    assert r.status_code == 200
    csrf = r.json()["csrf_token"]
    assert "httponly" in r.headers.get("set-cookie", "").lower()
    assert client.get("/api/v1/projects").status_code == 200
    body = {"project_id": 1, "raw_notes": "x"}
    assert client.post("/api/v1/incident-drafts", json=body).status_code == 403  # missing CSRF header
    assert client.post("/api/v1/incident-drafts", json=body, headers={"X-CSRF-Token": csrf}).status_code == 404  # passes CSRF


def test_demo_mode_blocks_external_writes(client, settings_override):
    settings_override(demo_mode="true")
    p = client.post("/api/v1/projects/demo/seed").json()
    assert "synthetic" in p["name"]
    from app.db import session_factory
    from app.models import Requirement
    with session_factory()() as s:
        req = s.query(Requirement).filter_by(project_id=p["id"], external_id="102").one()
        rid = req.id
    job = client.post(f"/api/v1/requirements/{rid}/analyses").json()
    a = client.get(f"/api/v1/analyses/{job['result']['analysis_id']}").json()
    assert a["is_simulated"] and len(a["content"]["acceptance_criteria"]) >= 3
    job = client.post("/api/v1/generation", json={"project_id": p["id"], "requirement_ids": [rid],
                                                  "config": {"counts": {"positive": 1, "negative": 2, "accessibility": 1}}}).json()
    batch = client.get(f"/api/v1/generation/batches/{job['result']['batch_id']}").json()
    assert batch["summary"]["skipped_categories"]  # accessibility not applicable -> skipped, not invented
    ids = [d["id"] for d in batch["drafts"]]
    pre = client.post("/api/v1/submissions/test-cases/preview", json={"project_id": p["id"], "draft_ids": ids, "folder_external_id": "11"}).json()
    assert pre["writes_allowed"] is False and pre["writes_disabled_reason"]
    r = client.post("/api/v1/submissions/test-cases", json={"project_id": p["id"], "draft_ids": ids, "folder_external_id": "11",
                                                            "confirm": True, "payload_hash": pre["payload_hash"]})
    assert r.status_code == 403
    assert client.get("/api/v1/dashboard", params={"project_id": p["id"]}).json()["project"]["is_demo"]


def test_demo_project_hidden_outside_demo_mode(client, settings_override):
    settings_override(demo_mode="true")
    client.post("/api/v1/projects/demo/seed")
    settings_override(demo_mode="false")
    assert client.get("/api/v1/projects").json() == []


def test_migrations_match_models(tmp_path):
    from alembic import command
    from alembic.config import Config
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    from app.db import configure_engine
    configure_engine()  # restore the test engine
