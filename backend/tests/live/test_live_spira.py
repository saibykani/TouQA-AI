"""Optional live checks against a real Spira instance. READ-ONLY by default.

Run only when explicitly enabled, against a designated test project:
    LIVE_TESTS_ENABLED=true LIVE_SPIRA_URL=https://toucan.spiraservice.net \
    LIVE_SPIRA_USERNAME=... LIVE_SPIRA_API_KEY=... LIVE_SPIRA_PROJECT_ID=... pytest tests/live -v
Write checks additionally require LIVE_ALLOW_WRITES=true and create a clearly named folder.
"""
import os

import pytest

from app.integrations.spira.client import SpiraClient

pytestmark = pytest.mark.skipif(os.getenv("LIVE_TESTS_ENABLED", "").lower() != "true", reason="live tests disabled")


@pytest.fixture(scope="module")
def live():
    c = SpiraClient(os.environ["LIVE_SPIRA_URL"], os.environ["LIVE_SPIRA_USERNAME"], os.environ["LIVE_SPIRA_API_KEY"])
    yield c, int(os.environ["LIVE_SPIRA_PROJECT_ID"])
    c.close()


def test_authenticated_user(live):
    c, _ = live
    assert c.current_user().get("UserId")


def test_project_and_first_pages(live):
    c, pid = live
    assert c.get_project(pid)["ProjectId"] == pid
    for it in (c.iter_requirements(pid), c.iter_test_cases(pid), c.iter_incidents(pid)):
        page = next(iter(it), [])
        assert isinstance(page, list)
    assert isinstance(c.test_case_folders(pid), list)


@pytest.mark.skipif(os.getenv("LIVE_ALLOW_WRITES", "").lower() != "true", reason="live writes disabled")
def test_create_folder_in_test_project(live):
    c, pid = live
    f = c.create_test_case_folder(pid, "TouQA live test (safe to delete)", None)
    assert f.get("TestCaseFolderId")
