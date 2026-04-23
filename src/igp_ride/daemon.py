from __future__ import annotations

import json
import os
import plistlib
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
from igp_ride.utils import format_duration, get_log_dir, get_logger


logger = get_logger(__name__)

DEFAULT_INTERVAL = "30m"
PID_FILE_NAME: Final[str] = "daemon.pid"
STATE_FILE_NAME: Final[str] = "daemon_state.json"
LAUNCH_AGENT_LABEL: Final[str] = "com.yetyeti.igp-ride.daemon"
STOP_WAIT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class DaemonPaths:
    pid_file: Path
    state_file: Path
    log_file: Path
    launch_agent_file: Path
    launch_agent_label: str = LAUNCH_AGENT_LABEL


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
        log_file=get_log_dir() / "daemon.log",
        launch_agent_file=Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{LAUNCH_AGENT_LABEL}.plist",
    )


def is_daemon_management_supported() -> bool:
    return sys.platform == "darwin"


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
) -> DaemonPaths:
    if not is_daemon_management_supported():
        raise DaemonError("Daemon scheduling is only supported on macOS.")
    paths = get_daemon_paths(config)
    if _launch_agent_loaded(paths):
        raise DaemonError("Daemon is already loaded via LaunchAgent.")
    if daemon_is_running(paths):
        pid = read_daemon_pid(paths.pid_file)
        raise DaemonError(
            "Legacy daemon process is still running. "
            f"Stop it before switching to LaunchAgent mode (pid {pid})."
        )

    _remove_if_exists(paths.pid_file)
    paths.log_file.parent.mkdir(parents=True, exist_ok=True)
    paths.launch_agent_file.parent.mkdir(parents=True, exist_ok=True)

    interval_seconds = parse_interval_spec(interval_spec)
    plist_payload = _build_launch_agent_plist(
        paths,
        interval_spec=interval_spec,
        interval_seconds=interval_seconds,
        hook_command=hook_command,
    )
    with paths.launch_agent_file.open("wb") as handle:
        plistlib.dump(plist_payload, handle, sort_keys=True)
    try:
        _launchctl("bootstrap", _launchctl_domain(), str(paths.launch_agent_file))
    except Exception:
        _remove_if_exists(paths.launch_agent_file)
        raise
    state: dict[str, object] = {
        "running": True,
        "started_at": _utc_now().isoformat(),
        "backend": "launch-agent",
        "interval_seconds": interval_seconds,
        "hook_command": hook_command or "",
        "log_file": str(paths.log_file),
        "launch_agent_file": str(paths.launch_agent_file),
        "launch_agent_label": paths.launch_agent_label,
        "last_status": "scheduled",
    }
    save_daemon_state(paths.state_file, state)
    return paths


def stop_daemon_process(config: AppConfig) -> tuple[bool, DaemonPaths]:
    if not is_daemon_management_supported():
        raise DaemonError("Daemon scheduling is only supported on macOS.")
    paths = get_daemon_paths(config)
    launch_agent_loaded = _launch_agent_loaded(paths)
    if not launch_agent_loaded and not paths.launch_agent_file.exists():
        _cleanup_stale_files(paths)
        return False, paths

    if launch_agent_loaded:
        _launchctl("bootout", _launchctl_domain(), str(paths.launch_agent_file))
        _wait_for_launch_agent_unload(paths)

    _remove_if_exists(paths.launch_agent_file)
    _cleanup_stale_files(paths)
    state = load_daemon_state(paths.state_file)
    state.update(
        {
            "running": False,
            "backend": "launch-agent",
            "launch_agent_file": str(paths.launch_agent_file),
            "launch_agent_label": paths.launch_agent_label,
            "stopped_at": _utc_now().isoformat(),
        }
    )
    save_daemon_state(paths.state_file, state)
    return True, paths


def get_daemon_status(config: AppConfig) -> dict[str, object]:
    paths = get_daemon_paths(config)
    state = load_daemon_state(paths.state_file)
    pid = read_daemon_pid(paths.pid_file)
    active = pid is not None and _is_process_running(pid)
    loaded = _launch_agent_loaded(paths) if is_daemon_management_supported() else active
    if pid is not None:
        state["pid"] = pid
    else:
        state.pop("pid", None)
    state["running"] = loaded
    state["active"] = active
    if is_daemon_management_supported():
        state["backend"] = "launch-agent"
        state["launch_agent_file"] = str(paths.launch_agent_file)
        state["launch_agent_label"] = paths.launch_agent_label
    else:
        backend = state.get("backend")
        state["backend"] = backend if isinstance(backend, str) and backend else "foreground"
        state.pop("launch_agent_file", None)
        state.pop("launch_agent_label", None)
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
            "backend": state.get(
                "backend",
                "launch-agent" if is_daemon_management_supported() else "foreground",
            ),
            "interval_seconds": interval_seconds,
            "hook_command": hook_command or "",
            "log_file": str(paths.log_file),
            "last_status": "running",
        }
    )
    if is_daemon_management_supported():
        state["launch_agent_file"] = state.get(
            "launch_agent_file", str(paths.launch_agent_file)
        )
        state["launch_agent_label"] = state.get(
            "launch_agent_label", paths.launch_agent_label
        )
    else:
        state.pop("launch_agent_file", None)
        state.pop("launch_agent_label", None)
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


def _build_launch_agent_plist(
    paths: DaemonPaths,
    *,
    interval_spec: str,
    interval_seconds: int,
    hook_command: str | None,
) -> dict[str, object]:
    program_arguments = [
        sys.executable,
        "-m",
        "igp_ride.cli",
        "daemon",
        "run",
        "--once",
        "--interval",
        interval_spec,
    ]
    if hook_command:
        program_arguments.extend(["--hook", hook_command])
    payload: dict[str, object] = {
        "Label": paths.launch_agent_label,
        "ProgramArguments": program_arguments,
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "StandardOutPath": str(paths.log_file),
        "StandardErrorPath": str(paths.log_file),
    }
    environment = _launch_agent_environment()
    if environment:
        payload["EnvironmentVariables"] = environment
    return payload


def _launch_agent_environment() -> dict[str, str]:
    environment = {"PYTHONUNBUFFERED": "1"}
    for name in ("PATH", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
        value = os.getenv(name)
        if value:
            environment[name] = value
    return environment


def _launch_agent_loaded(paths: DaemonPaths) -> bool:
    result = subprocess.run(
        [
            "launchctl",
            "print",
            f"{_launchctl_domain()}/{paths.launch_agent_label}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> None:
    subprocess.run(["launchctl", *args], check=True)


def _wait_for_launch_agent_unload(paths: DaemonPaths) -> None:
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _launch_agent_loaded(paths):
            return
        time.sleep(0.1)
    raise DaemonError("LaunchAgent did not unload in time.")


def _utc_now() -> datetime:
    return datetime.now(UTC)
