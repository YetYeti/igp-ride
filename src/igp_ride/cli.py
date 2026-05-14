from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from getpass import getpass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Final, Sequence, TextIO

import requests

from igp_ride.client import AuthenticationError, DataSyncError
from igp_ride.config import (
    AppConfig,
    ConfigurationError,
    clear_icu_config,
    save_icu_config,
)
from igp_ride.database import ActivitySortKey, DatabaseError
from igp_ride.icu_client import ICUClientError, IntervalsIcuClient
from igp_ride.models import Activity, SyncSummary
from igp_ride.service import (
    IcuSyncProgress,
    IcuSyncSummary,
    ResetResult,
    RideSyncService,
    SyncProgress,
)
from igp_ride.utils import setup_logging


_title_printed = False
_output_format = "text"
_no_input = False


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
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format. JSON mode writes only JSON to stdout.",
    )
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="Fail instead of prompting for input.",
    )
    subparsers = parser.add_subparsers(dest="command")

    login_parser = subparsers.add_parser("login", help="Log in to cycling website")
    login_parser.add_argument(
        "--username",
        help="IGPSPORT username. Password still comes from stored config, environment, or stdin.",
    )
    login_parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read IGPSPORT password from stdin.",
    )

    logout_parser = subparsers.add_parser(
        "logout", help="Clear local credentials and session"
    )
    logout_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation",
    )
    subparsers.add_parser(
        "status",
        help="Check saved IGPSPORT credentials and session status",
    )
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
        "--all",
        action="store_true",
        help="Force full update of all activities",
    )

    icu_parser = subparsers.add_parser(
        "icu",
        help="Sync local FIT activities to Intervals.icu",
    )
    icu_subparsers = icu_parser.add_subparsers(dest="icu_command", required=True)
    icu_login_parser = icu_subparsers.add_parser(
        "login",
        help="Save Intervals.icu API key",
    )
    icu_login_parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="Read Intervals.icu API key from stdin.",
    )
    icu_logout_parser = icu_subparsers.add_parser(
        "logout",
        help="Clear saved Intervals.icu API key",
    )
    icu_logout_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation",
    )
    icu_subparsers.add_parser(
        "status",
        help="Check saved Intervals.icu API configuration and login status",
    )
    icu_sync_parser = icu_subparsers.add_parser(
        "sync",
        help="Upload local downloaded FIT files to Intervals.icu",
    )
    icu_sync_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be synced without uploading or changing local state",
    )

    list_parser = subparsers.add_parser("list", help="List local activities")
    list_parser.add_argument("--limit", type=int, help="Show at most N activities")
    list_parser.add_argument(
        "--since",
        help="Only show activities on or after DATE (YYYY-MM-DD).",
    )
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

    show_parser = subparsers.add_parser("show", help="Show activity details")
    show_parser.add_argument("activity_id", help="Activity ID or 'last'")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    setup_logging()
    _configure_stderr_buffering()
    parser = build_parser()
    args = parser.parse_args(argv)
    _reset_output_state(output_format=args.format, no_input=args.no_input)
    if args.command is None:
        return cmd_welcome()

    try:
        try:
            if args.command == "login":
                return cmd_login(args.username, args.password_stdin)
            if args.command == "logout":
                return cmd_logout(args.yes)
            if args.command == "status":
                return cmd_status()
            if args.command == "reset":
                return cmd_reset(args.yes)
            if args.command == "update":
                return cmd_update(args.all)
            if args.command == "icu":
                return cmd_icu(args)
            if args.command == "list":
                return cmd_list(
                    args.limit,
                    args.sort,
                    since=_parse_date_arg(args.since, "--since"),
                    descending=not args.asc,
                )
            if args.command == "show":
                return cmd_show(args.activity_id)
        except ConfigurationError as exc:
            _print_error_block(
                _command_title(args),
                str(exc),
                _configuration_error_tip(args, str(exc)),
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
        except FileNotFoundError as exc:
            _print_error_block(_command_title(args), f"File error: {exc}")
            return 7
        except ValueError as exc:
            _print_error_block(_command_title(args), str(exc))
            return 2
        return 0
    finally:
        _reset_output_state()


def cmd_welcome() -> int:
    if _json_output():
        _print_json(
            {
                "command": "welcome",
                "result": "success",
                "next": [
                    "igp-ride login --username USERNAME --password-stdin",
                    "igp-ride update",
                    "igp-ride list",
                ],
            }
        )
        return 0

    _print_title("igp-ride")
    print("Sync IGPSPORT rides to a local database and optional Intervals.icu upload.")
    print()
    print("Quick start:")
    print("  igp-ride login --username USERNAME --password-stdin")
    print("  igp-ride update")
    print("  igp-ride list")
    print()
    print("Common commands:")
    print("  igp-ride show last")
    print("  igp-ride icu login --api-key-stdin")
    print("  igp-ride icu sync --dry-run")
    print()
    print("Run igp-ride --help for all commands.")
    return 0


def cmd_login(username: str | None = None, password_stdin: bool = False) -> int:
    config = AppConfig.load()
    password = _read_secret_stdin("IGPSPORT password") if password_stdin else None
    if _input_disabled():
        if not username and not config.username:
            raise ConfigurationError("Missing username. Pass --username or set IGP_USERNAME.")
        if not password and not config.password:
            raise ConfigurationError(
                "Missing password. Pass --password-stdin or set IGP_PASSWORD."
            )
    service = RideSyncService(config)
    try:
        account, session_path = service.login(username=username, password=password)
    finally:
        service.close()

    if _json_output():
        _print_json(
            {
                "command": "login",
                "result": "success",
                "account": account,
                "path": format_path(session_path),
                "next": ["igp-ride update"],
            }
        )
        return 0

    _print_title("Login")
    _print_result("success")
    _print_field("Account", account)
    _print_field("Path", format_path(session_path))
    _print_next("igp-ride update")
    return 0


def cmd_update(force_full: bool) -> int:
    config = AppConfig.load(require_credentials=True)
    service = RideSyncService(config)
    tty_progress = sys.stderr.isatty() and not _json_output()
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

        if p.stage == "fetching":
            if current_stage != "fetching":
                print("Progress: stage=fetching", file=sys.stderr)
                current_stage = "fetching"
            return

        if p.total <= 0:
            return

        percent = int((p.done / p.total) * 100)
        # Avoid flooding non-interactive outputs; print every 10% and final state.
        if percent < 100 and percent // 10 == last_plain_percent // 10:
            return
        last_plain_percent = percent
        print(
            f"Progress: done={p.done} total={p.total} percent={percent}",
            file=sys.stderr,
        )
        current_stage = "processing"

    try:
        summary = service.sync(force_full=force_full, progress_callback=render_progress)
        repair_summary = service.repair(progress_callback=render_progress)
        summary.updated_activities += repair_summary.updated_activities
        summary.fit_files_failed += repair_summary.fit_files_failed
    finally:
        service.close()

    if tty_progress and current_stage is not None:
        print(file=sys.stderr)

    if _json_output():
        _print_json(
            {
                "command": "update",
                "result": "success",
                "mode": _update_mode(force_full),
                "summary": _sync_summary_payload(summary),
                "warnings": (
                    [f"{summary.fit_files_failed} FIT file(s) failed to download."]
                    if summary.fit_files_failed > 0
                    else []
                ),
                "next": ["igp-ride list"],
            }
        )
        return 0

    _print_result("success")
    _print_field("Mode", _update_mode(force_full))
    _print_sync_summary(summary)
    if summary.fit_files_failed > 0:
        _print_warning(f"{summary.fit_files_failed} FIT file(s) failed to download.")
    _print_next("igp-ride list")
    return 0


def cmd_logout(yes: bool) -> int:
    if not yes:
        if _input_disabled():
            raise ConfigurationError("Confirmation required. Pass --yes to run logout.")
        _print_title("Logout")
        _print_warning("This will clear local IGPSPORT credentials and session.")
        _print_warning("Local activities, FIT files, and ICU config will not be deleted.")
        print()
        confirm = input("Type LOGOUT to confirm: ").strip()
        if confirm != "LOGOUT":
            _print_result("cancelled")
            return 0
    elif not _json_output():
        _print_title("Logout")

    config = AppConfig.load()
    service = RideSyncService(config)
    try:
        service.logout()
    finally:
        service.close()

    if _json_output():
        _print_json(
            {
                "command": "logout",
                "result": "success",
                "path": format_path(config.session_file),
            }
        )
        return 0

    _print_result("success")
    _print_field("Path", format_path(config.session_file))
    return 0


def cmd_status() -> int:
    config = AppConfig.load()
    has_credentials = bool(config.username and config.password)
    session_exists = config.session_file.exists()
    payload: dict[str, object] = {
        "command": "status",
        "result": "success",
        "credentials": has_credentials,
        "session": session_exists,
        "authenticated": False,
    }

    if not _json_output():
        _print_title("Status")
        _print_field("Credentials", has_credentials)
        _print_field("Session", session_exists)

    if not has_credentials:
        if _json_output():
            payload["tips"] = ["Run igp-ride login"]
            _print_json(payload)
            return 0
        _print_field("Authenticated", False)
        _print_tip("Run igp-ride login")
        return 0

    service = RideSyncService(config)
    try:
        try:
            service.client.get_activity_page(page=1, page_size=1)
        except (AuthenticationError, requests.RequestException) as exc:
            if _json_output():
                payload["error"] = str(exc)
                _print_json(payload)
                return 0
            _print_field("Authenticated", False)
            _print_error_line(str(exc))
            return 0
    finally:
        service.close()

    if _json_output():
        payload["authenticated"] = True
        _print_json(payload)
        return 0

    _print_field("Authenticated", True)
    return 0


def cmd_icu(args: argparse.Namespace) -> int:
    if args.icu_command == "login":
        return cmd_icu_login(args.api_key_stdin)
    if args.icu_command == "logout":
        return cmd_icu_logout(args.yes)
    if args.icu_command == "status":
        return cmd_icu_status()
    if args.icu_command == "sync":
        return cmd_icu_sync(args.dry_run)
    raise ValueError(f"Unknown icu command: {args.icu_command}")


def cmd_icu_login(api_key_stdin: bool = False) -> int:
    if api_key_stdin:
        final_api_key = _read_secret_stdin("Intervals.icu API key")
    elif _input_disabled():
        final_api_key = AppConfig.load().icu_api_key
        if not final_api_key:
            raise ConfigurationError(
                "Intervals.icu API key is required. Pass --api-key-stdin or set IGP_RIDE_ICU_API_KEY."
            )
    else:
        final_api_key = getpass("Intervals.icu API key: ").strip()
    config_path = save_icu_config(api_key=final_api_key)

    if _json_output():
        _print_json(
            {
                "command": "icu.login",
                "result": "success",
                "path": format_path(config_path),
                "next": ["igp-ride icu status"],
            }
        )
        return 0

    _print_title("ICU Login")
    _print_result("success")
    _print_field("Path", format_path(config_path))
    _print_next("igp-ride icu status")
    return 0


def cmd_icu_logout(yes: bool) -> int:
    if not yes:
        if _input_disabled():
            raise ConfigurationError("Confirmation required. Pass --yes to run icu logout.")
        _print_title("ICU Logout")
        _print_warning("This will remove the saved Intervals.icu API key.")
        _print_warning("Local activities and ICU sync history will not be deleted.")
        print()
        confirm = input("Type LOGOUT to confirm: ").strip()
        if confirm != "LOGOUT":
            _print_result("cancelled")
            return 0
    elif not _json_output():
        _print_title("ICU Logout")

    clear_icu_config()
    if _json_output():
        _print_json(
            {
                "command": "icu.logout",
                "result": "success",
                "logged_in": False,
            }
        )
        return 0

    _print_result("success")
    _print_field("Logged In", False)
    return 0


def cmd_icu_status() -> int:
    config = AppConfig.load()
    payload: dict[str, object] = {
        "command": "icu.status",
        "result": "success",
        "logged_in": bool(config.icu_api_key),
        "authenticated": False,
    }
    if _json_output():
        if not config.icu_api_key:
            payload["tips"] = ["Run igp-ride icu login"]
            _print_json(payload)
            return 0
    else:
        _print_title("ICU Status")
    if not _json_output():
        _print_field("Logged In", bool(config.icu_api_key))
    if not config.icu_api_key:
        if not _json_output():
            _print_field("Authenticated", False)
            _print_tip("Run igp-ride icu login")
        return 0

    client = IntervalsIcuClient(
        api_key=config.icu_api_key,
    )
    try:
        athlete = client.get_athlete()
    except ICUClientError as exc:
        if _json_output():
            payload["error"] = str(exc)
            _print_json(payload)
            return 0
        _print_field("Authenticated", False)
        _print_error_line(str(exc))
        return 0
    finally:
        client.close()

    if _json_output():
        payload["authenticated"] = True
        athlete_id = athlete.get("id")
        if isinstance(athlete_id, str) and athlete_id:
            payload["remote_athlete_id"] = athlete_id
        athlete_name = athlete.get("name")
        if isinstance(athlete_name, str) and athlete_name:
            payload["name"] = athlete_name
        _print_json(payload)
        return 0

    _print_field("Authenticated", True)
    athlete_id = athlete.get("id")
    if isinstance(athlete_id, str) and athlete_id:
        _print_field("Remote Athlete ID", athlete_id)
    athlete_name = athlete.get("name")
    if isinstance(athlete_name, str) and athlete_name:
        _print_field("Name", athlete_name)
    return 0


def cmd_icu_sync(dry_run: bool) -> int:
    config = AppConfig.load()
    service = RideSyncService(config)
    tty_progress = sys.stderr.isatty() and not _json_output()
    last_plain_percent = -1

    def render_progress(p: IcuSyncProgress) -> None:
        nonlocal last_plain_percent
        if p.total <= 0:
            return
        percent = int((p.done / p.total) * 100)
        if tty_progress:
            print(
                "\r\033[2K"
                f"Progress: done={p.done} total={p.total} percent={percent}"
                f" | uploaded {p.uploaded}"
                f" | remote {p.already_remote}"
                f" | skipped {p.skipped}"
                f" | failed {p.failed} ",
                end="",
                file=sys.stderr,
                flush=True,
            )
            return

        if percent < 100 and percent // 10 == last_plain_percent // 10:
            return
        last_plain_percent = percent
        print(
            f"Progress: done={p.done} total={p.total} percent={percent}",
            file=sys.stderr,
        )

    try:
        summary = service.sync_icu(
            dry_run=dry_run,
            progress_callback=None if _json_output() else render_progress,
        )
    finally:
        service.close()

    if tty_progress and summary.candidates > 0:
        print(file=sys.stderr)

    if _json_output():
        _print_json(
            {
                "command": "icu.sync",
                "result": "success",
                "mode": "dry-run" if dry_run else "upload",
                "summary": _icu_sync_summary_payload(summary),
                "next": ["igp-ride icu sync"] if dry_run else [],
            }
        )
        return 0

    _print_title("ICU Sync")
    _print_result("success")
    _print_field("Mode", "dry-run" if dry_run else "upload")
    _print_icu_sync_summary(summary)
    if dry_run:
        _print_next("igp-ride icu sync")
    return 0


def cmd_list(
    limit: int | None,
    sort_by: ActivitySortKey = "date",
    *,
    since: date | None = None,
    descending: bool = True,
) -> int:
    config = AppConfig.load()
    service = RideSyncService(config)
    try:
        activities = service.list_activities(
            limit=limit,
            since=since,
            sort_by=sort_by,
            descending=descending,
        )
    finally:
        service.close()

    if _json_output():
        _print_json(
            {
                "command": "list",
                "result": "success",
                "limit": limit,
                "since": since.isoformat() if since is not None else None,
                "sort": sort_by,
                "descending": descending,
                "count": len(activities),
                "activities": [_activity_list_payload(activity) for activity in activities],
                "tips": (
                    ["Run igp-ride update to download activities from IGPSPORT"]
                    if not activities
                    else []
                ),
            }
        )
        return 0

    _print_title("Activity List")
    if not activities:
        _print_field("Count", 0)
        _print_tip("Run igp-ride update to download activities from IGPSPORT")
        return 0

    if limit is not None:
        _print_field("Limit", limit)
    else:
        _print_field("Count", len(activities))
    if since is not None:
        _print_field("Since", since.isoformat())
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

def cmd_reset(yes: bool) -> int:
    config = AppConfig.load()
    if not yes:
        if _input_disabled():
            raise ConfigurationError("Confirmation required. Pass --yes to run reset.")
        _print_title("Reset")
        _print_warning("This will permanently delete all local igp-ride data.")
        _print_warning(
            "Saved credentials and session data will also be removed."
        )
        _print_field("Data Path", format_path(config.data_dir))
        _print_field("Config Path", format_path(config.session_file.parent))
        print()
        confirm = input("Type RESET to confirm: ").strip()
        if confirm != "RESET":
            _print_result("cancelled")
            return 0
    elif not _json_output():
        _print_title("Reset")

    service = RideSyncService(config)
    try:
        results = service.reset()
    finally:
        service.close()

    has_failure = any(item.status == "failed" for item in results)
    if _json_output():
        _print_json(_reset_payload(results))
        return 10 if has_failure else 0

    print_reset_summary(results)
    return 10 if has_failure else 0


def cmd_show(activity_id: str) -> int:
    config = AppConfig.load()
    service = RideSyncService(config)
    try:
        if activity_id == "last":
            activity = service.get_latest_activity()
        elif activity_id.isdecimal():
            activity = service.show_activity(int(activity_id))
        else:
            raise ValueError("Activity ID must be a number or 'last'.")
    finally:
        service.close()

    if activity is None:
        if _json_output():
            _print_json(
                {
                    "command": "show",
                    "result": "error",
                    "activity_id": activity_id,
                    "error": (
                        "No activities found"
                        if activity_id == "last"
                        else f"Activity not found: {activity_id}"
                    ),
                    "tips": [
                        (
                            "Run igp-ride update to download activities first"
                            if activity_id == "last"
                            else "Run igp-ride list to see available activities"
                        )
                    ],
                }
            )
            return 8

        _print_title("Activity Details")
        if activity_id == "last":
            _print_error_line("No activities found")
            _print_tip("Run igp-ride update to download activities first")
        else:
            _print_error_line(f"Activity not found: {activity_id}")
            _print_tip("Run igp-ride list to see available activities")
        return 8

    if _json_output():
        _print_json(
            {
                "command": "show",
                "result": "success",
                "activity": _activity_detail_payload(activity),
            }
        )
        return 0

    _print_title("Activity Details")
    print_activity(activity)
    return 0


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


def _as_str_state(value: object) -> str:
    return value if isinstance(value, str) else ""


def _reset_output_state(*, output_format: str = "text", no_input: bool = False) -> None:
    global _title_printed, _output_format, _no_input
    _title_printed = False
    _output_format = output_format
    _no_input = no_input


def _json_output() -> bool:
    return _output_format == "json"


def _input_disabled() -> bool:
    return _no_input or _json_output()


def _read_secret_stdin(label: str) -> str:
    value = sys.stdin.read().strip()
    if not value:
        raise ConfigurationError(f"{label} is required on stdin.")
    return value


def _parse_date_arg(value: str | None, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{option} must be a date in YYYY-MM-DD format.") from exc


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _configure_stderr_buffering() -> None:
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if sys.stderr.isatty() or not callable(reconfigure):
        return
    try:
        reconfigure(line_buffering=True)
    except (AttributeError, TypeError, ValueError):
        pass


def _command_title(args: argparse.Namespace) -> str:
    command_titles: Final[dict[str, str]] = {
        "login": "Login",
        "logout": "Logout",
        "status": "Status",
        "reset": "Reset",
        "update": "Update",
        "icu": _icu_command_title(args),
        "list": "Activity List",
        "show": "Activity Details",
    }
    return command_titles.get(_as_str_state(getattr(args, "command", "")), "igp-ride")


def _icu_command_title(args: argparse.Namespace) -> str:
    titles: Final[dict[str, str]] = {
        "login": "ICU Login",
        "logout": "ICU Logout",
        "status": "ICU Status",
        "sync": "ICU Sync",
    }
    return titles.get(_as_str_state(getattr(args, "icu_command", "")), "ICU")


def _configuration_error_tip(args: argparse.Namespace, message: str) -> str | None:
    if message.startswith("Confirmation required."):
        if _as_str_state(getattr(args, "command", "")) == "icu":
            return f"Run igp-ride icu {getattr(args, 'icu_command', '')} --yes"
        return f"Run igp-ride {getattr(args, 'command', '')} --yes"
    if "Missing username" in message or "Missing password" in message:
        return "Set IGP_USERNAME/IGP_PASSWORD or use login --username with --password-stdin"
    if "Intervals.icu API key" in message:
        return "Set IGP_RIDE_ICU_API_KEY or use icu login --api-key-stdin"
    return "Run igp-ride login first"


def _print_title(title: str, *, file: TextIO | None = None) -> None:
    if _json_output():
        return
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
    if file is None:
        file = sys.stderr
    print(f"Warning: {message}", file=_resolve_output(file))


def _print_error_line(message: str, *, file: TextIO | None = None) -> None:
    print(f"Error: {message}", file=_resolve_output(file))


def _print_error_block(title: str, message: str, tip: str | None = None) -> None:
    if _json_output():
        payload: dict[str, object] = {
            "command": _json_command_from_title(title),
            "result": "error",
            "error": message,
        }
        if tip:
            payload["tips"] = [tip]
        _print_json(payload)
        return
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


def _update_mode(force_full: bool) -> str:
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


def _sync_summary_payload(summary: SyncSummary) -> dict[str, int]:
    return {
        "remote": summary.remote_fetched,
        "new": summary.new_activities,
        "updated": summary.updated_activities,
        "skipped": summary.activities_skipped,
        "fit_failed": summary.fit_files_failed,
    }


def _print_icu_sync_summary(summary: IcuSyncSummary) -> None:
    _print_summary(
        [
            ("candidates", summary.candidates),
            ("uploaded", summary.uploaded),
            ("already_remote", summary.already_remote),
            ("skipped", summary.skipped),
            ("failed", summary.failed),
            ("dry_run", summary.dry_run),
        ]
    )


def _icu_sync_summary_payload(summary: IcuSyncSummary) -> dict[str, int | bool]:
    return {
        "candidates": summary.candidates,
        "uploaded": summary.uploaded,
        "already_remote": summary.already_remote,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "dry_run": summary.dry_run,
    }


def _reset_payload(results: list[ResetResult]) -> dict[str, object]:
    deleted = sum(1 for item in results if item.status == "deleted")
    not_found = sum(1 for item in results if item.status == "not_found")
    failed = sum(1 for item in results if item.status == "failed")
    return {
        "command": "reset",
        "result": "partial" if failed > 0 else "success",
        "items": [
            {
                "path": format_path(item.path),
                "status": item.status,
                "error": item.error,
            }
            for item in results
        ],
        "summary": {
            "deleted": deleted,
            "not_found": not_found,
            "failed": failed,
        },
    }


def _activity_list_payload(activity: Activity) -> dict[str, object]:
    return {
        "ride_id": activity.ride_id,
        "title": format_activity_name(activity.title),
        "start_time": _format_json_datetime(activity.start_time),
        "distance_m": activity.total_distance,
        "moving_time_s": activity.total_moving_time,
        "elapsed_time_s": activity.total_elapsed_time,
        "ascent_m": activity.total_ascent,
        "avg_speed_mps": activity.avg_speed,
        "avg_power_w": activity.avg_power,
    }


def _activity_detail_payload(activity: Activity) -> dict[str, object]:
    payload = _activity_list_payload(activity)
    payload.update(
        {
            "member_id": activity.member_id,
            "sport": activity.sport,
            "sub_sport": activity.sub_sport,
            "descent_m": activity.total_descent,
            "calories_kcal": activity.total_calories,
            "avg_cadence_rpm": activity.avg_cadence,
            "max_cadence_rpm": activity.max_cadence,
            "avg_heart_rate_bpm": activity.avg_heart_rate,
            "max_heart_rate_bpm": activity.max_heart_rate,
            "max_power_w": activity.max_power,
            "normalized_power_w": activity.normalized_power,
            "intensity_factor": activity.intensity_factor,
            "training_stress_score": activity.training_stress_score,
            "max_speed_mps": activity.max_speed,
            "fit_file_path": activity.fit_file_path,
            "fit_file_status": activity.fit_file_status,
            "icu_activity_id": activity.icu_activity_id,
            "icu_external_id": activity.icu_external_id,
            "icu_sync_status": activity.icu_sync_status,
            "icu_sync_error": activity.icu_sync_error,
        }
    )
    return payload


def _format_json_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_command_from_title(title: str) -> str:
    return title.lower().replace(" ", ".")


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


if __name__ == "__main__":
    raise SystemExit(main())
