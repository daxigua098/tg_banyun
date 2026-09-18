from __future__ import annotations

import os
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.services.backup_service import (
    BackupError,
    create_backup,
    is_backup_due,
    prune_backups,
    restore_backup,
)


def _build_project(root: Path) -> None:
    (root / "configs").mkdir(parents=True)
    (root / "data" / "sessions").mkdir(parents=True)
    (root / ".env").write_text("TG_API_ID=1\n", encoding="utf-8")
    (root / "configs" / "config.yaml").write_text(
        "database:\n  url: sqlite+aiosqlite:///./data/app.db\n",
        encoding="utf-8",
    )
    (root / "data" / "sessions" / "default.session").write_bytes(b"session")
    connection = sqlite3.connect(root / "data" / "app.db")
    connection.execute("CREATE TABLE sample (value TEXT)")
    connection.execute("INSERT INTO sample VALUES ('ok')")
    connection.commit()
    connection.close()


def test_backup_and_restore_round_trip(tmp_path) -> None:
    source_root = tmp_path / "source"
    destination_root = tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    _build_project(source_root)

    archive = create_backup(source_root, output_dir=tmp_path / "backups")
    with zipfile.ZipFile(archive) as backup:
        names = set(backup.namelist())
    assert "data/app.db" in names
    assert "data/sessions/default.session" in names
    assert ".env" in names
    assert "configs/config.yaml" in names

    restored = restore_backup(destination_root, archive, yes=True)
    assert "data/app.db" in restored
    assert (destination_root / "data" / "sessions" / "default.session").read_bytes() == b"session"
    connection = sqlite3.connect(destination_root / "data" / "app.db")
    assert connection.execute("SELECT value FROM sample").fetchone() == ("ok",)
    connection.close()


def test_restore_requires_confirmation(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass

    with pytest.raises(BackupError, match="--yes"):
        restore_backup(root, archive)


def test_restore_rejects_path_traversal(tmp_path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as backup:
        backup.writestr("../outside.txt", "unsafe")

    with pytest.raises(BackupError, match="Unsafe path"):
        restore_backup(root, archive, yes=True)


def test_backup_due_and_retention(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    assert is_backup_due(backup_dir, 24) is True

    now = datetime.now(UTC)
    for index in range(8):
        archive = backup_dir / f"tg-mirror-bot-{index}.zip"
        archive.write_bytes(b"backup")
        timestamp = (now - timedelta(hours=index + 1)).timestamp()
        os.utime(archive, (timestamp, timestamp))

    assert is_backup_due(backup_dir, 24, now=now) is False

    for index in range(8):
        archive = backup_dir / f"tg-mirror-bot-{index}.zip"
        timestamp = (now - timedelta(hours=30 + index)).timestamp()
        os.utime(archive, (timestamp, timestamp))
    assert is_backup_due(backup_dir, 24, now=now) is True

    removed = prune_backups(backup_dir, 3)
    assert removed == 5
    assert len(list(backup_dir.glob("tg-mirror-bot-*.zip"))) == 3
