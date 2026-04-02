from __future__ import annotations

import json
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from igp_ride.config import AppConfig
from igp_ride.cli import cmd_daemon_status
from igp_ride.daemon import (
    CycleResult,
    DaemonPaths,
    parse_interval_spec,
    run_daemon_loop,
    run_sync_cycle,
    start_daemon_process,
    stop_daemon_process,
)
from igp_ride.models import SyncSummary


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


def _make_paths(tmp_path: Path) -> DaemonPaths:
    return DaemonPaths(
        pid_file=tmp_path / "daemon.pid",
        state_file=tmp_path / "daemon_state.json",
        log_file=tmp_path / "daemon.log",
    )


class FakeService:
    def __init__(self, summary: SyncSummary):
        self.summary = summary
        self.closed = False

    def sync(self, force_full: bool = False) -> SyncSummary:
        assert force_full is False
        return self.summary

    def close(self) -> None:
        self.closed = True


class TestParseIntervalSpec:
    def test_accepts_minutes_suffix(self):
        assert parse_interval_spec("30m") == 1800

    def test_accepts_hours_suffix(self):
        assert parse_interval_spec("2h") == 7200

    def test_plain_number_defaults_to_minutes(self):
        assert parse_interval_spec("15") == 900

    def test_rejects_zero(self):
        with pytest.raises(ValueError):
            parse_interval_spec("0m")

    def test_rejects_unknown_suffix(self):
        with pytest.raises(ValueError):
            parse_interval_spec("5d")


class TestRunSyncCycle:
    def test_triggers_hook_when_new_activities_exist(self, tmp_path: Path):
        config = _make_config(tmp_path)
        service = FakeService(SyncSummary(remote_fetched=2, new_activities=2))

        with patch("igp_ride.daemon.subprocess.run") as mock_run:
            result = run_sync_cycle(
                config,
                interval_seconds=1800,
                hook_command="echo hook",
                service_factory=lambda _config: service,
            )

        assert isinstance(result, CycleResult)
        assert result.hook_triggered is True
        assert service.closed is True
        env = mock_run.call_args.kwargs["env"]
        assert env["IGP_RIDE_NEW_ACTIVITIES"] == "2"
        assert env["IGP_RIDE_INTERVAL_SECONDS"] == "1800"

    def test_skips_hook_when_no_new_activities(self, tmp_path: Path):
        config = _make_config(tmp_path)
        service = FakeService(SyncSummary(remote_fetched=3, new_activities=0))

        with patch("igp_ride.daemon.subprocess.run") as mock_run:
            result = run_sync_cycle(
                config,
                interval_seconds=1800,
                hook_command="echo hook",
                service_factory=lambda _config: service,
            )

        assert result.hook_triggered is False
        assert service.closed is True
        mock_run.assert_not_called()


class TestStartAndStopDaemonProcess:
    def test_start_daemon_process_writes_pid_and_state(self, tmp_path: Path):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)
        process = MagicMock()
        process.pid = 4321
        process.poll.return_value = None

        with (
            patch("igp_ride.daemon.get_daemon_paths", return_value=paths),
            patch(
                "igp_ride.daemon.subprocess.Popen", return_value=process
            ) as mock_popen,
            patch("igp_ride.daemon.time.sleep"),
        ):
            pid, returned_paths = start_daemon_process(
                config,
                interval_spec="30m",
                hook_command="echo hook",
            )

        assert pid == 4321
        assert returned_paths == paths
        assert paths.pid_file.read_text(encoding="utf-8").strip() == "4321"
        state = json.loads(paths.state_file.read_text(encoding="utf-8"))
        assert state["pid"] == 4321
        assert state["interval_seconds"] == 1800
        assert state["hook_command"] == "echo hook"
        command = mock_popen.call_args.args[0]
        assert command == [
            sys.executable,
            "-m",
            "igp_ride.cli",
            "daemon",
            "run",
            "--interval",
            "30m",
            "--hook",
            "echo hook",
        ]

    def test_stop_daemon_process_sends_sigterm_and_cleans_pid(self, tmp_path: Path):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)
        paths.pid_file.write_text("999\n", encoding="utf-8")
        paths.state_file.write_text("{}", encoding="utf-8")

        with (
            patch("igp_ride.daemon.get_daemon_paths", return_value=paths),
            patch("igp_ride.daemon._is_process_running", side_effect=[True, False]),
            patch("igp_ride.daemon.os.kill") as mock_kill,
            patch("igp_ride.daemon.time.monotonic", side_effect=[0.0, 0.0]),
            patch("igp_ride.daemon.time.sleep"),
        ):
            stopped, returned_paths = stop_daemon_process(config)

        assert stopped is True
        assert returned_paths == paths
        assert not paths.pid_file.exists()
        mock_kill.assert_called_once_with(999, signal.SIGTERM)


class TestRunDaemonLoop:
    def test_once_mode_updates_state_and_exits(self, tmp_path: Path):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)
        service = FakeService(SyncSummary(remote_fetched=1, new_activities=0))

        with patch("igp_ride.daemon.get_daemon_paths", return_value=paths):
            exit_code = run_daemon_loop(
                config,
                interval_seconds=60,
                hook_command=None,
                once=True,
                service_factory=lambda _config: service,
            )

        assert exit_code == 0
        assert service.closed is True
        assert not paths.pid_file.exists()
        state = json.loads(paths.state_file.read_text(encoding="utf-8"))
        assert state["running"] is False
        assert state["last_status"] == "ok"
        assert state["last_new_activities"] == 0


class TestDaemonStatusOutput:
    def test_status_formats_last_run_in_local_timezone(self, capsys):
        state = {
            "running": True,
            "pid": 1234,
            "interval_seconds": 1800,
            "hook_command": "",
            "log_file": "/tmp/daemon.log",
            "last_status": "ok",
            "last_run_at": datetime(2026, 4, 1, 13, 53, 38, tzinfo=UTC).isoformat(),
            "last_remote_fetched": 57,
            "last_new_activities": 1,
            "last_updated_activities": 0,
            "last_activities_skipped": 56,
            "last_fit_files_failed": 0,
            "last_hook_triggered": True,
        }

        with (
            patch("igp_ride.cli.AppConfig.load"),
            patch("igp_ride.cli.get_daemon_status", return_value=state),
        ):
            exit_code = cmd_daemon_status()

        captured = capsys.readouterr()
        expected = (
            datetime(2026, 4, 1, 13, 53, 38, tzinfo=UTC)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S %Z")
        )
        assert exit_code == 0
        assert "== Daemon Status ==" in captured.out
        assert f"Last Run: {expected}" in captured.out
        assert (
            "Summary: remote=57 new=1 updated=0 skipped=56 fit_failed=0" in captured.out
        )
        assert "Last Hook: triggered" in captured.out
