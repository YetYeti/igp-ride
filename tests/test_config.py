from __future__ import annotations

from unittest.mock import patch

from keyring.errors import KeyringError

from igp_ride.config import AppConfig, DEFAULT_BASE_URL


class TestAppConfig:
    def test_load_ignores_igp_base_url_env(self, monkeypatch):
        monkeypatch.setenv("IGP_BASE_URL", "https://evil.example")

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_session_username", return_value=None),
            patch("igp_ride.config.keyring.get_password", return_value=None),
        ):
            config = AppConfig.load()

        assert config.base_url == DEFAULT_BASE_URL

    def test_load_tolerates_keyring_errors_when_credentials_not_required(self):
        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_session_username", return_value="tester"),
            patch("igp_ride.config.keyring.get_password", side_effect=KeyringError()),
        ):
            config = AppConfig.load()

        assert config.username == "tester"
        assert config.password == ""
