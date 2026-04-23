from __future__ import annotations

import argparse
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final, Sequence, TextIO

import requests

from igp_ride.client import AuthenticationError, DataSyncError
from igp_ride.config import AppConfig, ConfigurationError
from igp_ride.daemon import (
    DEFAULT_INTERVAL,
    DaemonError,
    get_daemon_status,
    is_daemon_management_supported,
    parse_interval_spec,
    run_daemon_loop,
    start_daemon_process,
    stop_daemon_process,
)
from igp_ride.database import ActivitySortKey, DatabaseError
from igp_ride.models import Activity, PeriodStats, SyncSummary
from igp_ride.service import ResetResult, RideSyncService, SyncProgress
from igp_ride.utils import setup_logging


_title_printed = False


def _get_cli_version() -> str:
    try:
        return version("igp-ride")
    except PackageNotFoundError:
        return "unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="igp-ride",
        description="Sync IGPSPORT cycling activities to local SQLite",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_cli_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Log in to cycling website")
    login_parser.add_argument("--username", help="Use specified username")

    subparsers.add_parser("logout", help="Clear local credentials and session")
    reset_parser = subparsers.add_parser(
        "reset",
        help="Delete all local stored data (database, FIT files, credentials, session)",
    )
    reset_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation",
    )

    update_parser = subparsers.add_parser(
        "update",
        help="Update remote activities and download FIT files",
    )
    update_parser.add_argument(
        "--progress",
        choices=["auto", "plain", "off"],
        default="auto",
        help="Progress output mode (default: auto)",
    )
    update_parser.add_argument(
        "--all",
        action="store_true",
        help="Force full update of all activities",
    )
    update_parser.add_argument(
        "--repair",
        action="store_true",
        help="Only re-download missing or invalid FIT files",
    )

    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Manage background sync scheduling",
    )
    daemon_subparsers = daemon_parser.add_subparsers(
        dest="daemon_command",
        required=True,
    )

    daemon_start_parser = daemon_subparsers.add_parser(
        "start",
        help="Install and start the background sync LaunchAgent",
    )
    daemon_start_parser.add_argument(
        "--interval",
        default=DEFAULT_INTERVAL,
        help="Polling interval, e.g. 30m, 1h, or 45 (minutes).",
    )
    daemon_start_parser.add_argument(
        "--hook",
        help="Shell command to run when new activities are detected.",
    )

    daemon_run_parser = daemon_subparsers.add_parser(
        "run",
        help="Run a sync cycle in the foreground",
    )
    daemon_run_parser.add_argument(
        "--interval",
        default=DEFAULT_INTERVAL,
        help="Polling interval, e.g. 30m, 1h, or 45 (minutes).",
    )
    daemon_run_parser.add_argument(
        "--hook",
        help="Shell command to run when new activities are detected.",
    )
    daemon_run_parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single update cycle and exit.",
    )

    daemon_subparsers.add_parser("stop", help="Stop and unload the background sync")
    daemon_subparsers.add_parser("status", help="Show background sync status")

    list_parser = subparsers.add_parser("list", help="List local activities")
    list_parser.add_argument("--limit", type=int, help="Show at most N activities")
    list_parser.add_argument(
        "--sort",
        choices=["date", "distance", "time", "speed", "elev", "power"],
        default="date",
        help="Sort by date, distance, time, speed, elevation, or power",
    )
    list_direction = list_parser.add_mutually_exclusive_group()
    list_direction.add_argument(
        "--asc",
        action="store_true",
        help="Sort in ascending order",
    )
    list_direction.add_argument(
        "--desc",
        action="store_true",
        help="Sort in descending order",
    )
    list_parser.add_argument(
        "--update",
        action="store_true",
        help="Update remote activities before listing",
    )

    show_parser = subparsers.add_parser("show", help="Show activity details")
    show_parser.add_argument("activity_id", help="Activity ID or 'last'")
    show_parser.add_argument(
        "--update",
        action="store_true",
        help="Update remote activities before showing",
    )

    stats_parser = subparsers.add_parser("stats", help="Show activity statistics")
    stats_parser.add_argument(
        "--by",
        choices=["month", "year"],
        default="month",
        help="Group by month or year (default: month)",
    )
    stats_parser.add_argument("--year", type=int, help="Filter by year")
    stats_parser.add_argument(
        "--type", dest="activity_type", help="Filter by activity title"
    )
    stats_parser.add_argument(
        "--update",
        action="store_true",
        help="Update remote activities before showing stats",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    _reset_output_state()

    try:
        if args.command == "login":
            return cmd_login(args.username)
        if args.command == "logout":
            return cmd_logout()
        if args.command == "reset":
            return cmd_reset(args.yes)
        if args.command == "update":
            return cmd_update(args.all, args.progress, args.repair)
        if args.command == "daemon":
            return cmd_daemon(args)
        if args.command == "list":
            return cmd_list(
                args.limit,
                args.update,
                args.sort,
                descending=not args.asc,
            )
        if args.command == "show":
            return cmd_show(args.activity_id, args.update)
        if args.command == "stats":
            return cmd_stats(args.by, args.year, args.activity_type, args.update)
    except ConfigurationError as exc:
        _print_error_block(
            _command_title(args),
            str(exc),
            "Run igp-ride login first",
        )
        return 2
    except AuthenticationError as exc:
        _print_error_block(
            _command_title(args),
            str(exc),
            "Run igp-ride login to re-authenticate",
        )
        return 3
    except requests.RequestException as exc:
        _print_error_block(
            _command_title(args),
            f"Network error: {exc}",
            "Check your internet connection and try again",
        )
        return 4
    except DatabaseError as exc:
        _print_error_block(_command_title(args), str(exc))
        return 5
    except DataSyncError as exc:
        _print_error_block(_command_title(args), str(exc))
        return 6
    except DaemonError as exc:
        _print_error_block(_command_title(args), str(exc))
        return 9
    except FileNotFoundError as exc:
        _print_error_block(_command_title(args), f"File error: {exc}")
        return 7
    except ValueError as exc:
        _print_error_block(_command_title(args), str(exc))
        return 2
    return 0


def cmd_login(username: str | None) -> int:
    config = AppConfig.load()
    service = RideSyncService(config)
    try:
        account, session_path = service.login(username=username)
    finally:
        service.close()

    _print_title("Login")
    _print_result("success")
    _print_field("Account", account)
    _print_field("Path", format_path(session_path))
    _print_next("igp-ride update")
    return 0


def cmd_update(force_full: bool, progress: str, repair: bool) -> int:
    config = AppConfig.load(require_credentials=True)
    service = RideSyncService(config)
    tty_progress = progress == "auto" and sys.stderr.isatty()
    plain_progress = progress == "plain" or (
        progress == "auto" and not sys.stderr.isatty()
    )
    current_stage: str | None = None
    last_plain_percent = -1
    _print_title("Update")

    def render_progress(p: SyncProgress) -> None:
        nonlocal current_stage, last_plain_percent
        if tty_progress and p.stage == "fetching":
            message = "Progress: stage=fetching"
            print(
                f"\r\033[2K{message}",
                end="",
                file=sys.stderr,
                flush=True,
            )
            current_stage = "fetching"
            return
        if tty_progress:
            if p.total <= 0:
                return
            percent = int((p.done / p.total) * 100)
            print(
                "\r\033[2K"
                f"Progress: done={p.done} total={p.total} percent={percent}"
                f" | new {p.new_activities}"
                f" | updated {p.updated_activities}"
                f" | skipped {p.activities_skipped}"
                f" | failed {p.fit_files_failed} ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            current_stage = "processing"
            return

        if not plain_progress:
            return

        if p.stage == "fetching":
            if current_stage != "fetching":
                print("Progress: stage=fetching")
                current_stage = "fetching"
            return

        if p.total <= 0:
            return

        percent = int((p.done / p.total) * 100)
        # Avoid flooding non-interactive outputs; print every 10% and final state.
        if percent < 100 and percent // 10 == last_plain_percent // 10:
            return
        last_plain_percent = percent
        print(f"Progress: done={p.done} total={p.total} percent={percent}")
        current_stage = "processing"

    try:
        if repair:
            summary = service.repair(progress_callback=render_progress)
        else:
            summary = service.sync(
                force_full=force_full, progress_callback=render_progress
            )
    finally:
        service.close()

    if tty_progress and current_stage is not None:
        print(file=sys.stderr)

    _print_result("success")
    _print_field("Mode", _update_mode(force_full, repair))
    _print_sync_summary(summary)
    if summary.fit_files_failed > 0:
        _print_warning(f"{summary.fit_files_failed} FIT file(s) failed to download.")
    _print_next("igp-ride list")
    return 0


def cmd_logout() -> int:
    config = AppConfig.load()
    service = RideSyncService(config)
    try:
        service.logout()
    finally:
        service.close()

    _print_title("Logout")
    _print_result("success")
    _print_field("Path", format_path(config.session_file))
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    if args.daemon_command == "start":
        return cmd_daemon_start(args.interval, args.hook)
    if args.daemon_command == "run":
        return cmd_daemon_run(args.interval, args.hook, args.once)
    if args.daemon_command == "stop":
        return cmd_daemon_stop()
    if args.daemon_command == "status":
        return cmd_daemon_status()
    raise ValueError(f"Unknown daemon command: {args.daemon_command}")


def cmd_daemon_start(interval: str, hook_command: str | None) -> int:
    _ensure_daemon_management_supported()
    config = AppConfig.load(require_credentials=True)
    interval_seconds = parse_interval_spec(interval)
    paths = start_daemon_process(
        config,
        interval_spec=interval,
        hook_command=hook_command,
    )
    _print_title("Daemon Start")
    _print_result("success")
    _print_field("Backend", "LaunchAgent")
    _print_field("Interval", _format_interval_display(interval_seconds))
    _print_field("Hook", hook_command or "<none>")
    _print_field("Agent", format_path(paths.launch_agent_file))
    _print_field("Log", format_path(paths.log_file))
    _print_next("igp-ride daemon status")
    return 0


def cmd_daemon_run(interval: str, hook_command: str | None, once: bool) -> int:
    config = AppConfig.load(require_credentials=True)
    interval_seconds = parse_interval_spec(interval)
    _print_title("Daemon Run")

    if once:
        exit_code = run_daemon_loop(
            config,
            interval_seconds=interval_seconds,
            hook_command=hook_command,
            once=True,
        )
        state = get_daemon_status(config)
        _print_result("success" if exit_code == 0 else "error")
        _print_field("Mode", "foreground-once")
        _print_field("Interval", _format_interval_display(interval_seconds))
        _print_field("Hook", hook_command or "<none>")
        if _has_sync_summary_state(state):
            _print_summary(_summary_items_from_state(state))
        _print_field("Hook Triggered", _as_bool(state.get("last_hook_triggered")))
        last_error = _as_str_state(state.get("last_error"))
        if last_error:
            _print_error_line(last_error)
        return exit_code

    _print_result("running")
    _print_field("Mode", "foreground")
    _print_field("Interval", _format_interval_display(interval_seconds))
    _print_field("Hook", hook_command or "<none>")
    _print_tip("Press Ctrl-C to stop")
    return run_daemon_loop(
        config,
        interval_seconds=interval_seconds,
        hook_command=hook_command,
        once=False,
    )


def cmd_daemon_stop() -> int:
    _ensure_daemon_management_supported()
    config = AppConfig.load()
    stopped, paths = stop_daemon_process(config)
    _print_title("Daemon Stop")
    _print_result("success" if stopped else "no-op")
    _print_field("Running", False)
    _print_field("Log", format_path(paths.log_file))
    return 0


def cmd_daemon_status() -> int:
    _ensure_daemon_management_supported()
    config = AppConfig.load()
    state = get_daemon_status(config)
    running = _as_bool(state.get("running"))
    active = _as_bool(state.get("active"))
    pid = _as_int_state(state.get("pid"))
    interval_seconds = _as_int_state(state.get("interval_seconds"))
    hook_command = _as_str_state(state.get("hook_command"))
    log_file = _as_str_state(state.get("log_file"))
    backend = _as_str_state(state.get("backend"))
    launch_agent_file = _as_str_state(state.get("launch_agent_file"))
    last_status = _as_str_state(state.get("last_status"))
    last_run_at = _as_str_state(state.get("last_run_at"))
    last_error = _as_str_state(state.get("last_error"))
    hook_triggered = _as_bool(state.get("last_hook_triggered"))

    _print_title("Daemon Status")
    _print_field("Running", running)
    if backend:
        _print_field("Backend", backend)
    if launch_agent_file:
        _print_field("Agent", format_path(Path(launch_agent_file)))
    _print_field("Active", active)
    if pid > 0:
        _print_field("PID", pid)
    if interval_seconds > 0:
        _print_field("Interval", _format_interval_display(interval_seconds))
    _print_field("Hook", hook_command or "<none>")
    if log_file:
        _print_field("Log", format_path(Path(log_file)))
    if last_status:
        _print_field("Last Status", last_status)
    if last_run_at:
        _print_field("Last Run", _format_local_timestamp(last_run_at))
    if _has_sync_summary_state(state):
        _print_summary(_summary_items_from_state(state))
    if hook_triggered:
        _print_field("Last Hook", "triggered")
    if last_error:
        _print_error_line(last_error)
    return 0


def cmd_list(
    limit: int | None,
    do_update: bool,
    sort_by: ActivitySortKey = "date",
    *,
    descending: bool = True,
) -> int:
    config = AppConfig.load(require_credentials=do_update)
    service = RideSyncService(config)
    try:
        if do_update:
            service.sync()
        activities = service.list_activities(
            limit=limit,
            sort_by=sort_by,
            descending=descending,
        )
    finally:
        service.close()

    _print_title("Activity List")
    if not activities:
        _print_field("Count", 0)
        _print_tip("Run igp-ride update to download activities from IGPSPORT")
        return 0

    if limit is not None:
        _print_field("Limit", limit)
    else:
        _print_field("Count", len(activities))
    print()
    print(
        f"{'RIDE_ID':<8}   {'DATE':<10}   {'DISTANCE':>8}   "
        f"{'TIME':>6}   {'AVG_SPD':>9}   {'ELEV':>8}   {'AVG_PWR':>7}   TITLE"
    )
    for activity in activities:
        start = _format_activity_date(activity.start_time)
        title = format_activity_name(activity.title)
        distance = f"{activity.total_distance / 1000:.1f} km"
        avg_speed = (
            f"{to_kmh(activity.avg_speed):.1f} km/h" if activity.avg_speed > 0 else "-"
        )
        elevation = f"{activity.total_ascent:,} m"
        power = f"{activity.avg_power:.0f} W" if activity.avg_power > 0 else "-"
        print(
            f"{activity.ride_id:<8}   {start:<10}   {distance:>8}   "
            f"{_format_list_duration_display(activity.total_moving_time):>6}   "
            f"{avg_speed:>9}   {elevation:>8}   {power:>7}   {title}"
        )
    return 0


def _format_local_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def cmd_reset(yes: bool) -> int:
    config = AppConfig.load()
    _print_title("Reset")
    if not yes:
        _print_warning("This will permanently delete all local igp-ride data.")
        _print_warning(
            "Saved credentials and session data in the system keychain will also be removed."
        )
        _print_field("Data Path", format_path(config.data_dir))
        _print_field("Config Path", format_path(config.session_file.parent))
        print()
        confirm = input("Type RESET to confirm: ").strip()
        if confirm != "RESET":
            _print_result("cancelled")
            return 0

    service = RideSyncService(config)
    try:
        results = service.reset()
    finally:
        service.close()

    print_reset_summary(results)
    has_failure = any(item.status == "failed" for item in results)
    return 10 if has_failure else 0


def cmd_show(activity_id: str, do_update: bool) -> int:
    config = AppConfig.load(require_credentials=do_update)
    service = RideSyncService(config)
    try:
        if do_update:
            service.sync(force_full=False)
        if activity_id == "last":
            activity = service.get_latest_activity()
        else:
            activity = service.show_activity(int(activity_id))
    finally:
        service.close()

    _print_title("Activity Details")
    if activity is None:
        if activity_id == "last":
            _print_error_line("No activities found")
            _print_tip("Run igp-ride update to download activities first")
        else:
            _print_error_line(f"Activity not found: {activity_id}")
            _print_tip("Run igp-ride list to see available activities")
        return 8

    print_activity(activity)
    return 0


def cmd_stats(
    group_by: str, year: int | None, activity_type: str | None, do_update: bool
) -> int:
    config = AppConfig.load(require_credentials=do_update)
    service = RideSyncService(config)
    try:
        if do_update:
            service.sync(force_full=False)
        stats = service.get_stats(
            group_by=group_by, year=year, activity_type=activity_type
        )
    finally:
        service.close()

    _print_title("Ride Statistics")
    if not stats:
        _print_field("Count", 0)
        _print_tip("Run igp-ride update to download activities first")
        return 0

    print_stats(stats)
    return 0


def print_stats(stats: list[PeriodStats]) -> None:
    total_count = sum(s.count for s in stats)
    total_distance = sum(s.total_distance for s in stats)
    total_time = sum(s.total_moving_time for s in stats)
    total_ascent = sum(s.total_ascent for s in stats)

    _print_field("Periods", len(stats))
    _print_field("Rides", total_count)
    _print_field("Distance", f"{total_distance / 1000:,.1f} km")
    _print_field("Time", f"{total_time / 3600:.1f} h")
    _print_field("Ascent", f"{total_ascent:,} m")
    print()
    print(
        f"{'PERIOD':<8}   {'CNT':>2}   {'DISTANCE':>9}   "
        f"{'TIME':>6}   {'AVG_SPD':>9}   {'AVG_PWR':>7}   {'ASCENT':>8}"
    )
    for s in stats:
        distance = f"{s.total_distance / 1000:,.1f} km"
        time_str = _format_list_duration_display(s.total_moving_time)
        avg_spd = f"{to_kmh(s.avg_speed):.1f} km/h" if s.avg_speed > 0 else "-"
        avg_pwr = f"{s.avg_power:.0f} W" if s.avg_power > 0 else "-"
        elev = f"{s.total_ascent:,} m"
        print(
            f"{s.period:<8}   {s.count:>2}   {distance:>9}   "
            f"{time_str:>6}   {avg_spd:>9}   {avg_pwr:>7}   {elev:>8}"
        )


def print_reset_summary(results: list[ResetResult]) -> None:
    deleted = sum(1 for item in results if item.status == "deleted")
    not_found = sum(1 for item in results if item.status == "not_found")
    failed = sum(1 for item in results if item.status == "failed")
    _print_result("partial" if failed > 0 else "success")
    for item in results:
        status = item.status
        if item.error:
            print(f"{status}: {format_path(item.path)} ({item.error})")
        else:
            print(f"{status}: {format_path(item.path)}")
    _print_summary(
        [
            ("deleted", deleted),
            ("not_found", not_found),
            ("failed", failed),
        ]
    )


def print_activity(activity: Activity) -> None:
    _print_field("ID", activity.ride_id)
    _print_field("Title", format_activity_name(activity.title))
    _print_field("Start Time", _format_activity_timestamp(activity.start_time))
    _print_field("Distance", f"{activity.total_distance / 1000:.2f} km")
    _print_field(
        "Moving / Elapsed",
        (
            f"{_format_duration_display(activity.total_moving_time)} / "
            f"{_format_duration_display(activity.total_elapsed_time)}"
        ),
    )
    _print_field(
        "Ascent / Descent",
        f"{activity.total_ascent} m / {activity.total_descent} m",
    )

    power_parts: list[str] = []
    if activity.avg_power > 0:
        power_parts.append(f"{activity.avg_power} W")
    if activity.max_power > 0:
        power_parts.append(f"max {activity.max_power} W")
    if activity.normalized_power > 0:
        power_parts.append(f"NP {activity.normalized_power} W")
    if activity.intensity_factor > 0:
        power_parts.append(f"IF {activity.intensity_factor:.2f}")
    if activity.training_stress_score > 0:
        power_parts.append(f"TSS {activity.training_stress_score:.1f}")
    if power_parts:
        _print_field("Power", " | ".join(power_parts))
    elif activity.training_stress_score > 0:
        _print_field("TSS", f"{activity.training_stress_score:.1f}")

    if activity.avg_heart_rate > 0 or activity.max_heart_rate > 0:
        _print_field(
            "Heart Rate",
            _format_avg_max_metric(
                avg_value=activity.avg_heart_rate,
                max_value=activity.max_heart_rate,
                unit="bpm",
            ),
        )
    if activity.avg_cadence > 0 or activity.max_cadence > 0:
        _print_field(
            "Cadence",
            _format_avg_max_metric(
                avg_value=activity.avg_cadence,
                max_value=activity.max_cadence,
                unit="rpm",
            ),
        )
    if activity.avg_speed > 0 or activity.max_speed > 0:
        _print_field(
            "Speed",
            _format_avg_max_metric(
                avg_value=to_kmh(activity.avg_speed),
                max_value=to_kmh(activity.max_speed),
                unit="km/h",
                precision=1,
            ),
        )
    if activity.total_calories > 0:
        _print_field("Calories", f"{activity.total_calories:,} kcal")


def format_activity_name(title: str) -> str:
    if title == "室内骑行":
        return "室内骑行"
    if title == "户外骑行":
        return "户外骑行"
    return title


def to_kmh(speed_mps: float) -> float:
    return speed_mps * 3.6


def format_path(path: Path) -> str:
    abs_path = path.resolve()
    if sys.platform == "win32":
        return str(abs_path)
    home = Path.home().resolve()
    try:
        return f"~/{abs_path.relative_to(home)}"
    except ValueError:
        return str(abs_path)


def _as_bool(value: object) -> bool:
    return bool(value)


def _as_int_state(value: object) -> int:
    return value if isinstance(value, int) else 0


def _as_str_state(value: object) -> str:
    return value if isinstance(value, str) else ""


def _reset_output_state() -> None:
    global _title_printed
    _title_printed = False


def _command_title(args: argparse.Namespace) -> str:
    daemon_titles: Final[dict[str, str]] = {
        "start": "Daemon Start",
        "run": "Daemon Run",
        "stop": "Daemon Stop",
        "status": "Daemon Status",
    }
    command_titles: Final[dict[str, str]] = {
        "login": "Login",
        "logout": "Logout",
        "reset": "Reset",
        "update": "Update",
        "daemon": daemon_titles.get(
            _as_str_state(getattr(args, "daemon_command", "")), "Daemon"
        ),
        "list": "Activity List",
        "show": "Activity Details",
        "stats": "Ride Statistics",
    }
    return command_titles.get(_as_str_state(getattr(args, "command", "")), "igp-ride")


def _ensure_daemon_management_supported() -> None:
    if is_daemon_management_supported():
        return
    raise DaemonError(
        "Daemon start/stop/status is only supported on macOS. "
        "Use `igp-ride update` or `igp-ride daemon run --once` instead."
    )


def _print_title(title: str, *, file: TextIO | None = None) -> None:
    global _title_printed
    output = _resolve_output(file)
    print(f"== {title} ==", file=output)
    print(file=output)
    _title_printed = True


def _print_field(label: str, value: object, *, file: TextIO | None = None) -> None:
    print(f"{label}: {_format_field_value(value)}", file=_resolve_output(file))


def _print_result(status: str, *, file: TextIO | None = None) -> None:
    _print_field("Result", status, file=file)


def _print_summary(
    items: Sequence[tuple[str, object]],
    *,
    file: TextIO | None = None,
) -> None:
    output = _resolve_output(file)
    payload = " ".join(f"{key}={_format_summary_value(value)}" for key, value in items)
    print(f"Summary: {payload}", file=output)


def _print_next(command: str, *, file: TextIO | None = None) -> None:
    output = _resolve_output(file)
    print(file=output)
    print(f"Next: {command}", file=output)


def _print_tip(message: str, *, file: TextIO | None = None) -> None:
    print(f"Tip: {message}", file=_resolve_output(file))


def _print_warning(message: str, *, file: TextIO | None = None) -> None:
    print(f"Warning: {message}", file=_resolve_output(file))


def _print_error_line(message: str, *, file: TextIO | None = None) -> None:
    print(f"Error: {message}", file=_resolve_output(file))


def _print_error_block(title: str, message: str, tip: str | None = None) -> None:
    if not _title_printed:
        _print_title(title, file=sys.stderr)
    _print_error_line(message, file=sys.stderr)
    if tip:
        _print_tip(tip, file=sys.stderr)


def _format_field_value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _format_summary_value(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _update_mode(force_full: bool, repair: bool) -> str:
    if repair:
        return "repair"
    if force_full:
        return "full"
    return "incremental"


def _print_sync_summary(summary: SyncSummary) -> None:
    _print_summary(
        [
            ("remote", summary.remote_fetched),
            ("new", summary.new_activities),
            ("updated", summary.updated_activities),
            ("skipped", summary.activities_skipped),
            ("fit_failed", summary.fit_files_failed),
        ]
    )


def _summary_items_from_state(state: dict[str, object]) -> list[tuple[str, object]]:
    return [
        ("remote", _as_int_state(state.get("last_remote_fetched"))),
        ("new", _as_int_state(state.get("last_new_activities"))),
        ("updated", _as_int_state(state.get("last_updated_activities"))),
        ("skipped", _as_int_state(state.get("last_activities_skipped"))),
        ("fit_failed", _as_int_state(state.get("last_fit_files_failed"))),
    ]


def _has_sync_summary_state(state: dict[str, object]) -> bool:
    last_run_at = _as_str_state(state.get("last_run_at"))
    if not last_run_at:
        return False
    if _as_str_state(state.get("last_status")) == "ok":
        return True
    return any(value != 0 for _, value in _summary_items_from_state(state))


def _format_local_timestamp(value: str) -> str:
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    if timestamp.tzinfo is None:
        return timestamp.strftime("%Y-%m-%d %H:%M:%S")
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _format_activity_date(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%d")
    return value.astimezone().strftime("%Y-%m-%d")


def _format_activity_timestamp(value: datetime | None) -> str:
    if value is None:
        return "unknown"
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _join_non_empty(parts: Sequence[str]) -> str:
    return " ".join(part for part in parts if part)


def _format_avg_max_metric(
    *,
    avg_value: float,
    max_value: float,
    unit: str,
    precision: int = 0,
) -> str:
    parts: list[str] = []
    if avg_value > 0:
        parts.append(f"{avg_value:.{precision}f} {unit}")
    if max_value > 0:
        parts.append(f"max {max_value:.{precision}f} {unit}")
    return " | ".join(parts)


def _resolve_output(file: TextIO | None) -> TextIO:
    return sys.stdout if file is None else file


def _format_duration_display(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours} h {minutes:02d} m"
    if minutes > 0:
        return f"{minutes} m"
    if secs > 0:
        return f"{secs} s"
    return "0 s"


def _format_list_duration_display(seconds: float) -> str:
    total_seconds = max(int(seconds), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}"
    return str(minutes)


def _format_interval_display(seconds: int) -> str:
    total_seconds = max(seconds, 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0 and minutes > 0:
        return f"{hours}h{minutes}m"
    if hours > 0:
        return f"{hours}h"
    if minutes > 0:
        return f"{minutes}m"
    return f"{secs}s"


if __name__ == "__main__":
    raise SystemExit(main())
