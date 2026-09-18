from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import TransferConfig


def test_mvp_rejects_non_sequential_transfer() -> None:
    with pytest.raises(ValidationError):
        TransferConfig(sequential=False)


def test_mvp_rejects_multiple_workers() -> None:
    with pytest.raises(ValidationError):
        TransferConfig(worker_concurrency=2)
