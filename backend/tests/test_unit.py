import logging

import httpx
import pytest

from app.ai.schemas import GeneratedTestCase, RequirementAnalysisContent
from app.integrations import http as ih
from app.integrations.jira import adf
from app.integrations.spira import mapper
from app.security.crypto import decrypt_secret, encrypt_secret
from app.security.netguard import UnsafeUrlError, validate_outbound_url
from app.security.redaction import REDACTED, RedactingFilter, redact, redact_text
from app.services import duplicates, validation
from app.services.attachments import UploadRejected, sanitize_filename, store


# ------------------------------------------------------------------ security
def test_redaction_of_secrets():
    text = "GET /projects?username=bob&api-key={11111111-2222-3333-4444-555555555555} Authorization: Basic Zm9vOmJhcg== sk-ant-abcdefghijklmnopqrstu ATATT3xFfGF0abcdefghijklmnop"
    out = redact_text(text)
    assert "11111111-2222" not in out and "Zm9vOmJhcg" not in out and "sk-ant-abc" not in out and "ATATT3x" not in out
    nested = redact({"headers": {"api-key": "{secret}", "Accept": "json"}, "password": "pw", "items": [{"token": "t"}]})
    assert nested["headers"]["api-key"] == REDACTED and nested["headers"]["Accept"] == "json"
    assert nested["password"] == REDACTED and nested["items"][0]["token"] == REDACTED


def test_logging_filter_redacts(caplog):
    logger = logging.getLogger("touqa.test")
    caplog.handler.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO):
        logger.info("calling %s", "https://x?api-key={11111111-2222-3333-4444-555555555555}")
    assert "11111111-2222" not in caplog.text


def test_encryption_roundtrip():
    c = encrypt_secret("{my-rss-token}")
    assert "{my-rss-token}" not in c and decrypt_secret(c) == "{my-rss-token}"


def test_ssrf_guard(settings_override):
    settings_override(allow_private_network_targets="false")
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("http://example.com")  # https required
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https://user:pw@example.com")
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https://127.0.0.1")
    with pytest.raises(UnsafeUrlError):
        validate_outbound_url("https://169.254.169.254")  # cloud metadata
    assert validate_outbound_url("http://localhost:11434/v1", allow_loopback_http=True).startswith("http://localhost")
    assert validate_outbound_url("toucan.spiraservice.net", resolve=False) == "https://toucan.spiraservice.net"


def test_client_refuses_other_hosts():
    c = ih.ResilientClient("https://a.example.com", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ih.IntegrationValidationError):
        c.request("GET", "https://evil.example.com/x")


