from __future__ import annotations

import json
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igp_ride.cli import cmd_icu_sync, cmd_list, cmd_show, cmd_update, main
from igp_ride.config import AppConfig, ConfigurationError
from igp_ride.models import Activity, SyncSummary
from igp_ride.service import IcuSyncProgress, IcuSyncSummary, ResetResult, SyncProgress


def _make_config(tmp_path: Path) -> AppConfig:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    return AppConfig(
        username="tester",
        password="secret",
        data_dir=data_dir,
        fit_dir=data_dir / "fit",
        session_file=config_dir / "session.json",
        db_path=data_dir / "rides.db",
    )


def _make_activity() -> Activity:
    return Activity(
        ride_id=123456,
        member_id=1,
        title="户外骑行",
        sport="cycling",
        sub_sport="road",
        start_time=datetime(2026, 3, 31, 7, 12, 8, tzinfo=UTC),
        total_distance=45200,
        total_moving_time=5520,
        total_elapsed_time=6000,
        total_ascent=420,
        total_descent=418,
        avg_power=215,
        max_power=612,
        normalized_power=228,
        intensity_factor=0.81,
        training_stress_score=92.4,
        avg_heart_rate=148,
        max_heart_rate=176,
        avg_cadence=86,
        max_cadence=112,
        avg_speed=8.1666667,
        max_speed=14.2222222,
        total_calories=1024,
    )


class FakeUpdateService:
    def __init__(self):
        self.closed = False

    def sync(
        self,
        force_full: bool = False,
        progress_callback=None,
    ) -> SyncSummary:
        assert force_full is False
        assert progress_callback is not None
        progress_callback(SyncProgress(stage="fetching", done=0, total=0))
        progress_callback(
            SyncProgress(
                stage="processing",
                done=12,
                total=57,
                new_activities=1,
                updated_activities=0,
                activities_skipped=11,
                fit_files_failed=0,
            )
        )
        progress_callback(
            SyncProgress(
                stage="processing",
                done=57,
                total=57,
                new_activities=1,
                updated_activities=3,
                activities_skipped=53,
                fit_files_failed=0,
            )
        )
        return SyncSummary(
            remote_fetched=57,
            new_activities=1,
            updated_activities=3,
            activities_skipped=53,
            fit_files_failed=0,
        )

    def repair(self, progress_callback=None) -> SyncSummary:
        assert progress_callback is not None
        return SyncSummary(updated_activities=1)

    def close(self) -> None:
        self.closed = True


class TestMainOutput:
    def test_main_configures_non_tty_stderr_line_buffering(self):
        stderr = MagicMock()
        stderr.isatty.return_value = False

        with (
            patch("sys.stderr", stderr),
            patch("igp_ride.cli.cmd_list", return_value=0),
        ):
            exit_code = main(["list"])

        assert exit_code == 0
        stderr.reconfigure.assert_called_once_with(line_buffering=True)

    def test_main_prints_version(self, capsys):
        with patch("igp_ride.cli._get_cli_version", return_value="0.1.1"):
            with pytest.raises(SystemExit) as exc:
                main(["--version"])

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "igp-ride 0.1.1"

    def test_main_without_command_prints_quick_start(self, capsys):
        exit_code = main([])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== igp-ride ==" in captured.out
        assert "Quick start:" in captured.out
        assert "igp-ride update" in captured.out
        assert captured.err == ""

    def test_main_without_command_can_output_json(self, capsys):
        exit_code = main(["--format", "json"])

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert exit_code == 0
        assert payload["command"] == "welcome"
        assert payload["result"] == "success"

    def test_main_formats_configuration_error(self, capsys):
        with patch(
            "igp_ride.cli.cmd_update",
            side_effect=ConfigurationError("Missing credentials."),
        ):
            exit_code = main(["update"])

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "== Update ==" in captured.err
        assert "Error: Missing credentials." in captured.err
        assert "Tip: Run igp-ride login first" in captured.err


