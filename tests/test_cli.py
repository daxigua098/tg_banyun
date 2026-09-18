from __future__ import annotations

from app.cli import build_parser


def test_run_accepts_skip_history_flag() -> None:
    args = build_parser().parse_args(["run", "--skip-history"])
    assert args.command == "run"
    assert args.skip_history is True

def test_record_add_accepts_join_and_multiple_inputs() -> None:
    args = build_parser().parse_args(
        ["record", "add", "--join", "https://t.me/+invite", "https://t.me/records"]
    )
    assert args.command == "record"
    assert args.record_command == "add"
    assert args.join is True
    assert args.inputs == ["https://t.me/+invite", "https://t.me/records"]

def test_status_command_parses() -> None:
    args = build_parser().parse_args(["status"])
    assert args.command == "status"

def test_backup_and_restore_commands_parse() -> None:
    backup = build_parser().parse_args(["backup"])
    assert backup.command == "backup"
    restore = build_parser().parse_args(["restore", "backup.zip", "--yes"])
    assert restore.command == "restore"
    assert restore.yes is True
