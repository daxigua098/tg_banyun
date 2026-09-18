"""Backup and restore support for the SQLite MVP deployment."""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from loguru import logger

PROJECT_FILES = (
    ".env",
    "configs/config.yaml",
)
RESTORE_ROOTS = (
    ".env",
    "configs/config.yaml",
    "data/app.db",
)


class BackupError(RuntimeError):
    """Raised when a backup archive is invalid or unsafe to restore."""


def _sqlite_path(project_root: Path, database_url: str) -> Path | None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return None
    raw_path = database_url.removeprefix(prefix)
    if raw_path == ":memory:":
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path
    return path


def _add_sqlite_snapshot(
    archive: zipfile.ZipFile,
    source_path: Path,
    archive_name: str,
) -> None:
    if not source_path.exists():
        return
    with tempfile.TemporaryDirectory() as temp_dir:
        snapshot = Path(temp_dir) / "app.db"
        source = sqlite3.connect(source_path)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        archive.write(snapshot, archive_name)


def _add_missing_file(
    archive: zipfile.ZipFile,
    path: Path,
    archive_name: str,
) -> None:
    if path.exists() and path.is_file():
        archive.write(path, archive_name)


def create_backup(project_root: Path, output_dir: Path | None = None) -> Path:
    """Create a timestamped backup of database, sessions and configuration."""
    project_root = project_root.resolve()
    output_dir = (output_dir or project_root / "backups").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    archive_path = output_dir / f"tg-mirror-bot-{timestamp}.zip"

    database_url = "sqlite+aiosqlite:///./data/app.db"
    config_path = project_root / "configs" / "config.yaml"
    if config_path.exists():
        try:
            import yaml

            config_data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            database_url = str(
                (config_data.get("database") or {}).get("url", database_url)
            )
        except Exception:
            pass

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in PROJECT_FILES:
            _add_missing_file(archive, project_root / relative, relative)

        database_path = _sqlite_path(project_root, database_url)
        if database_path is not None:
            _add_sqlite_snapshot(archive, database_path, "data/app.db")

        sessions_dir = project_root / "data" / "sessions"
        if sessions_dir.exists():
            for session_path in sorted(sessions_dir.glob("*.session*")):
                archive.write(
                    session_path,
                    f"data/sessions/{session_path.name}",
                )

        archive.writestr(
            "metadata.json",
            json.dumps(
                {
                    "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "format": "tg-mirror-bot-backup-v1",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

    return archive_path


def list_backups(directory: Path) -> list[Path]:
    """Return backup archives ordered from newest to oldest."""
    if not directory.exists():
        return []
    return sorted(
        directory.glob("tg-mirror-bot-*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def latest_backup(directory: Path) -> Path | None:
    """Return the newest backup archive when one exists."""
    backups = list_backups(directory)
    return backups[0] if backups else None


def is_backup_due(
    directory: Path,
    interval_hours: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether an automatic backup should run."""
    latest = latest_backup(directory)
    if latest is None:
        return True
    now = now or datetime.now(UTC)
    modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
    return now - modified >= timedelta(hours=interval_hours)


def prune_backups(directory: Path, retention_count: int) -> int:
    """Delete old backup archives while keeping the newest retention_count files."""
    backups = list_backups(directory)
    removed = 0
    for archive in backups[retention_count:]:
        try:
            archive.unlink()
            removed += 1
        except OSError:
            logger.exception("Failed to remove old backup: {}", archive)
    return removed


def _validate_archive_member(name: str) -> None:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise BackupError(f"Unsafe path in backup archive: {name}")


def restore_backup(project_root: Path, archive_path: Path, *, yes: bool = False) -> list[str]:
    """Restore supported files from a backup archive."""
    if not yes:
        raise BackupError("Restore requires --yes to overwrite local data.")
    if not archive_path.exists():
        raise BackupError(f"Backup archive not found: {archive_path}")

    project_root = project_root.resolve()
    restored: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        extract_root = Path(temp_dir)
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                _validate_archive_member(member.filename)
            archive.extractall(extract_root)

        for relative in RESTORE_ROOTS:
            source = extract_root / relative
            if not source.exists():
                continue
            destination = project_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
            restored.append(relative)

        session_root = extract_root / "data" / "sessions"
        if session_root.exists():
            destination_root = project_root / "data" / "sessions"
            destination_root.mkdir(parents=True, exist_ok=True)
            for session_path in session_root.glob("*.session*"):
                shutil.copy2(session_path, destination_root / session_path.name)
                restored.append(f"data/sessions/{session_path.name}")

    return restored
