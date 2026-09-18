"""Safe local image uploads for additional content."""

from __future__ import annotations

import uuid
from pathlib import Path

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class UploadError(ValueError):
    """Raised when an uploaded image is invalid."""


def save_additional_image(
    project_root: Path,
    filename: str | None,
    content: bytes,
) -> str:
    """Save an uploaded image and return its project-relative path."""
    if not content:
        raise UploadError("上传文件为空。")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadError("图片不能超过 10 MB。")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise UploadError("仅支持 PNG、JPG、JPEG、WEBP 和 GIF 图片。")

    upload_dir = project_root / "assets" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    destination = upload_dir / stored_name
    destination.write_bytes(content)
    return f"assets/uploads/{stored_name}"