# --------------------------------------------------------------- http policy
def _client(handler, **kw):
    return ih.ResilientClient("https://api.example.com", transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_get_retries_on_429_and_5xx_then_succeeds():
    seq = [429, 503, 200]
    def h(req):
        s = seq.pop(0)
        return httpx.Response(s, json={"ok": s == 200}, headers={"Retry-After": "1"})
    assert _client(h).request("GET", "/x").data == {"ok": True}
    assert seq == []


def test_get_gives_up_after_max_retries():
    calls = []
    def h(req):
        calls.append(1)
        return httpx.Response(503)
    with pytest.raises(ih.IntegrationServerError):
        _client(h, max_retries=2).request("GET", "/x")
    assert len(calls) == 3


def test_post_is_never_retried_and_timeout_is_outcome_unknown():
    calls = []
    def h(req):
        calls.append(1)
        raise httpx.ReadTimeout("t", request=req)
    with pytest.raises(ih.OutcomeUnknownError):
        _client(h).request("POST", "/create", json={})
    assert len(calls) == 1
    seq = [503]
    def h2(req):
        calls.append(2)
        return httpx.Response(seq.pop(0) if seq else 200)
    with pytest.raises(ih.IntegrationServerError):
        _client(h2).request("POST", "/create", json={})


def test_auth_and_validation_errors_are_typed():
    with pytest.raises(ih.IntegrationAuthError):
        _client(lambda r: httpx.Response(401)).request("GET", "/x")
    with pytest.raises(ih.IntegrationPermissionError):
        _client(lambda r: httpx.Response(403)).request("GET", "/x")
    with pytest.raises(ih.IntegrationValidationError) as e:
        _client(lambda r: httpx.Response(400, json={"Message": "Name is required"})).request("POST", "/x", json={})
    assert "Name is required" in e.value.user_message


def test_cancellation_between_requests():
    with pytest.raises(ih.OperationCancelled):
        _client(lambda r: httpx.Response(200)).request("GET", "/x", cancel_check=lambda: True)


# ------------------------------------------------------------------- mapping
def test_spira_date_and_html_mapping():
    assert mapper.parse_date("2026-10-01T10:00:00.1234567").year == 2026
    assert mapper.parse_date("/Date(1700000000000-0000)/").year == 2023
    assert mapper.parse_date("0001-01-01T00:00:00") is None
    assert mapper.html_to_text("<p>Hello &amp; welcome</p><ul><li>a</li><li>b</li></ul>") == "Hello & welcome\na\nb"
    r = mapper.map_requirement({"RequirementId": 5, "Name": "N", "Description": "<p>x</p>", "IndentLevel": "AAA"})
    assert r["external_id"] == "5" and r["description_text"] == "x" and r["owner_name"] is None  # missing -> None, not invented


def test_adf_builder():
    doc = adf.sections_to_adf([("Steps", ["one", "two"]), ("Logs", ("code", "trace")), ("Empty", "")])
    assert doc["type"] == "doc" and doc["version"] == 1
    types = [b["type"] for b in doc["content"]]
    assert types == ["heading", "orderedList", "heading", "codeBlock"]
    assert "one" in adf.adf_to_text(doc)


# ---------------------------------------------------------------- validation
def _case(**over):
    base = dict(name="Login with valid credentials", description="d", requirement_id="11", acceptance_criterion_ids=["AC-1"],
                category="positive", objective="o", preconditions=[], test_data=[],
                steps=[{"step_number": 5, "action": "Enter user 'a' and password 'b'", "expected_result": "Dashboard is shown", "test_data": ""}],
                expected_outcome="ok", priority="high", risk_level="low", automation_suitability="high", automation_rationale="",
                tags=[], assumptions=[], source_references=[], confidence="high", review_warnings=[])
    base.update(over)
    return base


def test_test_case_validation_rules():
    content, issues = validation.validate_test_case(_case(), allowed_requirement_ids={"11"}, known_criterion_ids={"AC-1"})
    assert not validation.has_errors(issues) and content["steps"][0]["step_number"] == 1  # renumbered
    _, issues = validation.validate_test_case(_case(steps=[{"step_number": 1, "action": "Do it", "expected_result": "Works as expected", "test_data": ""}]))
    assert validation.has_errors(issues)  # unverifiable expected result
    _, issues = validation.validate_test_case(_case(steps=[]))
    assert validation.has_errors(issues)
    _, issues = validation.validate_test_case(_case(requirement_id="99"), allowed_requirement_ids={"11"})
    assert any(i["field"] == "requirement_id" for i in issues)
    _, issues = validation.validate_test_case(_case(acceptance_criterion_ids=["AC-9"]), known_criterion_ids={"AC-1"})
    assert any(i["severity"] == "warning" and "AC-9" in i["message"] for i in issues)
    _, issues = validation.validate_test_case({"name": "x"})
    assert validation.has_errors(issues)


def test_schemas_reject_invalid_ai_output():
    with pytest.raises(Exception):
        GeneratedTestCase.model_validate(_case(category="made_up"))
    with pytest.raises(Exception):
        RequirementAnalysisContent.model_validate({"requirement_id": "1"})


def test_duplicate_detection_is_not_title_only():
    a = duplicates.from_draft_content(_case())
    same_steps = duplicates.from_draft_content(_case(name="Sign in using correct username and password"))
    assert duplicates.compare(a, same_steps)["level"] in ("possible", "likely")
    title_twin = duplicates.from_draft_content(_case(steps=[{"step_number": 1, "action": "Open the reports page and export CSV",
                                                             "expected_result": "File downloads", "test_data": ""}], requirement_id="77"))
    r = duplicates.compare(a, title_twin)
    assert r["level"] != "likely" and r["title_only"] is True and "title similarity only" in r["explanation"]
    identical = duplicates.compare(a, duplicates.from_draft_content(_case()))
    assert identical["level"] == "likely"


# --------------------------------------------------------------- attachments
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8"
       b"\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


def test_attachment_validation(settings_override):
    meta = store(PNG, "../../etc/passwd.png", "text/plain")
    assert meta["content_type"] == "image/png" and meta["width"] == 1 and "/" not in meta["original_filename"]
    assert sanitize_filename("..\\..\\x<>.png") == "x_.png"
    with pytest.raises(UploadRejected):
        store(b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100, "evil.exe", "application/octet-stream")
    with pytest.raises(UploadRejected):
        store(b"", "empty.txt", "text/plain")
    settings_override(max_upload_bytes=10)
    with pytest.raises(UploadRejected):
        store(b"x" * 11, "big.txt", "text/plain")
