from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from igp_ride.config import (
    AppConfig,
    DEFAULT_BASE_URL,
    clear_icu_config,
    delete_credentials,
    get_default_config_dir,
    get_default_credentials_file,
    get_default_data_dir,
    get_default_db_file,
    get_default_fit_dir,
    get_default_icu_config_file,
    get_default_session_file,
    save_credentials,
    save_icu_config,
)


class TestAppConfig:
    def test_load_ignores_igp_base_url_env(self, monkeypatch):
        monkeypatch.setenv("IGP_BASE_URL", "https://evil.example")

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_stored_username", return_value=None),
            patch("igp_ride.config._load_password", return_value=None),
        ):
            config = AppConfig.load()

        assert config.base_url == DEFAULT_BASE_URL

    def test_load_reads_credentials_from_file(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch(
                "igp_ride.config.get_default_credentials_file", return_value=cred_file
            ),
            patch("igp_ride.config._load_password", return_value="decrypted-pw"),
            patch("igp_ride.config._read_stored_username", return_value="tester"),
        ):
            config = AppConfig.load()

        assert config.username == "tester"
        assert config.password == "decrypted-pw"

    def test_load_reads_icu_settings_from_environment(self, monkeypatch):
        monkeypatch.setenv("INTERVALS_ICU_API_KEY", "icu-key")

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_stored_username", return_value=None),
            patch("igp_ride.config._load_password", return_value=None),
        ):
            config = AppConfig.load()

        assert config.icu_api_key == "icu-key"

    def test_load_reads_icu_api_key_from_file(self):
        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_stored_username", return_value=None),
            patch("igp_ride.config._load_password", return_value=None),
            patch("igp_ride.config.load_icu_api_key", return_value="stored-key"),
        ):
            config = AppConfig.load()

        assert config.icu_api_key == "stored-key"

    def test_load_prefers_igp_ride_icu_environment(self, monkeypatch):
        monkeypatch.setenv("INTERVALS_ICU_API_KEY", "intervals-key")
        monkeypatch.setenv("IGP_RIDE_ICU_API_KEY", "igp-key")

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_stored_username", return_value=None),
            patch("igp_ride.config._load_password", return_value=None),
        ):
            config = AppConfig.load()

        assert config.icu_api_key == "igp-key"


class TestDefaultPaths:
    def test_default_paths_follow_platform_dirs(self):
        with (
            patch(
                "igp_ride.config.get_config_dir",
                return_value=Path("C:/Users/demo/AppData/Roaming/igp-ride"),
            ),
            patch(
                "igp_ride.config.get_data_dir",
                return_value=Path("C:/Users/demo/AppData/Local/igp-ride"),
            ),
        ):
            assert get_default_config_dir() == Path(
                "C:/Users/demo/AppData/Roaming/igp-ride"
            )
            assert get_default_data_dir() == Path(
                "C:/Users/demo/AppData/Local/igp-ride"
            )
            assert get_default_fit_dir() == Path(
                "C:/Users/demo/AppData/Local/igp-ride/fit"
            )
            assert get_default_session_file() == Path(
                "C:/Users/demo/AppData/Roaming/igp-ride/session.json"
            )
            assert get_default_credentials_file() == Path(
                "C:/Users/demo/AppData/Roaming/igp-ride/credentials.json"
            )
            assert get_default_icu_config_file() == Path(
                "C:/Users/demo/AppData/Roaming/igp-ride/icu.json"
            )
            assert get_default_db_file() == Path(
                "C:/Users/demo/AppData/Local/igp-ride/rides.db"
            )


class TestCredentialStorage:
    def test_save_credentials_writes_encrypted_password(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"

        with (
            patch(
                "igp_ride.config.get_default_credentials_file", return_value=cred_file
            ),
            patch("igp_ride.config.encrypt_value", return_value="ENC_TOKEN"),
        ):
            save_credentials("tester", "secret")

        payload = json.loads(cred_file.read_text(encoding="utf-8"))
        assert payload["username"] == "tester"
        assert payload["password_encrypted"] == "ENC_TOKEN"
        assert "secret" not in cred_file.read_text(encoding="utf-8")

    def test_delete_credentials_removes_file(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"
        cred_file.write_text("{}", encoding="utf-8")

        with patch(
            "igp_ride.config.get_default_credentials_file", return_value=cred_file
        ):
            delete_credentials()

        assert not cred_file.exists()

    def test_delete_credentials_tolerates_missing_file(self, tmp_path: Path):
        cred_file = tmp_path / "credentials.json"

        with patch(
            "igp_ride.config.get_default_credentials_file", return_value=cred_file
        ):
            delete_credentials()


class TestIcuConfigStorage:
    def test_save_icu_config_writes_encrypted_key(self, tmp_path: Path):
        icu_file = tmp_path / "icu.json"

        with (
            patch("igp_ride.config.get_default_icu_config_file", return_value=icu_file),
            patch("igp_ride.config.encrypt_value", return_value="ENC_API_KEY"),
        ):
            saved_path = save_icu_config(api_key="secret")

        assert saved_path == icu_file
        payload = json.loads(icu_file.read_text(encoding="utf-8"))
        assert payload["api_key_encrypted"] == "ENC_API_KEY"
        assert "secret" not in icu_file.read_text(encoding="utf-8")

    def test_clear_icu_config_removes_file(self, tmp_path: Path):
        icu_file = tmp_path / "icu.json"
        icu_file.write_text("{}", encoding="utf-8")

        with patch(
            "igp_ride.config.get_default_icu_config_file", return_value=icu_file
        ):
            clear_icu_config()

        assert not icu_file.exists()

    def test_clear_icu_config_tolerates_missing_file(self, tmp_path: Path):
        icu_file = tmp_path / "icu.json"

        with patch(
            "igp_ride.config.get_default_icu_config_file", return_value=icu_file
        ):
            clear_icu_config()
