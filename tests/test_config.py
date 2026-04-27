from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from keyring.errors import KeyringError

from igp_ride.config import (
    AppConfig,
    DEFAULT_BASE_URL,
    delete_session_data,
    get_default_config_dir,
    get_default_data_dir,
    get_default_db_file,
    get_default_fit_dir,
    get_default_session_file,
    load_session_data,
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
            assert get_default_db_file() == Path(
                "C:/Users/demo/AppData/Local/igp-ride/rides.db"
            )


class TestWindowsSessionDataStorage:
    def test_save_session_data_uses_dpapi_protected_file_on_windows(
        self, tmp_path: Path
    ):
        session_data_file = tmp_path / "session_data.json"
        session_payload = b'{"cookies":{"sessionid":"abc"},"authorization":"Bearer token"}'

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
            )
            payload = load_session_data("tester")

            stored = session_data_file.read_text(encoding="utf-8")
            assert "Bearer token" not in stored
            assert "sessionid" not in stored
            assert payload == {
                "cookies": {"sessionid": "abc"},
                "authorization": "Bearer token",
            }
            mock_set_password.assert_not_called()

    def test_load_session_data_accepts_legacy_plain_file_on_windows(self, tmp_path: Path):
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
