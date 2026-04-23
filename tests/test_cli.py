from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igp_ride.cli import cmd_list, cmd_show, cmd_stats, cmd_update, main
from igp_ride.config import AppConfig, ConfigurationError
from igp_ride.models import Activity, PeriodStats, SyncSummary
from igp_ride.service import SyncProgress


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

    def test_main_blocks_daemon_start_when_management_is_unsupported(self, capsys):
        with patch("igp_ride.cli.is_daemon_management_supported", return_value=False):
            exit_code = main(["daemon", "start"])

        captured = capsys.readouterr()
        assert exit_code == 9
        assert "== Daemon Start ==" in captured.err
        assert "only supported on macOS" in captured.err

    def test_main_allows_daemon_run_once_when_management_is_unsupported(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        state = {
            "last_status": "ok",
            "last_hook_triggered": False,
            "last_remote_fetched": 1,
            "last_new_activities": 0,
            "last_updated_activities": 0,
            "last_activities_skipped": 1,
            "last_fit_files_failed": 0,
        }

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.run_daemon_loop", return_value=0),
            patch("igp_ride.cli.get_daemon_status", return_value=state),
            patch("igp_ride.cli.is_daemon_management_supported", return_value=False),
        ):
            exit_code = main(["daemon", "run", "--once"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== Daemon Run ==" in captured.out
        assert "Mode: foreground-once" in captured.out


class TestUpdateOutput:
    def test_plain_progress_is_compact(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = FakeUpdateService()

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_update(False, "plain", False)

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
            "Summary: remote=57 new=1 updated=3 skipped=53 fit_failed=0" in captured.out
        )
        assert "Next: igp-ride list" in captured.out


class TestListOutput:
    def test_main_passes_list_sort_options(self):
        with patch("igp_ride.cli.cmd_list", return_value=0) as cmd_list_mock:
            exit_code = main(["list", "--sort", "distance", "--asc", "--limit", "5"])

        assert exit_code == 0
        cmd_list_mock.assert_called_once_with(5, False, "distance", descending=False)

    def test_empty_list_uses_count_and_tip(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        service = MagicMock()
        service.list_activities.return_value = []

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_list(limit=None, do_update=False)

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
            exit_code = cmd_list(limit=None, do_update=False)

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
            exit_code = cmd_list(limit=20, do_update=False, sort_by="distance")

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
            exit_code = cmd_list(limit=None, do_update=False)

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
            exit_code = cmd_show("last", False)

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


class TestStatsOutput:
    def test_stats_uses_summary_and_table(self, tmp_path: Path, capsys):
        config = _make_config(tmp_path)
        stats = [
            PeriodStats(
                period="2026-03",
                count=7,
                total_distance=239100,
                total_moving_time=30420,
                avg_speed=7.8611111,
                avg_power=214,
                total_ascent=2220,
            )
        ]
        service = MagicMock()
        service.get_stats.return_value = stats

        with (
            patch("igp_ride.cli.AppConfig.load", return_value=config),
            patch("igp_ride.cli.RideSyncService", return_value=service),
        ):
            exit_code = cmd_stats("month", None, None, False)

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "== Ride Statistics ==" in captured.out
        assert "Periods: 1" in captured.out
        assert "Rides: 7" in captured.out
        assert "Distance: 239.1 km" in captured.out
        assert "Time: 8.4 h" in captured.out
        assert "Ascent: 2,220 m" in captured.out
        assert "PERIOD   " in captured.out
        assert "CNT" in captured.out
        assert "AVG_SPD" in captured.out
        assert "ASCENT" in captured.out
        assert "2026-03" in captured.out
        assert "  7" in captured.out
        assert "  8:27" in captured.out
