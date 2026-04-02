from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Final, cast

from igp_ride.config import AppConfig
from igp_ride.models import SyncSummary
from igp_ride.service import RideSyncService
from igp_ride.utils import LOG_DIR, format_duration, get_logger


logger = get_logger(__name__)

DEFAULT_INTERVAL = "30m"
PID_FILE_NAME: Final[str] = "daemon.pid"
STATE_FILE_NAME: Final[str] = "daemon_state.json"
STARTUP_POLL_SECONDS = 0.2
STOP_WAIT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class DaemonPaths:
    pid_file: Path
    state_file: Path
    log_file: Path


@dataclass(frozen=True, slots=True)
class CycleResult:
    summary: SyncSummary
    hook_triggered: bool = False


class DaemonError(Exception):
    pass


def parse_interval_spec(value: str) -> int:
    raw = value.strip().lower()
    if not raw:
        raise ValueError("Interval is required.")

    unit = raw[-1]
    number_text = raw[:-1] if unit.isalpha() else raw
    multiplier = {"s": 1, "m": 60, "h": 3600}
    if unit.isalpha():
        if unit not in multiplier:
            raise ValueError("Interval must use s, m, or h suffix.")
        if not number_text:
            raise ValueError("Interval must include a number.")
        scale = multiplier[unit]
    else:
        scale = 60
    try:
        amount = int(number_text)
    except ValueError as exc:
        raise ValueError("Interval must be an integer value.") from exc
    if amount <= 0:
        raise ValueError("Interval must be greater than zero.")
    return amount * scale


def format_interval_seconds(seconds: int) -> str:
    return format_duration(float(seconds))


def get_daemon_paths(config: AppConfig) -> DaemonPaths:
    return DaemonPaths(
        pid_file=config.session_file.parent / PID_FILE_NAME,
        state_file=config.session_file.parent / STATE_FILE_NAME,
        log_file=LOG_DIR / "daemon.log",
    )


def daemon_is_running(paths: DaemonPaths) -> bool:
    pid = read_daemon_pid(paths.pid_file)
    return pid is not None and _is_process_running(pid)


def read_daemon_pid(path: Path) -> int | None:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content:
        return None
    try:
        pid = int(content)
    except ValueError:
        return None
    return pid if pid > 0 else None


def load_daemon_state(path: Path) -> dict[str, object]:
    try:
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except OSError, json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def save_daemon_state(path: Path, state: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def start_daemon_process(
    config: AppConfig,
    *,
    interval_spec: str,
    hook_command: str | None = None,
) -> tuple[int, DaemonPaths]:
    paths = get_daemon_paths(config)
    if daemon_is_running(paths):
        pid = read_daemon_pid(paths.pid_file)
        raise DaemonError(f"Daemon is already running (pid {pid}).")

    _cleanup_stale_files(paths)
    paths.log_file.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "igp_ride.cli",
        "daemon",
        "run",
        "--interval",
        interval_spec,
    ]
    if hook_command:
        command.extend(["--hook", hook_command])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    log_handle = paths.log_file.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    finally:
        log_handle.close()

    state: dict[str, object] = {
        "pid": process.pid,
        "running": True,
        "started_at": _utc_now().isoformat(),
        "interval_seconds": parse_interval_spec(interval_spec),
        "hook_command": hook_command or "",
        "log_file": str(paths.log_file),
        "last_status": "starting",
    }
    _write_pid_file(paths.pid_file, process.pid)
    save_daemon_state(paths.state_file, state)

    time.sleep(STARTUP_POLL_SECONDS)
    if process.poll() is not None:
        _cleanup_stale_files(paths)
        raise DaemonError("Daemon process exited immediately. Check daemon.log.")
    return process.pid, paths


def stop_daemon_process(config: AppConfig) -> tuple[bool, DaemonPaths]:
    paths = get_daemon_paths(config)
    pid = read_daemon_pid(paths.pid_file)
    if pid is None:
        _cleanup_stale_files(paths)
        return False, paths
    if not _is_process_running(pid):
        _cleanup_stale_files(paths)
        return False, paths

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _is_process_running(pid):
            _cleanup_stale_files(paths)
            return True, paths
        time.sleep(0.1)

    os.kill(pid, signal.SIGKILL)
    _cleanup_stale_files(paths)
    return True, paths


def get_daemon_status(config: AppConfig) -> dict[str, object]:
    paths = get_daemon_paths(config)
    state = load_daemon_state(paths.state_file)
    pid = read_daemon_pid(paths.pid_file)
    running = pid is not None and _is_process_running(pid)
    if pid is not None:
        state["pid"] = pid
    state["running"] = running
    if "log_file" not in state:
        state["log_file"] = str(paths.log_file)
    return state


def run_sync_cycle(
    config: AppConfig,
    *,
    interval_seconds: int,
    hook_command: str | None = None,
    service_factory: Callable[[AppConfig], RideSyncService] = RideSyncService,
) -> CycleResult:
    service = service_factory(config)
    try:
        summary = service.sync(force_full=False)
    finally:
        service.close()

    hook_triggered = False
    if summary.new_activities > 0 and hook_command:
        _run_hook_command(hook_command, summary, interval_seconds)
        hook_triggered = True
    return CycleResult(summary=summary, hook_triggered=hook_triggered)


