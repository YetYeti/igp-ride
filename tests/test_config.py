from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from keyring.errors import KeyringError

from igp_ride.config import (
    AppConfig,
    DEFAULT_BASE_URL,
    DEFAULT_ICU_BASE_URL,
    clear_icu_config,
    delete_session_data,
    get_default_config_dir,
    get_default_data_dir,
    get_default_db_file,
    get_default_fit_dir,
    get_default_icu_config_file,
    get_default_session_file,
    load_session_data,
    save_icu_config,
    save_session_data,
)


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

    def test_load_reads_icu_settings_from_environment(self, monkeypatch):
        monkeypatch.setenv("INTERVALS_ICU_API_KEY", "icu-key")
        monkeypatch.setenv("INTERVALS_ICU_ATHLETE_ID", "i123456")

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_session_username", return_value=None),
            patch("igp_ride.config.keyring.get_password", return_value=None),
        ):
            config = AppConfig.load()

        assert config.icu_api_key == "icu-key"
        assert config.icu_athlete_id == "i123456"
        assert config.icu_base_url == DEFAULT_ICU_BASE_URL

    def test_load_reads_icu_settings_from_keyring_and_file(self, tmp_path: Path):
        icu_config_file = tmp_path / "icu.json"
        icu_config_file.write_text(
            '{"athlete_id": "i123456", "base_url": "https://icu.example/api"}',
            encoding="utf-8",
        )

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_session_username", return_value=None),
            patch("igp_ride.config._load_password", return_value=None),
            patch("igp_ride.config.get_default_icu_config_file", return_value=icu_config_file),
            patch("igp_ride.config.load_icu_api_key", return_value="stored-key"),
        ):
            config = AppConfig.load()

        assert config.icu_api_key == "stored-key"
        assert config.icu_athlete_id == "i123456"
        assert config.icu_base_url == "https://icu.example/api"

    def test_load_prefers_igp_ride_icu_environment(self, monkeypatch):
        monkeypatch.setenv("INTERVALS_ICU_API_KEY", "intervals-key")
        monkeypatch.setenv("INTERVALS_ICU_ATHLETE_ID", "i123456")
        monkeypatch.setenv("IGP_RIDE_ICU_API_KEY", "igp-key")
        monkeypatch.setenv("IGP_RIDE_ICU_ATHLETE_ID", "0")
        monkeypatch.setenv("IGP_RIDE_ICU_BASE_URL", "https://icu.example/api")

        with (
            patch("igp_ride.config.ensure_runtime_dirs"),
            patch("igp_ride.config._read_session_username", return_value=None),
            patch("igp_ride.config.keyring.get_password", return_value=None),
        ):
            config = AppConfig.load()

        assert config.icu_api_key == "igp-key"
        assert config.icu_athlete_id == "0"
        assert config.icu_base_url == "https://icu.example/api"


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
            assert get_default_icu_config_file() == Path(
                "C:/Users/demo/AppData/Roaming/igp-ride/icu.json"
            )
            assert get_default_db_file() == Path(
                "C:/Users/demo/AppData/Local/igp-ride/rides.db"
            )


class TestIcuConfigStorage:
    def test_save_icu_config_writes_non_secret_settings_to_file(self, tmp_path: Path):
        icu_config_file = tmp_path / "icu.json"

        with (
            patch("igp_ride.config.get_default_icu_config_file", return_value=icu_config_file),
            patch("igp_ride.config.keyring.set_password") as mock_set_password,
        ):
            saved_path = save_icu_config(
                api_key="secret",
                athlete_id="i123456",
                base_url="https://icu.example/api",
            )

        assert saved_path == icu_config_file
        assert "secret" not in icu_config_file.read_text(encoding="utf-8")
        assert '"athlete_id": "i123456"' in icu_config_file.read_text(encoding="utf-8")
        mock_set_password.assert_called_once()

    def test_clear_icu_config_removes_keyring_secret_and_file(self, tmp_path: Path):
        icu_config_file = tmp_path / "icu.json"
        icu_config_file.write_text("{}", encoding="utf-8")

        with (
            patch("igp_ride.config.get_default_icu_config_file", return_value=icu_config_file),
            patch("igp_ride.config.keyring.delete_password") as mock_delete_password,
        ):
            clear_icu_config()

        assert not icu_config_file.exists()
        mock_delete_password.assert_called_once()


