"""Validated local storage for uploaded evidence.

* Size limit and MIME allow-list from settings; the MIME type is derived from content
  (magic bytes / Pillow), never trusted from the client.
* Files are stored under a random name in UPLOAD_DIR; the original filename is sanitised and
  kept only as metadata, so path traversal is impossible.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import get_settings

IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")
Image.MAX_IMAGE_PIXELS = 60_000_000  # decompression-bomb guard


class UploadRejected(ValueError):
    pass


def sanitize_filename(name: str) -> str:
    base = Path(name or "file").name.replace("\x00", "")
    base = _SAFE.sub("_", base).strip(" .") or "file"
    return base[:150]


def sniff(data: bytes, declared: str | None, filename: str) -> tuple[str, int | None, int | None]:
    """Return (content_type, width, height) after verifying the content."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.verify()
        if fmt in IMAGE_FORMATS:
            with Image.open(io.BytesIO(data)) as im2:
                w, h = im2.size
            return IMAGE_FORMATS[fmt], w, h
        raise UploadRejected(f"Unsupported image format: {fmt}")
    except (UnidentifiedImageError, OSError, SyntaxError):
        pass
    except Image.DecompressionBombError as exc:
        raise UploadRejected("Image dimensions are too large.") from exc
    if data.startswith(b"%PDF-"):
        return "application/pdf", None, None
    if b"\x00" in data[:4096]:
        raise UploadRejected("Binary files of this type are not allowed.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadRejected("Text files must be UTF-8 encoded.") from exc
    lower = filename.lower()
    if lower.endswith(".json") or (declared == "application/json"):
        try:
            json.loads(text)
            return "application/json", None, None
        except ValueError:
            return "text/plain", None, None
    if lower.endswith(".csv"):
        return "text/csv", None, None
    return "text/plain", None, None


def store(data: bytes, filename: str, declared_type: str | None) -> dict:
    s = get_settings()
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > s.max_upload_bytes:
        raise UploadRejected(f"File exceeds the {s.max_upload_bytes // (1024 * 1024)} MB limit.")
    clean = sanitize_filename(filename)
    ctype, w, h = sniff(data, declared_type, clean)
    if ctype not in s.allowed_upload_types:
        raise UploadRejected(f"File type {ctype} is not allowed.")
    stored = f"{uuid.uuid4().hex}"
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    path = (s.upload_dir / stored).resolve()
    if s.upload_dir.resolve() not in path.parents:
        raise UploadRejected("Invalid storage path.")
    path.write_bytes(data)
    return {"original_filename": clean, "stored_name": stored, "content_type": ctype, "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "width": w, "height": h}


def read(stored_name: str) -> bytes:
    s = get_settings()
    if not re.fullmatch(r"[0-9a-f]{32}", stored_name or ""):
        raise UploadRejected("Invalid attachment reference.")
    path = (s.upload_dir / stored_name).resolve()
    if s.upload_dir.resolve() not in path.parents or not path.is_file():
        raise UploadRejected("Attachment file not found.")
    return path.read_bytes()


def delete(stored_name: str) -> None:
    s = get_settings()
    if re.fullmatch(r"[0-9a-f]{32}", stored_name or ""):
        p = (s.upload_dir / stored_name).resolve()
        if s.upload_dir.resolve() in p.parents and p.is_file():
            p.unlink()