class TestUpdateOutput:
    def test_plain_progress_is_compact(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = FakeUpdateService()

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_update(False)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert service.closed is True
        assert "== Update ==" in captured.out
        assert "Progress: stage=fetching" in captured.err
        assert "Progress: done=12 total=57 percent=21" in captured.err
        assert "Progress: done=57 total=57 percent=100" in captured.err
        assert "new=1 updated=0" not in captured.out
        assert "Result: success" in captured.out
        assert "Mode: incremental" in captured.out
        assert (
            "Summary: remote=57 new=1 updated=4 skipped=53 fit_failed=0" in captured.out
        )
        assert "Next: igp-ride list" in captured.out

    def test_json_output_is_single_stdout_payload(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = FakeUpdateService()

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = main(["--format", "json", "update"])

        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["command"] == "update"
        assert payload["result"] == "success"
        assert payload["summary"] == {
            "remote": 57,
            "new": 1,
            "updated": 4,
            "skipped": 53,
            "fit_failed": 0,
        }
        assert "== Update ==" not in captured.out


class TestLoginLogoutOutput:
    def test_main_routes_login_without_options(self):
        with patch("igp_ride.cli.cmd_login", return_value=0) as cmd:
            exit_code = main(["login"])

        assert exit_code == 0
        cmd.assert_called_once_with(None, False)

    def test_main_routes_login_stdin_options(self):
        with patch("igp_ride.cli.cmd_login", return_value=0) as cmd:
            exit_code = main(["login", "--username", "tester", "--password-stdin"])

        assert exit_code == 0
        cmd.assert_called_once_with("tester", True)

    def test_login_no_input_requires_missing_credentials(self, tmp_path: Path, capsys):
        config = AppConfig(
            username="",
            password="",
            data_dir=tmp_path / "data",
            fit_dir=tmp_path / "data" / "fit",
            session_file=tmp_path / "config" / "session.json",
            db_path=tmp_path / "data" / "rides.db",
        )

        with patch("igp_ride.cli.AppConfig.load", return_value=config):
            exit_code = main(["--no-input", "login"])

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "Missing username" in captured.err

    def test_login_reads_password_from_stdin(self, tmp_path: Path, capsys):
        from igp_ride.cli import cmd_login

        config = _make_config(tmp_path)
        service = MagicMock()
        service.login.return_value = ("tester", config.session_file)

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
            patch("sys.stdin", StringIO("secret-from-stdin\n")),
        ):
            exit_code = cmd_login("tester", True)

        captured = capsys.readouterr()
        assert exit_code == 0
        service.login.assert_called_once_with(
            username="tester",
            password="secret-from-stdin",
        )
        assert "secret-from-stdin" not in captured.out

    def test_logout_removes_credentials_with_yes(self, tmp_path: Path, capsys):
        from igp_ride.cli import cmd_logout

        config = _make_config(tmp_path)
        service = MagicMock()

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_logout(yes=True)

        captured = capsys.readouterr()
        assert exit_code == 0
        service.logout.assert_called_once_with()
        service.close.assert_called_once_with()
        assert "== Logout ==" in captured.out
        assert "Result: success" in captured.out

    def test_logout_requires_confirmation(self, capsys):
        from igp_ride.cli import cmd_logout

        with (
            patch("igp_ride.cli.AppConfig.load") as load,
            patch("builtins.input", return_value="no"),
        ):
            exit_code = cmd_logout(yes=False)

        captured = capsys.readouterr()
        assert exit_code == 0
        load.assert_not_called()
        assert "This will clear local IGPSPORT credentials and session." in captured.err
        assert "Result: cancelled" in captured.out

    def test_main_routes_logout_yes(self):
        with patch("igp_ride.cli.cmd_logout", return_value=0) as cmd:
            exit_code = main(["logout", "--yes"])

        assert exit_code == 0
        cmd.assert_called_once_with(True)


class TestStatusOutput:
    def test_status_without_credentials_prints_tip(self, tmp_path: Path, capsys):
        from igp_ride.cli import cmd_status

        config = AppConfig(
            username="",
            password="",
            data_dir=tmp_path / "data",
            fit_dir=tmp_path / "data" / "fit",
            session_file=tmp_path / "config" / "session.json",
            db_path=tmp_path / "data" / "rides.db",
        )

        with patch("igp_ride.cli.AppConfig.load", return_value=config):
            exit_code = cmd_status()

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== Status ==" in captured.out
        assert "Credentials: no" in captured.out
        assert "Session: no" in captured.out
        assert "Authenticated: no" in captured.out
        assert "Tip: Run igp-ride login" in captured.out

    def test_status_checks_igpsport_session(self, tmp_path: Path, capsys):
        from igp_ride.cli import cmd_status

        config = _make_config(tmp_path)
        config.session_file.parent.mkdir(parents=True)
        config.session_file.write_text("{}", encoding="utf-8")
        service = MagicMock()
        service.client.get_activity_page.return_value = ([], 0)

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_status()

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Credentials: yes" in captured.out
        assert "Session: yes" in captured.out
        assert "Authenticated: yes" in captured.out
        service.client.get_activity_page.assert_called_once_with(page=1, page_size=1)
        service.close.assert_called_once_with()

    def test_status_json_without_credentials(self, tmp_path: Path, capsys):
        config = AppConfig(
            username="",
            password="",
            data_dir=tmp_path / "data",
            fit_dir=tmp_path / "data" / "fit",
            session_file=tmp_path / "config" / "session.json",
            db_path=tmp_path / "data" / "rides.db",
        )

        with patch("igp_ride.cli.AppConfig.load", return_value=config):
            exit_code = main(["--format", "json", "status"])

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["command"] == "status"
        assert payload["credentials"] is False
        assert payload["authenticated"] is False


class TestIcuOutput:
    def test_main_routes_icu_login_options(self):
        with patch("igp_ride.cli.cmd_icu_login", return_value=0) as cmd:
            exit_code = main(
                [
                    "icu",
                    "login",
                    "--api-key-stdin",
                ]
            )

        assert exit_code == 0
        cmd.assert_called_once_with(True)

    def test_icu_login_saves_config_without_printing_key(self, tmp_path: Path, capsys):
        config_file = tmp_path / "icu.json"

        with (
            patch("igp_ride.cli.save_icu_config", return_value=config_file) as save,
            patch("sys.stdin", StringIO("secret\n")),
        ):
            from igp_ride.cli import cmd_icu_login

            exit_code = cmd_icu_login(api_key_stdin=True)

        captured = capsys.readouterr()
        assert exit_code == 0
        save.assert_called_once_with(api_key="secret")
        assert "secret" not in captured.out
        assert "== ICU Login ==" in captured.out
        assert "Next: igp-ride icu status" in captured.out

    def test_icu_logout_removes_config(self, capsys):
        from igp_ride.cli import cmd_icu_logout

        with patch("igp_ride.cli.clear_icu_config") as clear:
            exit_code = cmd_icu_logout(yes=True)

        captured = capsys.readouterr()
        assert exit_code == 0
        clear.assert_called_once()
        assert "== ICU Logout ==" in captured.out
        assert "Logged In: no" in captured.out

    def test_icu_logout_requires_confirmation(self, capsys):
        from igp_ride.cli import cmd_icu_logout

        with (
            patch("igp_ride.cli.clear_icu_config") as clear,
            patch("builtins.input", return_value="no"),
        ):
            exit_code = cmd_icu_logout(yes=False)

        captured = capsys.readouterr()
        assert exit_code == 0
        clear.assert_not_called()
        assert "This will remove the saved Intervals.icu API key." in captured.err
        assert "Result: cancelled" in captured.out

    def test_main_routes_icu_logout_yes(self):
        with patch("igp_ride.cli.cmd_icu_logout", return_value=0) as cmd:
            exit_code = main(["icu", "logout", "--yes"])

        assert exit_code == 0
        cmd.assert_called_once_with(True)

    def test_icu_status_without_key_prints_not_configured(self, tmp_path: Path, capsys):
        from igp_ride.cli import cmd_icu_status

        config = _make_config(tmp_path)

        with patch("igp_ride.cli.AppConfig.load", return_value=config):
            exit_code = cmd_icu_status()

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== ICU Status ==" in captured.out
        assert "Logged In: no" in captured.out
        assert "Authenticated: no" in captured.out
        assert "Tip: Run igp-ride icu login" in captured.out

    def test_icu_status_checks_remote_athlete(self, tmp_path: Path, capsys):
        from igp_ride.cli import cmd_icu_status

        config = _make_config(tmp_path)
        config = AppConfig(
            username=config.username,
            password=config.password,
            data_dir=config.data_dir,
            fit_dir=config.fit_dir,
            session_file=config.session_file,
            db_path=config.db_path,
            icu_api_key="secret",
        )

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.IntervalsIcuClient") as MockClient,
        ):
            mock_client = MockClient.return_value
            mock_client.get_athlete.return_value = {
                "id": "i123456",
                "name": "Tester",
            }
            exit_code = cmd_icu_status()

        captured = capsys.readouterr()
        assert exit_code == 0
        MockClient.assert_called_once_with(api_key="secret")
        assert "Logged In: yes" in captured.out
        assert "Authenticated: yes" in captured.out
        assert "Remote Athlete ID: i123456" in captured.out
        assert "Name: Tester" in captured.out
        mock_client.close.assert_called_once()

    def test_main_routes_icu_sync_options(self):
        with patch("igp_ride.cli.cmd_icu_sync", return_value=0) as cmd:
            exit_code = main(
                [
                    "icu",
                    "sync",
                    "--dry-run",
                    "--force",
                ]
            )

        assert exit_code == 0
        cmd.assert_called_once_with(True, force=True)

    def test_icu_sync_prints_summary(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()

        def sync_icu(*, dry_run, force, progress_callback):
            assert dry_run is False
            assert force is False
            assert progress_callback is not None
            progress_callback(IcuSyncProgress(done=0, total=3))
            progress_callback(IcuSyncProgress(done=1, total=3, uploaded=1))
            progress_callback(
                IcuSyncProgress(done=3, total=3, uploaded=2, already_remote=1)
            )
            return IcuSyncSummary(
                candidates=3,
                uploaded=2,
                already_remote=1,
            )

        service.sync_icu.side_effect = sync_icu

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_icu_sync(False)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== ICU Sync ==" in captured.out
        assert "Mode: upload" in captured.out
        assert "Force: no" in captured.out
        assert (
            "Summary: candidates=3 uploaded=2 already_remote=1 skipped=0 "
            "failed=0 dry_run=no"
        ) in captured.out
        assert "Progress: done=0 total=3 percent=0" in captured.err
        assert "Progress: done=1 total=3 percent=33" in captured.err
        assert "Progress: done=3 total=3 percent=100" in captured.err
        assert service.close.called

    def test_icu_sync_dry_run_prints_next_command(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.sync_icu.return_value = IcuSyncSummary(
            candidates=1,
            skipped=1,
            dry_run=True,
        )

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_icu_sync(True)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Mode: dry-run" in captured.out
        assert "Force: no" in captured.out
        assert "dry_run=yes" in captured.out
        assert "Next: igp-ride icu sync" in captured.out
        service.sync_icu.assert_called_once()
        assert service.sync_icu.call_args.kwargs["dry_run"] is True
        assert service.sync_icu.call_args.kwargs["progress_callback"] is not None

    def test_icu_status_json_without_key(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)

        with patch("igp_ride.cli.AppConfig.load", return_value=config):
            exit_code = main(["--format", "json", "icu", "status"])

        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["command"] == "icu.status"
        assert payload["logged_in"] is False
        assert payload["authenticated"] is False
        assert captured.err == ""

    def test_icu_sync_json(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.sync_icu.return_value = IcuSyncSummary(
            candidates=1,
            skipped=1,
            dry_run=True,
        )

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = main(["--format", "json", "icu", "sync", "--dry-run"])

        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["command"] == "icu.sync"
        assert payload["mode"] == "dry-run"
        assert payload["force"] is False
        assert payload["summary"]["dry_run"] is True
        assert captured.err == ""
        assert service.sync_icu.call_args.kwargs["progress_callback"] is None


class TestListOutput:
    def test_main_passes_list_sort_options(self):
        with patch("igp_ride.cli.cmd_list", return_value=0) as cmd_list_mock:
            exit_code = main(["list", "--sort", "distance", "--asc", "--limit", "5"])

        assert exit_code == 0
        cmd_list_mock.assert_called_once_with(
            5,
            "distance",
            since=None,
            descending=False,
        )

    def test_main_passes_list_since_option(self):
        with patch("igp_ride.cli.cmd_list", return_value=0) as cmd_list_mock:
            exit_code = main(["list", "--since", "2026-03-01"])

        assert exit_code == 0
        cmd_list_mock.assert_called_once_with(
            None,
            "date",
            since=date(2026, 3, 1),
            descending=True,
        )

    def test_main_rejects_invalid_list_since(self, capsys):
        exit_code = main(["list", "--since", "7d"])

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "Error: --since must be a date in YYYY-MM-DD format." in captured.err

    def test_empty_list_uses_count_and_tip(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.list_activities.return_value = []

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_list(limit=None)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== Activity List ==" in captured.out
        assert "Count: 0" in captured.out
        assert (
            "Tip: Run igp-ride update to download activities from IGPSPORT"
            in captured.out
        )

    def test_list_uses_compact_time_column(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        long_ride = _make_activity()
        short_ride = Activity(
            ride_id=123455,
            member_id=1,
            title="室内骑行",
            sport="cycling",
            sub_sport="indoor",
            start_time=datetime(2026, 3, 29, 8, 0, 0, tzinfo=UTC),
            total_distance=32800,
            total_moving_time=3120,
            total_elapsed_time=3300,
            total_ascent=180,
            avg_speed=9.1111111,
        )
        service = MagicMock()
        service.list_activities.return_value = [long_ride, short_ride]

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_list(limit=None)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "TIME" in captured.out
        assert "1:32" in captured.out
        assert " 52 " in captured.out
        assert "Summary: shown=" not in captured.out
        assert "Limit:" not in captured.out

    def test_list_shows_limit_without_summary(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.list_activities.return_value = [_make_activity()]

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_list(
                limit=20,
                sort_by="distance",
                since=date(2026, 3, 1),
            )

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Limit: 20" in captured.out
        assert "Since: 2026-03-01" in captured.out
        assert "Summary: shown=" not in captured.out
        assert "Count:" not in captured.out
        service.list_activities.assert_called_once_with(
            limit=20,
            since=date(2026, 3, 1),
            sort_by="distance",
            descending=True,
        )

    def test_list_aligns_elevation_column_for_thousands(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        first = _make_activity()
        first.total_ascent = 1110
        second = Activity(
            ride_id=123455,
            member_id=1,
            title="室内骑行",
            sport="cycling",
            sub_sport="indoor",
            start_time=datetime(2026, 3, 29, 8, 0, 0, tzinfo=UTC),
            total_distance=32800,
            total_moving_time=3120,
            total_elapsed_time=3300,
            total_ascent=570,
            avg_speed=9.1111111,
            avg_power=155,
        )
        service = MagicMock()
        service.list_activities.return_value = [first, second]

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_list(limit=None)

        lines = capsys.readouterr().out.splitlines()
        assert exit_code == 0
        first_row = next(line for line in lines if line.startswith("123456"))
        second_row = next(line for line in lines if line.startswith("123455"))
        assert "1,110 m" in first_row
        assert "570 m" in second_row
        assert first_row.index("215 W") == second_row.index("155 W")

    def test_display_padding_uses_chinese_display_width(self):
        from igp_ride.cli import _display_ljust, _display_rjust, _display_width

        assert _display_width("户外") == 4
        assert _display_width(_display_ljust("户外", 6)) == 6
        assert _display_width(_display_rjust("户外", 6)) == 6

    def test_list_json_outputs_activities(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.list_activities.return_value = [_make_activity()]

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = main(["--format", "json", "list", "--limit", "1"])

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["command"] == "list"
        assert payload["since"] is None
        assert payload["count"] == 1
        assert payload["activities"][0]["ride_id"] == 123456
        assert payload["activities"][0]["distance_m"] == 45200


class TestShowOutput:
    def test_show_last_uses_structured_fields(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        activity = _make_activity()
        service = MagicMock()
        service.get_latest_activity.return_value = activity

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_show("last")

        captured = capsys.readouterr()
        assert activity.start_time is not None
        expected_start = activity.start_time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        assert exit_code == 0
        assert "== Activity Details ==" in captured.out
        assert "ID: 123456" in captured.out
        assert f"Start Time: {expected_start}" in captured.out
        assert "Distance: 45.20 km" in captured.out
        assert "Moving / Elapsed: 1 h 32 m / 1 h 40 m" in captured.out
        assert "Ascent / Descent: 420 m / 418 m" in captured.out
        assert (
            "Power: 215 W | max 612 W | NP 228 W | IF 0.81 | TSS 92.4" in captured.out
        )
        assert "Heart Rate: 148 bpm | max 176 bpm" in captured.out
        assert "Cadence: 86 rpm | max 112 rpm" in captured.out
        assert "Speed: 29.4 km/h | max 51.2 km/h" in captured.out
        assert "Calories: 1,024 kcal" in captured.out

    def test_show_json_outputs_activity(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        activity = _make_activity()
        service = MagicMock()
        service.get_latest_activity.return_value = activity

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = main(["--format", "json", "show", "last"])

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["command"] == "show"
        assert payload["activity"]["ride_id"] == 123456
        assert payload["activity"]["avg_heart_rate_bpm"] == 148

    def test_show_rejects_non_numeric_id(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = main(["show", "abc"])

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "Error: Activity ID must be a number or 'last'." in captured.err
        service.show_activity.assert_not_called()
        service.close.assert_called_once_with()


class TestResetOutput:
    def test_reset_json_outputs_summary(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.reset.return_value = [
            ResetResult(path=config.data_dir, status="deleted"),
            ResetResult(path=config.session_file.parent, status="not_found"),
        ]

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = main(["--format", "json", "reset", "--yes"])

        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["command"] == "reset"
        assert payload["summary"] == {
            "deleted": 1,
            "not_found": 1,
            "failed": 0,
        }