class TestWindowsSessionDataStorage:
    def test_save_session_data_uses_dpapi_protected_file_on_windows(
        self, tmp_path: Path
    ):
        session_data_file = tmp_path / "session_data.json"
        session_payload = (
            b'{"cookies":{"sessionid":"abc"},"authorization":"Bearer token",'
            b'"access_token":"token","refresh_token":"refresh","expires_at":"date"}'
        )

        with (
            patch("igp_ride.config.sys.platform", "win32"),
            patch(
                "igp_ride.config.get_default_session_data_file",
                return_value=session_data_file,
            ),
            patch("igp_ride.config._protect_with_dpapi", return_value=b"encrypted"),
            patch(
                "igp_ride.config._unprotect_with_dpapi",
                return_value=session_payload,
            ),
            patch("igp_ride.config.keyring.set_password") as mock_set_password,
        ):
            save_session_data(
                "tester",
                cookies={"sessionid": "abc"},
                authorization="Bearer token",
                access_token="token",
                refresh_token="refresh",
                expires_at="date",
            )
            payload = load_session_data("tester")

            stored = session_data_file.read_text(encoding="utf-8")
            assert "Bearer token" not in stored
            assert "sessionid" not in stored
            assert payload == {
                "cookies": {"sessionid": "abc"},
                "authorization": "Bearer token",
                "access_token": "token",
                "refresh_token": "refresh",
                "expires_at": "date",
            }
            mock_set_password.assert_not_called()

    def test_load_session_data_accepts_legacy_plain_file_on_windows(
        self, tmp_path: Path
    ):
        session_data_file = tmp_path / "session_data.json"
        session_data_file.write_text(
            '{"cookies":{"sessionid":"abc"},"authorization":"Bearer token"}',
            encoding="utf-8",
        )

        with (
            patch("igp_ride.config.sys.platform", "win32"),
            patch(
                "igp_ride.config.get_default_session_data_file",
                return_value=session_data_file,
            ),
        ):
            payload = load_session_data("tester")

        assert payload == {
            "cookies": {"sessionid": "abc"},
            "authorization": "Bearer token",
        }

    def test_restrict_session_data_permissions_uses_icacls_on_windows(
        self, tmp_path: Path
    ):
        from igp_ride.config import _restrict_session_data_file_permissions

        session_data_file = tmp_path / "session_data.json"
        session_data_file.write_text("{}", encoding="utf-8")

        with (
            patch("igp_ride.config.sys.platform", "win32"),
            patch("igp_ride.config.os.name", "nt"),
            patch("igp_ride.config._current_windows_identity", return_value="USER\\me"),
            patch("igp_ride.config.subprocess.run") as mock_run,
        ):
            _restrict_session_data_file_permissions(session_data_file)

        mock_run.assert_called_once_with(
            [
                "icacls",
                str(session_data_file),
                "/inheritance:r",
                "/grant:r",
                "USER\\me:(R,W)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_delete_session_data_uses_file_on_windows(self, tmp_path: Path):
        session_data_file = tmp_path / "session_data.json"
        session_data_file.write_text("{}", encoding="utf-8")

        with (
            patch("igp_ride.config.sys.platform", "win32"),
            patch(
                "igp_ride.config.get_default_session_data_file",
                return_value=session_data_file,
            ),
            patch("igp_ride.config.keyring.delete_password") as mock_delete_password,
        ):
            delete_session_data("tester")

        assert not session_data_file.exists()
        mock_delete_password.assert_not_called()
