"""Listing and deletion of files stored under assets/uploads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class UploadAssetError(ValueError):
    """Raised when an upload asset operation is unsafe or invalid."""


def uploads_directory(project_root: Path) -> Path:
    path = project_root / "assets" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_file(directory: Path, filename: str) -> Path:
    name = Path(filename).name
    if name != filename or not name:
        raise UploadAssetError("文件名不合法。")
    path = directory / name
    if not path.is_file():
        raise UploadAssetError(f"文件不存在：{filename}")
    return path


def list_upload_assets(project_root: Path) -> list[dict[str, object]]:
    directory = uploads_directory(project_root)
    items: list[dict[str, object]] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        suffix = path.suffix.lower()
        items.append(
            {
                "filename": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                "url": f"/uploads/{path.name}",
                "is_image": suffix in IMAGE_SUFFIXES,
            }
        )
    return items


def delete_upload_assets(project_root: Path, filenames: list[str]) -> int:
    directory = uploads_directory(project_root)
    deleted = 0
    for filename in filenames:
        path = _safe_file(directory, filename)
        path.unlink()
        deleted += 1
    return deleted
