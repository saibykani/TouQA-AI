"""Pure functions that map Spira JSON records to TouQA column values.

Only fields present in the Spira v7.0 schemas are read. Missing fields map to ``None``
rather than invented defaults.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from typing import Any

_MS_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")
_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"(?i)</?(p|div|br|li|tr|h[1-6]|ul|ol|table)[^>]*>")


def parse_date(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    m = _MS_DATE.match(value)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc)
    v = value.strip()
    if v.startswith("0001-01-01"):
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    # Trim fractional seconds beyond microseconds (.NET emits 7 digits)
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def html_to_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = _BLOCK.sub("\n", value)
    text = _TAG.sub("", text)
    text = html.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip()


def text_to_html(value: str | None) -> str:
    if not value:
        return ""
    paras = [p for p in value.split("\n\n")]
    return "".join(f"<p>{html.escape(p).replace(chr(10), '<br />')}</p>" for p in paras if p.strip())


def content_hash(record: dict) -> str:
    stable = {k: v for k, v in record.items() if k not in {"ConcurrencyDate", "ConcurrencyGuid"}}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, default=str).encode()).hexdigest()


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def custom_properties(record: dict) -> list:
    return record.get("CustomProperties") or []


def map_project(r: dict) -> dict:
    return {
        "external_id": str(r["ProjectId"]),
        "name": r.get("Name") or f"Project {r['ProjectId']}",
        "description": html_to_text(r.get("Description")),
        "template_id": _s(r.get("ProjectTemplateId")),
        "is_active": bool(r.get("Active", True)),
    }


def map_release(r: dict) -> dict:
    type_name = r.get("ReleaseTypeName") or ""
    return {
        "external_id": str(r["ReleaseId"]),
        "name": r.get("Name") or "",
        "version_number": r.get("VersionNumber"),
        "indent_level": r.get("IndentLevel"),
        "is_iteration": "iteration" in type_name.lower() or "sprint" in type_name.lower(),
        "type_name": type_name or None,
        "status_name": r.get("ReleaseStatusName"),
        "active": bool(r.get("Active", True)),
        "start_date": parse_date(r.get("StartDate")),
        "end_date": parse_date(r.get("EndDate")),
        "external_created_at": parse_date(r.get("CreationDate")),
        "external_updated_at": parse_date(r.get("LastUpdateDate")),
        "custom_properties": custom_properties(r),
    }


def map_requirement(r: dict) -> dict:
    desc = r.get("Description")
    return {
        "external_id": str(r["RequirementId"]),
        "name": r.get("Name") or "",
        "description_html": desc,
        "description_text": html_to_text(desc),
        "indent_level": r.get("IndentLevel"),
        "is_summary": bool(r.get("Summary")),
        "status_name": r.get("StatusName"),
        "type_name": r.get("RequirementTypeName"),
        "importance_name": r.get("ImportanceName"),
        "owner_name": r.get("OwnerName"),
        "author_name": r.get("AuthorName"),
        "release_external_id": _s(r.get("ReleaseId")),
        "release_version": r.get("ReleaseVersionNumber"),
        "component_external_id": _s(r.get("ComponentId")),
        "tags": r.get("Tags"),
        "steps": [
            {"position": s.get("Position"), "description": html_to_text(s.get("Description"))}
            for s in (r.get("Steps") or []) if isinstance(s, dict)
        ],
        "coverage": {
            "total": r.get("CoverageCountTotal"), "passed": r.get("CoverageCountPassed"),
            "failed": r.get("CoverageCountFailed"), "caution": r.get("CoverageCountCaution"),
            "blocked": r.get("CoverageCountBlocked"),
        },
        "external_created_at": parse_date(r.get("CreationDate")),
        "external_updated_at": parse_date(r.get("LastUpdateDate")),
        "custom_properties": custom_properties(r),
    }


def map_folder(r: dict, folder_type: str) -> dict:
    id_key = "TestCaseFolderId" if folder_type == "test_case" else "TestSetFolderId"
    parent_key = "ParentTestCaseFolderId" if folder_type == "test_case" else "ParentTestSetFolderId"
    return {
        "external_id": str(r[id_key]),
        "folder_type": folder_type,
        "name": r.get("Name") or "",
        "description": html_to_text(r.get("Description")),
        "parent_external_id": _s(r.get(parent_key)),
        "indent_level": r.get("IndentLevel"),
        "external_updated_at": parse_date(r.get("LastUpdateDate")),
    }


def map_test_case(r: dict) -> dict:
    desc = r.get("Description")
    return {
        "external_id": str(r["TestCaseId"]),
        "folder_external_id": _s(r.get("TestCaseFolderId")),
        "name": r.get("Name") or "",
        "description_html": desc,
        "description_text": html_to_text(desc),
        "status_name": r.get("TestCaseStatusName"),
        "type_name": r.get("TestCaseTypeName"),
        "priority_name": r.get("TestCasePriorityName"),
        "owner_name": r.get("OwnerName"),
        "author_name": r.get("AuthorName"),
        "execution_status_name": r.get("ExecutionStatusName"),
        "tags": r.get("Tags"),
        "external_created_at": parse_date(r.get("CreationDate")),
        "external_updated_at": parse_date(r.get("LastUpdateDate")),
        "custom_properties": custom_properties(r),
    }


def map_test_step(r: dict) -> dict:
    return {
        "external_id": str(r["TestStepId"]),
        "position": int(r.get("Position") or 0),
        "description": html_to_text(r.get("Description")) or "",
        "expected_result": html_to_text(r.get("ExpectedResult")),
        "sample_data": html_to_text(r.get("SampleData")),
        "precondition": html_to_text(r.get("Precondition")),
        "linked_test_case_external_id": _s(r.get("LinkedTestCaseId")),
    }


def map_test_set(r: dict) -> dict:
    desc = r.get("Description")
    return {
        "external_id": str(r["TestSetId"]),
        "folder_external_id": _s(r.get("TestSetFolderId")),
        "name": r.get("Name") or "",
        "description_html": desc,
        "description_text": html_to_text(desc),
        "status_name": r.get("TestSetStatusName"),
        "owner_name": r.get("OwnerName"),
        "release_external_id": _s(r.get("ReleaseId")),
        "release_version": r.get("ReleaseVersionNumber"),
        "planned_date": parse_date(r.get("PlannedDate")),
        "counts": {k: r.get(f"Count{k}") for k in ("Passed", "Failed", "Caution", "Blocked", "NotRun", "NotApplicable")},
        "tags": r.get("Tags"),
        "external_created_at": parse_date(r.get("CreationDate")),
        "external_updated_at": parse_date(r.get("LastUpdateDate")),
        "custom_properties": custom_properties(r),
    }


def map_incident(r: dict) -> dict:
    desc = r.get("Description")
    return {
        "external_id": str(r["IncidentId"]),
        "name": r.get("Name") or "",
        "description_html": desc,
        "description_text": html_to_text(desc),
        "status_name": r.get("IncidentStatusName"),
        "is_open": r.get("IncidentStatusOpenStatus"),
        "type_name": r.get("IncidentTypeName"),
        "priority_name": r.get("PriorityName"),
        "severity_name": r.get("SeverityName"),
        "owner_name": r.get("OwnerName"),
        "opener_name": r.get("OpenerName"),
        "detected_release_external_id": _s(r.get("DetectedReleaseId")),
        "detected_release_version": r.get("DetectedReleaseVersionNumber"),
        "resolved_release_external_id": _s(r.get("ResolvedReleaseId")),
        "resolved_release_version": r.get("ResolvedReleaseVersionNumber"),
        "component_external_ids": [str(c) for c in (r.get("ComponentIds") or [])],
        "tags": r.get("Tags"),
        "external_created_at": parse_date(r.get("CreationDate")),
        "external_updated_at": parse_date(r.get("LastUpdateDate")),
        "custom_properties": custom_properties(r),
    }


def map_user(r: dict) -> tuple[str, str, dict]:
    name = r.get("FullName") or " ".join(filter(None, [r.get("FirstName"), r.get("LastName")])) or r.get("UserName") or ""
    return str(r["UserId"]), name, {"username": r.get("UserName"), "email": r.get("EmailAddress"),
                                    "role": r.get("ProjectRoleName")}
