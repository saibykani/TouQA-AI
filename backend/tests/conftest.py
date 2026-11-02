import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

_TMP = Path(tempfile.mkdtemp(prefix="touqa-tests-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "AUTH_ENABLED": "false",
    "DEMO_MODE": "false",
    "AI_PROVIDER": "simulated",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "ALLOW_PRIVATE_NETWORK_TARGETS": "true",  # fake hosts do not resolve in tests
    "RATE_LIMIT_PER_MINUTE": "100000",
    "AI_RATE_LIMIT_PER_MINUTE": "100000",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app import db as dbmod  # noqa: E402
from app.services import integrations as isvc  # noqa: E402
from app.services import jobs as jobsvc  # noqa: E402
from tests.fakes import JIRA, SPIRA, FakeJira, FakeSpira  # noqa: E402

jobsvc.RUN_INLINE = True


@pytest.fixture()
def settings_override(monkeypatch):
    def apply(**kw):
        for k, v in kw.items():
            monkeypatch.setenv(k.upper(), str(v))
        get_settings.cache_clear()
    yield apply
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_db():
    dbmod.configure_engine()
    import app.models  # noqa: F401

    dbmod.Base.metadata.drop_all(dbmod.get_engine())
    dbmod.Base.metadata.create_all(dbmod.get_engine())
    isvc.TEST_TRANSPORTS.clear()
    from app.security.ratelimit import limiter
    limiter._hits.clear()
    yield
    isvc.TEST_TRANSPORTS.clear()


@pytest.fixture()
def db():
    s = dbmod.session_factory()()
    yield s
    s.close()


@pytest.fixture()
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def spira():
    fake = FakeSpira()
    isvc.TEST_TRANSPORTS["spira"] = fake.transport()
    return fake


@pytest.fixture()
def jira():
    fake = FakeJira()
    isvc.TEST_TRANSPORTS["jira"] = fake.transport()
    return fake


@pytest.fixture()
def connected(client, spira):
    r = client.put("/api/v1/integrations/spira", json={"base_url": SPIRA, "username": spira.username, "api_key": spira.api_key})
    assert r.status_code == 200, r.text
    return spira


@pytest.fixture()
def synced(client, connected):
    """Spira configured, project imported and fully synchronised."""
    p = client.post("/api/v1/projects/import", json={"external_id": "1"}).json()
    job = client.post("/api/v1/sync/jobs", json={"project_id": p["id"]}).json()
    assert job["status"] in ("QUEUED", "RUNNING", "COMPLETED")
    detail = client.get(f"/api/v1/sync/jobs/{job['id']}").json()
    assert detail["status"] == "COMPLETED", detail
    return p


@pytest.fixture()
def jira_connected(client, jira):
    r = client.put("/api/v1/integrations/jira", json={"base_url": JIRA, "email": "qa@example.com", "api_token": "ATATT-test-token-value-123456789",
                                                      "project_key": "QA", "issue_type_id": "10001"})
    assert r.status_code == 200, r.text
    return jira
