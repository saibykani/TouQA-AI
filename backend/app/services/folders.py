"""Test case folder tree, validation and confirmed creation in Spira."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db import utcnow
from app.integrations.http import IntegrationError, IntegrationValidationError, OutcomeUnknownError
from app.integrations.spira import mapper
from app.models import Folder, Project
from app.services import audit, operations
from app.services.integrations import external_writes_allowed, spira_client

NAME_MAX = 255
_BAD_CHARS = re.compile(r"[<>\\]")


class FolderError(Exception):
    def __init__(self, message: str, *, code: str = "invalid", existing: dict | None = None):
        super().__init__(message)
        self.message, self.code, self.existing = message, code, existing


def to_dict(f: Folder) -> dict:
    return {"id": f.id, "external_id": f.external_id, "name": f.name, "parent_external_id": f.parent_external_id,
            "folder_type": f.folder_type, "description": f.description, "indent_level": f.indent_level}


def tree(db: Session, project_id: int, folder_type: str = "test_case") -> list[dict]:
    rows = db.query(Folder).filter_by(project_id=project_id, folder_type=folder_type, is_deleted_externally=False).all()
    nodes = {f.external_id: {**to_dict(f), "children": []} for f in rows}
    roots = []
    for n in sorted(nodes.values(), key=lambda n: (n["indent_level"] or "", n["name"].lower())):
        parent = nodes.get(n["parent_external_id"]) if n["parent_external_id"] else None
        (parent["children"] if parent else roots).append(n)
    return roots


def path_of(db: Session, project_id: int, external_id: str | None, folder_type: str = "test_case") -> list[str]:
    if not external_id:
        return []
    rows = {f.external_id: f for f in db.query(Folder).filter_by(project_id=project_id, folder_type=folder_type)}
    path, cur, guard = [], rows.get(str(external_id)), 0
    while cur is not None and guard < 50:
        path.insert(0, cur.name)
        cur = rows.get(cur.parent_external_id) if cur.parent_external_id else None
        guard += 1
    return path


def refresh(db: Session, project: Project) -> list[dict]:
    """Re-read the test case folder hierarchy from Spira."""
    with spira_client(db) as client:
        records = client.test_case_folders(int(project.external_id))
    existing = {f.external_id: f for f in db.query(Folder).filter_by(project_id=project.id, folder_type="test_case")}
    seen = set()
    for r in records:
        data = mapper.map_folder(r, "test_case")
        data.pop("folder_type")
        seen.add(data["external_id"])
        row = existing.get(data["external_id"])
        if row is None:
            row = Folder(project_id=project.id, folder_type="test_case", raw={}, **data)
            db.add(row)
        else:
            for k, v in data.items():
                setattr(row, k, v)
            row.is_deleted_externally = False
        row.synced_at = utcnow()
    for ext, row in existing.items():
        if ext not in seen:
            row.is_deleted_externally = True
    db.commit()
    return tree(db, project.id)


def validate_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise FolderError("Folder name is required.")
    if len(clean) > NAME_MAX:
        raise FolderError(f"Folder name must be at most {NAME_MAX} characters.")
    if _BAD_CHARS.search(clean):
        raise FolderError("Folder name must not contain <, > or \\ characters.")
    return clean


def check_duplicate(db: Session, project: Project, name: str, parent_external_id: str | None) -> Folder | None:
    target = name.strip().lower()
    q = db.query(Folder).filter_by(project_id=project.id, folder_type="test_case", is_deleted_externally=False)
    for f in q:
        if (f.parent_external_id or None) == (parent_external_id or None) and f.name.strip().lower() == target:
            return f
    return None


def preview(db: Session, project: Project, name: str, parent_external_id: str | None) -> dict:
    clean = validate_name(name)
    if parent_external_id and not db.query(Folder).filter_by(project_id=project.id, folder_type="test_case",
                                                             external_id=str(parent_external_id)).first():
        raise FolderError("The selected parent folder no longer exists. Refresh the folder tree.", code="parent_missing")
    dup = check_duplicate(db, project, clean, parent_external_id)
    return {
        "name": clean, "parent_external_id": parent_external_id,
        "path": path_of(db, project.id, parent_external_id) + [clean],
        "duplicate": to_dict(dup) if dup else None,
        "operation": "POST /projects/{project_id}/test-folders",
        "payload": {"Name": clean, "ProjectId": int(project.external_id),
                    **({"ParentTestCaseFolderId": int(parent_external_id)} if parent_external_id else {})},
    }


def create(db: Session, project: Project, name: str, parent_external_id: str | None, *, user_id: int | None,
           description: str | None = None) -> dict:
    allowed, reason = external_writes_allowed()
    if not allowed:
        raise FolderError(reason, code="writes_disabled")
    clean = validate_name(name)
    # Re-read the live tree so the duplicate check is against Spira, not a stale copy.
    refresh(db, project)
    dup = check_duplicate(db, project, clean, parent_external_id)
    if dup:
        raise FolderError(f"A folder named '{dup.name}' already exists in this location.", code="duplicate", existing=to_dict(dup))
    key = f"spira:create_folder:{project.external_id}:{parent_external_id or 'root'}:{clean.lower()}"
    op = operations.get_or_create(db, key, platform="spira", operation="create_test_case_folder", project_id=project.id,
                                  entity_type="folder", entity_id=None, summary={"name": clean, "parent": parent_external_id})
    if op.status == "succeeded" and op.external_id:
        f = db.query(Folder).filter_by(project_id=project.id, folder_type="test_case", external_id=op.external_id).first()
        if f and not f.is_deleted_externally:
            return {"folder": to_dict(f), "tree": tree(db, project.id), "already_existed": True}
    op.status, op.attempts = "in_flight", op.attempts + 1
    db.commit()
    try:
        with spira_client(db) as client:
            created = client.create_test_case_folder(int(project.external_id), clean,
                                                     int(parent_external_id) if parent_external_id else None, description)
    except OutcomeUnknownError as exc:
        op.status, op.error = "unknown", exc.user_message
        db.commit()
        refresh(db, project)
        found = check_duplicate(db, project, clean, parent_external_id)
        if found:
            op.status, op.external_id, op.error = "succeeded", found.external_id, None
            db.commit()
            return {"folder": to_dict(found), "tree": tree(db, project.id), "reconciled": True}
        raise FolderError(exc.user_message, code="unknown_outcome") from exc
    except IntegrationError as exc:
        op.status, op.error, op.response_status = "failed", exc.user_message, exc.status_code
        audit.record(db, action="spira.folder.create", category="external_write", outcome="failure", user_id=user_id,
                     project_id=project.id, platform="spira", summary=f"Folder '{clean}' creation failed: {exc.user_message}")
        db.commit()
        raise
    new_id = str((created or {}).get("TestCaseFolderId") or "")
    if not new_id:
        op.status, op.error = "unknown", "Spira did not return the new folder ID"
        db.commit()
        raise IntegrationValidationError("Spira did not return the new folder ID; refresh the folder tree to verify.")
    op.status, op.external_id, op.error = "succeeded", new_id, None
    audit.record(db, action="spira.folder.create", category="external_write", outcome="success", user_id=user_id,
                 project_id=project.id, platform="spira", entity_type="folder", entity_id=new_id,
                 summary=f"Created test case folder '{clean}' (TF:{new_id})",
                 details={"parent": parent_external_id})
    db.commit()
    refresh(db, project)
    f = db.query(Folder).filter_by(project_id=project.id, folder_type="test_case", external_id=new_id).first()
    return {"folder": to_dict(f) if f else {"external_id": new_id, "name": clean}, "tree": tree(db, project.id)}