def run_daemon_loop(
    config: AppConfig,
    *,
    interval_seconds: int,
    hook_command: str | None = None,
    once: bool = False,
    service_factory: Callable[[AppConfig], RideSyncService] = RideSyncService,
) -> int:
    paths = get_daemon_paths(config)
    stop_event = Event()
    previous_handlers = _install_signal_handlers(stop_event)
    started_at = _utc_now()
    state = load_daemon_state(paths.state_file)
    state.update(
        {
            "pid": os.getpid(),
            "running": True,
            "started_at": state.get("started_at", started_at.isoformat()),
            "interval_seconds": interval_seconds,
            "hook_command": hook_command or "",
            "log_file": str(paths.log_file),
            "last_status": "running",
        }
    )
    _write_pid_file(paths.pid_file, os.getpid())
    save_daemon_state(paths.state_file, state)

    exit_code = 0
    logger.info(
        "Daemon started: pid=%d interval=%s hook=%s",
        os.getpid(),
        format_interval_seconds(interval_seconds),
        hook_command or "<none>",
    )

    try:
        while not stop_event.is_set():
            started_cycle_at = _utc_now()
            try:
                result = run_sync_cycle(
                    config,
                    interval_seconds=interval_seconds,
                    hook_command=hook_command,
                    service_factory=service_factory,
                )
                _update_cycle_state(
                    paths,
                    running=True,
                    interval_seconds=interval_seconds,
                    hook_command=hook_command or "",
                    log_file=str(paths.log_file),
                    last_run_at=started_cycle_at.isoformat(),
                    last_status="ok",
                    last_error="",
                    last_remote_fetched=result.summary.remote_fetched,
                    last_new_activities=result.summary.new_activities,
                    last_updated_activities=result.summary.updated_activities,
                    last_activities_skipped=result.summary.activities_skipped,
                    last_fit_files_failed=result.summary.fit_files_failed,
                    last_hook_triggered=result.hook_triggered,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Daemon cycle failed: %s", exc)
                _update_cycle_state(
                    paths,
                    running=True,
                    interval_seconds=interval_seconds,
                    hook_command=hook_command or "",
                    log_file=str(paths.log_file),
                    last_run_at=started_cycle_at.isoformat(),
                    last_status="error",
                    last_error=str(exc),
                )
                exit_code = 1
                if once:
                    break
            else:
                exit_code = 0

            if once:
                break
            stop_event.wait(interval_seconds)
    finally:
        _update_cycle_state(
            paths,
            running=False,
            interval_seconds=interval_seconds,
            hook_command=hook_command or "",
            log_file=str(paths.log_file),
            stopped_at=_utc_now().isoformat(),
        )
        _remove_pid_file(paths.pid_file, os.getpid())
        _restore_signal_handlers(previous_handlers)
        logger.info("Daemon stopped: pid=%d", os.getpid())

    return exit_code


def _run_hook_command(
    command: str,
    summary: SyncSummary,
    interval_seconds: int,
) -> None:
    env = os.environ.copy()
    env.update(
        {
            "IGP_RIDE_REMOTE_FETCHED": str(summary.remote_fetched),
            "IGP_RIDE_NEW_ACTIVITIES": str(summary.new_activities),
            "IGP_RIDE_UPDATED_ACTIVITIES": str(summary.updated_activities),
            "IGP_RIDE_ACTIVITIES_SKIPPED": str(summary.activities_skipped),
            "IGP_RIDE_FIT_FILES_FAILED": str(summary.fit_files_failed),
            "IGP_RIDE_INTERVAL_SECONDS": str(interval_seconds),
        }
    )
    logger.info(
        "Running hook command after detecting %d new activities", summary.new_activities
    )
    subprocess.run(command, shell=True, check=True, env=env)


def _cleanup_stale_files(paths: DaemonPaths) -> None:
    _remove_if_exists(paths.pid_file)
    _update_cycle_state(
        paths,
        running=False,
        last_status="stopped",
    )


def _write_pid_file(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def _remove_pid_file(path: Path, expected_pid: int) -> None:
    pid = read_daemon_pid(path)
    if pid != expected_pid:
        return
    _remove_if_exists(path)


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _update_cycle_state(paths: DaemonPaths, **updates: object) -> None:
    state = load_daemon_state(paths.state_file)
    state.update(updates)
    save_daemon_state(paths.state_file, state)


def _install_signal_handlers(
    stop_event: Event,
) -> dict[signal.Signals, object]:
    previous_handlers: dict[signal.Signals, object] = {}

    def handler(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %d, stopping daemon loop", signum)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, handler)
    return previous_handlers


def _restore_signal_handlers(
    previous_handlers: Mapping[signal.Signals, object],
) -> None:
    for sig, handler in previous_handlers.items():
        signal.signal(sig, cast(signal.Handlers, handler))


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _utc_now() -> datetime:
    return datetime.now(UTC)
