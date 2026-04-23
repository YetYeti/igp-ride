from __future__ import annotations

import json
import plistlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from igp_ride.config import AppConfig
from igp_ride.cli import cmd_daemon_status
from igp_ride.daemon import (
    CycleResult,
    DaemonError,
    DaemonPaths,
    get_daemon_status,
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
        launch_agent_file=tmp_path / "com.yetyeti.igp-ride.daemon.plist",
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
    def test_start_daemon_process_rejects_windows(self, tmp_path: Path):
        config = _make_config(tmp_path)

        with patch("igp_ride.daemon.sys.platform", "win32"):
            with pytest.raises(DaemonError, match="only supported on macOS"):
                start_daemon_process(config, interval_spec="30m")

    def test_start_daemon_process_writes_launch_agent_plist(self, tmp_path: Path):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)

        with (
            patch("igp_ride.daemon.is_daemon_management_supported", return_value=True),
            patch("igp_ride.daemon.get_daemon_paths", return_value=paths),
            patch("igp_ride.daemon._launchctl_domain", return_value="gui/501"),
            patch("igp_ride.daemon._launch_agent_loaded", return_value=False),
            patch("igp_ride.daemon.subprocess.run") as mock_run,
        ):
            returned_paths = start_daemon_process(
                config,
                interval_spec="30m",
                hook_command="echo hook",
            )

        assert returned_paths == paths
        state = json.loads(paths.state_file.read_text(encoding="utf-8"))
        assert state["backend"] == "launch-agent"
        assert state["interval_seconds"] == 1800
        assert state["hook_command"] == "echo hook"
        assert state["launch_agent_file"] == str(paths.launch_agent_file)
        payload = plistlib.loads(paths.launch_agent_file.read_bytes())
        assert payload["Label"] == paths.launch_agent_label
        assert payload["RunAtLoad"] is True
        assert payload["StartInterval"] == 1800
        assert payload["ProgramArguments"] == [
            sys.executable,
            "-m",
            "igp_ride.cli",
            "daemon",
            "run",
            "--once",
            "--interval",
            "30m",
            "--hook",
            "echo hook",
        ]
        mock_run.assert_called_once_with(
            ["launchctl", "bootstrap", "gui/501", str(paths.launch_agent_file)],
            check=True,
        )

    def test_stop_daemon_process_unloads_launch_agent(self, tmp_path: Path):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)
        paths.launch_agent_file.parent.mkdir(parents=True, exist_ok=True)
        paths.launch_agent_file.write_bytes(b"plist")

        with (
            patch("igp_ride.daemon.is_daemon_management_supported", return_value=True),
            patch("igp_ride.daemon.get_daemon_paths", return_value=paths),
            patch("igp_ride.daemon._launchctl_domain", return_value="gui/501"),
            patch("igp_ride.daemon._launch_agent_loaded", side_effect=[True, False]),
            patch("igp_ride.daemon.subprocess.run") as mock_run,
            patch("igp_ride.daemon.time.monotonic", side_effect=[0.0, 0.0]),
            patch("igp_ride.daemon.time.sleep"),
        ):
            stopped, returned_paths = stop_daemon_process(config)

        assert stopped is True
        assert returned_paths == paths
        assert not paths.launch_agent_file.exists()
        state = json.loads(paths.state_file.read_text(encoding="utf-8"))
        assert state["running"] is False
        assert state["backend"] == "launch-agent"
        mock_run.assert_called_once_with(
            ["launchctl", "bootout", "gui/501", str(paths.launch_agent_file)],
            check=True,
        )


class TestDaemonStatusState:
    def test_status_merges_launch_agent_and_active_pid(self, tmp_path: Path):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)
        paths.pid_file.write_text("999\n", encoding="utf-8")
        paths.state_file.write_text('{"last_status":"ok"}', encoding="utf-8")

        with (
            patch("igp_ride.daemon.is_daemon_management_supported", return_value=True),
            patch("igp_ride.daemon.get_daemon_paths", return_value=paths),
            patch("igp_ride.daemon._launch_agent_loaded", return_value=True),
            patch("igp_ride.daemon._is_process_running", return_value=True),
        ):
            state = get_daemon_status(config)

        assert state["running"] is True
        assert state["active"] is True
        assert state["pid"] == 999
        assert state["backend"] == "launch-agent"
        assert state["launch_agent_file"] == str(paths.launch_agent_file)
        assert state["launch_agent_label"] == paths.launch_agent_label


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

    def test_once_mode_uses_foreground_backend_when_daemon_management_is_unsupported(
        self, tmp_path: Path
    ):
        config = _make_config(tmp_path)
        paths = _make_paths(tmp_path)
        service = FakeService(SyncSummary(remote_fetched=1, new_activities=0))

        with (
            patch("igp_ride.daemon.get_daemon_paths", return_value=paths),
            patch("igp_ride.daemon.is_daemon_management_supported", return_value=False),
        ):
            exit_code = run_daemon_loop(
                config,
                interval_seconds=60,
                hook_command=None,
                once=True,
                service_factory=lambda _config: service,
            )

        state = json.loads(paths.state_file.read_text(encoding="utf-8"))
        assert exit_code == 0
        assert state["backend"] == "foreground"
        assert "launch_agent_file" not in state


class TestDaemonStatusOutput:
    def test_status_formats_last_run_in_local_timezone(self, capsys):
        state = {
            "running": True,
            "active": False,
            "interval_seconds": 1800,
            "hook_command": "",
            "backend": "launch-agent",
            "launch_agent_file": "/tmp/com.yetyeti.igp-ride.daemon.plist",
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
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        assert exit_code == 0
        assert "== Daemon Status ==" in captured.out
        assert "Backend: launch-agent" in captured.out
        expected_agent = str(Path("/tmp/com.yetyeti.igp-ride.daemon.plist").resolve())
        assert f"Agent: {expected_agent}" in captured.out
        assert "Active: no" in captured.out
        assert f"Last Run: {expected}" in captured.out
        assert (
            "Summary: remote=57 new=1 updated=0 skipped=56 fit_failed=0" in captured.out
        )
        assert "Last Hook: triggered" in captured.out
