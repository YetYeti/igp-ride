from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igp_ride.cli import cmd_icu_sync, cmd_list, cmd_show, cmd_update, main
from igp_ride.config import AppConfig, ConfigurationError
from igp_ride.models import Activity, SyncSummary
from igp_ride.service import IcuSyncSummary, SyncProgress


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
    def test_main_prints_version(self, capsys):
        with patch("igp_ride.cli._get_cli_version", return_value="0.1.1"):
            with pytest.raises(SystemExit) as exc:
                main(["--version"])

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "igp-ride 0.1.1"

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
        assert "Progress: stage=fetching" in captured.out
        assert "Progress: done=12 total=57 percent=21" in captured.out
        assert "Progress: done=57 total=57 percent=100" in captured.out
        assert "new=1 updated=0" not in captured.out
        assert "Result: success" in captured.out
        assert "Mode: incremental" in captured.out
        assert (
            "Summary: remote=57 new=1 updated=4 skipped=53 fit_failed=0" in captured.out
        )
        assert "Next: igp-ride list" in captured.out


class TestLoginLogoutOutput:
    def test_main_routes_login_without_options(self):
        with patch("igp_ride.cli.cmd_login", return_value=0) as cmd:
            exit_code = main(["login"])

        assert exit_code == 0
        cmd.assert_called_once_with()

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
        assert "This will clear local IGPSPORT credentials and session." in captured.out
        assert "Result: cancelled" in captured.out

    def test_main_routes_logout_yes(self):
        with patch("igp_ride.cli.cmd_logout", return_value=0) as cmd:
            exit_code = main(["logout", "--yes"])

        assert exit_code == 0
        cmd.assert_called_once_with(True)


class TestIcuOutput:
    def test_main_routes_icu_login_options(self):
        with patch("igp_ride.cli.cmd_icu_login", return_value=0) as cmd:
            exit_code = main(
                [
                    "icu",
                    "login",
                    "--api-key",
                    "secret",
                ]
            )

        assert exit_code == 0
        cmd.assert_called_once_with("secret")

    def test_icu_login_saves_config_without_printing_key(self, tmp_path: Path, capsys):
        config_file = tmp_path / "icu.json"

        with patch("igp_ride.cli.save_icu_config", return_value=config_file) as save:
            from igp_ride.cli import cmd_icu_login

            exit_code = cmd_icu_login("secret")

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
        assert "This will remove the saved Intervals.icu API key." in captured.out
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
            icu_athlete_id="i123456",
            icu_base_url="https://icu.example/api",
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
        MockClient.assert_called_once_with(
            api_key="secret",
            athlete_id="i123456",
            base_url="https://icu.example/api",
        )
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
                    "--since",
                    "2026-05-01",
                    "--retry-failed",
                    "--dry-run",
                ]
            )

        assert exit_code == 0
        assert cmd.call_args.args[0].isoformat() == "2026-05-01"
        assert cmd.call_args.args[1:] == (True, True)

    def test_icu_sync_prints_summary(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.sync_icu.return_value = IcuSyncSummary(
            candidates=3,
            uploaded=2,
            already_remote=1,
        )

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_icu_sync(None, False, False)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== ICU Sync ==" in captured.out
        assert "Mode: upload" in captured.out
        assert (
            "Summary: candidates=3 uploaded=2 already_remote=1 skipped=0 "
            "failed=0 dry_run=no"
        ) in captured.out
        service.sync_icu.assert_called_once_with(
            since=None,
            include_failed=False,
            dry_run=False,
        )
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
            exit_code = cmd_icu_sync(None, False, True)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Mode: dry-run" in captured.out
        assert "dry_run=yes" in captured.out
        assert "Next: igp-ride icu sync" in captured.out


class TestListOutput:
    def test_main_passes_list_sort_options(self):
        with patch("igp_ride.cli.cmd_list", return_value=0) as cmd_list_mock:
            exit_code = main(["list", "--sort", "distance", "--asc", "--limit", "5"])

        assert exit_code == 0
        cmd_list_mock.assert_called_once_with(5, "distance", descending=False)

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
            exit_code = cmd_list(limit=20, sort_by="distance")

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Limit: 20" in captured.out
        assert "Summary: shown=" not in captured.out
        assert "Count:" not in captured.out
        service.list_activities.assert_called_once_with(
            limit=20,
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
