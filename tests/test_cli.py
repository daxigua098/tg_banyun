from __future__ import annotations

from app.cli import build_parser


def test_run_accepts_skip_history_flag() -> None:
    args = build_parser().parse_args(["run", "--skip-history"])
    assert args.command == "run"
    assert args.skip_history is True
