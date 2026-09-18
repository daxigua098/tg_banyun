from __future__ import annotations

import pytest

from app.config import ManagementBotConfig, TransferConfig


def test_mvp_rejects_non_sequential_transfer() -> None:
    with pytest.raises(ValueError):
        TransferConfig(sequential=False)


def test_mvp_rejects_multiple_workers() -> None:
    with pytest.raises(ValueError):
        TransferConfig(worker_concurrency=2)


def test_disabled_management_bot_does_not_require_credentials() -> None:
    ManagementBotConfig().validate_ready()


@pytest.mark.parametrize(
    "config",
    [
        ManagementBotConfig(enabled=True),
        ManagementBotConfig(enabled=True, token="token"),
        ManagementBotConfig(enabled=True, admin_user_ids=[42]),
    ],
)
def test_enabled_management_bot_requires_token_and_admins(
    config: ManagementBotConfig,
) -> None:
    with pytest.raises(ValueError):
        config.validate_ready()

def test_load_config_parses_management_bot_environment(monkeypatch, tmp_path) -> None:
    from app.config import load_config

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
telegram:
  api_id: 1
  api_hash: hash
  phone: '+10000000000'
management_bot:
  enabled: true
  token: ''
  admin_user_ids: []
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TG_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TG_ADMIN_IDS", "10, 20")

    config = load_config(config_path)

    assert config.management_bot.token == "bot-token"
    assert config.management_bot.admin_user_ids == [10, 20]
