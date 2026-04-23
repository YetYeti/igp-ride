from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from getpass import getpass
from pathlib import Path
from typing import Any, Callable

from igp_ride.client import DataSyncError, IGPSportClient
from igp_ride.config import (
    AppConfig,
    delete_credentials,
    delete_session_data,
    save_credentials,
)

from igp_ride.database import ActivityDatabase, ActivitySortKey
from igp_ride.models import Activity, PeriodStats, SyncSummary
from igp_ride.parser import FitParseError, normalize_session_data, parse_fit_file
from igp_ride.utils import get_logger


logger = get_logger(__name__)
MAX_ACTIVITY_PAGES = 1000


def _calculate_fetch_limits(last_sync_time: str | None) -> tuple[int, int]:
    """Return (page_size, max_pages) based on time since last sync."""
    if last_sync_time is None:
        return 200, MAX_ACTIVITY_PAGES  # full sync
    last_sync = datetime.fromisoformat(last_sync_time).date()
    day_gap = max(1, (date.today() - last_sync).days)
    page_size = day_gap * 5
    return page_size, 1  # incremental: 1 HTTP request


@dataclass(slots=True)
class ResetResult:
    path: Path
    status: str
    error: str = ""


@dataclass(slots=True)
class SyncProgress:
    stage: str
    done: int
    total: int
    new_activities: int = 0
    updated_activities: int = 0
    activities_skipped: int = 0
    fit_files_failed: int = 0
    current_ride_id: int | None = None


class RideSyncService:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db = ActivityDatabase(config.db_path)
        self.client = IGPSportClient(
            username=config.username,
            password=config.password,
            base_url=config.base_url,
            session_path=config.session_file,
        )

    def close(self) -> None:
        self.client.close()
        self.db.close()

    def login(
        self,
        *,
        username: str | None = None,
        password: str | None = None,
    ) -> tuple[str, Path]:
        final_username = username or self.config.username or input("Username: ").strip()
        final_password = password or self.config.password or getpass("Password: ")
        if not final_username or not final_password:
            raise ValueError("Username and password are required.")

        logger.info("Logging in as: %s", final_username)
        self.client.username = final_username
        self.client.password = final_password
        self.client.login()
        save_credentials(final_username, final_password)
        logger.info("Credentials saved")
        return final_username, self.config.session_file

    def logout(self) -> bool:
        logger.info("Logging out")

        if self.client.username:
            delete_credentials(self.client.username)
            delete_session_data(self.client.username)
        if self.config.session_file.exists():
            self.config.session_file.unlink()
            logger.debug("Session removed: %s", self.config.session_file)

        logger.info("Logout completed")
        return True

    def reset(self) -> list[ResetResult]:
        logger.info("Resetting all local data")
        self.db.close()
        self.client.close()
        if self.client.username:
            delete_credentials(self.client.username)
            delete_session_data(self.client.username)

        # The app stores runtime state under XDG config/data roots.
        targets = [self.config.data_dir, self.config.session_file.parent]
        results: list[ResetResult] = []
        for target in targets:
            if not target.exists():
                results.append(ResetResult(path=target, status="not_found"))
                continue
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                results.append(ResetResult(path=target, status="deleted"))
            except OSError as exc:
                results.append(
                    ResetResult(path=target, status="failed", error=str(exc))
                )
        return results

    def sync(
        self,
        force_full: bool = False,
        progress_callback: Callable[[SyncProgress], None] | None = None,
    ) -> SyncSummary:
        # Determine sync mode
        last_sync_time: str | None = None
        if not force_full:
            last_sync_time = self.db.get_sync_meta("last_sync_time")
            if last_sync_time:
                logger.info("Incremental sync since: %s", last_sync_time)
            else:
                logger.info("No last_sync_time found, performing full sync")
        else:
            logger.info("Force full sync requested")

        page_size, max_pages = _calculate_fetch_limits(last_sync_time)
        logger.info("Sync params: page_size=%d, max_pages=%d", page_size, max_pages)

        summary = SyncSummary()
        all_remote, total, page_count = self._fetch_all_remote_activities(
            page_size=page_size,
            max_pages=max_pages,
            progress_callback=progress_callback,
        )
        if not all_remote:
            return summary

        summary.remote_fetched = len(all_remote)
        total_items = summary.remote_fetched
        if progress_callback is not None:
            progress_callback(
                SyncProgress(
                    stage="processing",
                    done=0,
                    total=total_items,
                )
            )
        logger.debug(
            "Fetched remote activities: %d items across %d page(s), total=%s",
            len(all_remote),
            page_count,
            total,
        )

        local_ride_ids = self.db.get_all_ride_ids()
        logger.debug(
            "Local activities: %d, Remote activities: %d",
            len(local_ride_ids),
            len(all_remote),
        )

        for index, raw_activity in enumerate(all_remote, start=1):
            ride_id = _as_int(raw_activity.get("RideId"))
            try:
                if ride_id <= 0:
                    continue

                is_existing = ride_id in local_ride_ids
                fit_path = self.config.fit_dir / f"{ride_id}.fit"
                needs_fit_download = not fit_path.exists()

                # Skip when both record and FIT already exist locally.
                if is_existing and not needs_fit_download:
                    logger.debug("Skipping ride %d: already exists", ride_id)
                    summary.activities_skipped += 1
                    continue

                fit_status = "downloaded"
                if needs_fit_download:
                    try:
                        self.client.download_fit_file(ride_id, fit_path)
                    except DataSyncError as e:
                        logger.warning(
                            "Failed to download FIT for ride %d: %s", ride_id, e
                        )
                        fit_status = "missing"
                        summary.fit_files_failed += 1

                activity = self._build_activity(raw_activity, fit_path, fit_status)
                self.db.upsert(activity)
                if is_existing:
                    summary.updated_activities += 1
                    logger.debug("Activity updated: ride_id=%d", ride_id)
                else:
                    summary.new_activities += 1
                    logger.debug("New activity added: ride_id=%d", ride_id)
                    local_ride_ids.add(ride_id)
            finally:
                if progress_callback is not None:
                    progress_callback(
                        SyncProgress(
                            stage="processing",
                            done=index,
                            total=total_items,
                            new_activities=summary.new_activities,
                            updated_activities=summary.updated_activities,
                            activities_skipped=summary.activities_skipped,
                            fit_files_failed=summary.fit_files_failed,
                            current_ride_id=ride_id if ride_id > 0 else None,
                        )
                    )

        logger.info(
            "Sync completed: %d new, %d updated, %d skipped, %d failed",
            summary.new_activities,
            summary.updated_activities,
            summary.activities_skipped,
            summary.fit_files_failed,
        )
        self.db.set_sync_meta("last_sync_time", datetime.now(UTC).isoformat())
        return summary

    def _fetch_all_remote_activities(
        self,
        *,
        page_size: int,
        max_pages: int | None = None,
        progress_callback: Callable[[SyncProgress], None] | None = None,
    ) -> tuple[list[dict[str, object]], int | None, int]:
        page = 1
        total: int | None = None
        all_items: list[dict[str, object]] = []
        fetched_pages = 0

        if progress_callback is not None:
            progress_callback(
                SyncProgress(
                    stage="fetching",
                    done=0,
                    total=0,
                )
            )

        effective_max_pages = max_pages if max_pages is not None else MAX_ACTIVITY_PAGES
        while page <= effective_max_pages:
            items, page_total = self.client.get_activity_page(
                page=page, page_size=page_size
            )
            if total is None and page_total is not None:
                total = page_total
            if not items:
                break

            fetched_pages += 1
            all_items.extend(items)
            if progress_callback is not None:
                progress_callback(
                    SyncProgress(
                        stage="fetching",
                        done=len(all_items),
                        total=total or len(all_items),
                    )
                )
            if total is not None and len(all_items) >= total:
                break
            page += 1

        if fetched_pages >= MAX_ACTIVITY_PAGES and (
            total is None or len(all_items) < total
        ):
            logger.warning("Stopped fetching at max pages: %d.", MAX_ACTIVITY_PAGES)

        return all_items, total, fetched_pages

    def list_activities(
        self,
        *,
        limit: int | None = None,
        since: date | None = None,
        sort_by: ActivitySortKey = "date",
        descending: bool = True,
    ) -> list[Activity]:
        return self.db.list_activities(
            limit=limit,
            since=since,
            sort_by=sort_by,
            descending=descending,
        )

    def get_stats(
        self,
        *,
        group_by: str = "month",
        year: int | None = None,
        activity_type: str | None = None,
    ) -> list[PeriodStats]:
        return self.db.get_stats(
            group_by=group_by, year=year, activity_type=activity_type
        )

    def repair(
        self,
        progress_callback: Callable[[SyncProgress], None] | None = None,
    ) -> SyncSummary:
        logger.info("Starting FIT file repair")
        broken = self.db.get_activities_with_missing_fit()
        summary = SyncSummary(remote_fetched=len(broken))
        if not broken:
            return summary

        total_items = len(broken)
        if progress_callback is not None:
            progress_callback(
                SyncProgress(stage="processing", done=0, total=total_items)
            )

        for index, activity in enumerate(broken, start=1):
            ride_id = activity.ride_id
            fit_path = self.config.fit_dir / f"{ride_id}.fit"
            fit_status = "downloaded"
            try:
                self.client.download_fit_file(ride_id, fit_path)
                # Re-parse the newly downloaded FIT file
                parsed_session: dict[str, Any] = {}
                try:
                    parsed_session = normalize_session_data(
                        parse_fit_file(str(fit_path))
                    )
                except FitParseError:
                    fit_status = "invalid"

                updated = self._build_activity_from_existing(
                    activity, parsed_session, fit_path, fit_status
                )
                self.db.upsert(updated)
                summary.updated_activities += 1
                logger.debug("Repaired FIT for ride %d", ride_id)
            except DataSyncError as e:
                logger.warning("Failed to repair FIT for ride %d: %s", ride_id, e)
                summary.fit_files_failed += 1
            finally:
                if progress_callback is not None:
                    progress_callback(
                        SyncProgress(
                            stage="processing",
                            done=index,
                            total=total_items,
                            updated_activities=summary.updated_activities,
                            fit_files_failed=summary.fit_files_failed,
                            current_ride_id=ride_id,
                        )
                    )

        logger.info(
            "Repair completed: %d repaired, %d failed",
            summary.updated_activities,
            summary.fit_files_failed,
        )
        return summary

    def show_activity(self, ride_id: int) -> Activity | None:
        return self.db.get_by_ride_id(ride_id)

    def get_latest_activity(self) -> Activity | None:
        return self.db.get_latest_activity()

    def _build_activity(
        self,
        raw_activity: dict[str, Any],
        fit_path: Path,
        fit_status: str,
    ) -> Activity:
        parsed_session: dict[str, Any] = {}
        if fit_path.exists():
            try:
                parsed_session = normalize_session_data(parse_fit_file(str(fit_path)))
            except FitParseError:
                fit_status = "invalid"

        start_time = parsed_session.get("start_time")
        if start_time is None:
            start_time = _parse_start_time(raw_activity)

        return Activity(
            ride_id=_as_int(raw_activity.get("RideId")),
            member_id=_as_int(raw_activity.get("MemberId")),
            title=_as_str(raw_activity.get("Title"), "Untitled Ride"),
            sport=_as_str(parsed_session.get("sport"), "cycling"),
            sub_sport=_as_str(parsed_session.get("sub_sport"), "road"),
            start_time=start_time,
            total_ascent=_as_int(
                parsed_session.get("total_ascent", raw_activity.get("TotalAscent"))
            ),
            total_descent=_as_int(parsed_session.get("total_descent")),
            total_calories=_as_int(parsed_session.get("total_calories")),
            total_distance=_as_float(
                parsed_session.get(
                    "total_distance",
                    _as_float(raw_activity.get("RideDistance", 0.0)) * 1000,
                )
            ),
            total_elapsed_time=_as_float(parsed_session.get("total_elapsed_time")),
            total_moving_time=_as_float(parsed_session.get("total_moving_time")),
            avg_cadence=_as_int(parsed_session.get("avg_cadence")),
            max_cadence=_as_int(parsed_session.get("max_cadence")),
            avg_heart_rate=_as_int(parsed_session.get("avg_heart_rate")),
            min_heart_rate=_as_int(parsed_session.get("min_heart_rate")),
            max_heart_rate=_as_int(parsed_session.get("max_heart_rate")),
            avg_power=_as_int(parsed_session.get("avg_power")),
            max_power=_as_int(parsed_session.get("max_power")),
            avg_speed=_as_float(parsed_session.get("avg_speed")),
            max_speed=_as_float(parsed_session.get("max_speed")),
            avg_temperature=_as_int(parsed_session.get("avg_temperature")),
            max_temperature=_as_int(parsed_session.get("max_temperature")),
            intensity_factor=_as_float(parsed_session.get("intensity_factor")),
            normalized_power=_as_int(parsed_session.get("normalized_power")),
            training_stress_score=_as_float(
                parsed_session.get("training_stress_score")
            ),
            fit_file_path=str(fit_path),
            fit_file_status=fit_status,
        )

    def _build_activity_from_existing(
        self,
        existing: Activity,
        parsed_session: dict[str, Any],
        fit_path: Path,
        fit_status: str,
    ) -> Activity:
        start_time = parsed_session.get("start_time") or existing.start_time
        return Activity(
            ride_id=existing.ride_id,
            member_id=existing.member_id,
            title=existing.title,
            sport=_as_str(parsed_session.get("sport"), existing.sport),
            sub_sport=_as_str(parsed_session.get("sub_sport"), existing.sub_sport),
            start_time=start_time,
            total_ascent=_as_int(
                parsed_session.get("total_ascent"), existing.total_ascent
            ),
            total_descent=_as_int(
                parsed_session.get("total_descent"), existing.total_descent
            ),
            total_calories=_as_int(
                parsed_session.get("total_calories"), existing.total_calories
            ),
            total_distance=_as_float(
                parsed_session.get("total_distance"), existing.total_distance
            ),
            total_elapsed_time=_as_float(
                parsed_session.get("total_elapsed_time"), existing.total_elapsed_time
            ),
            total_moving_time=_as_float(
                parsed_session.get("total_moving_time"), existing.total_moving_time
            ),
            avg_cadence=_as_int(
                parsed_session.get("avg_cadence"), existing.avg_cadence
            ),
            max_cadence=_as_int(
                parsed_session.get("max_cadence"), existing.max_cadence
            ),
            avg_heart_rate=_as_int(
                parsed_session.get("avg_heart_rate"), existing.avg_heart_rate
            ),
            min_heart_rate=_as_int(
                parsed_session.get("min_heart_rate"), existing.min_heart_rate
            ),
            max_heart_rate=_as_int(
                parsed_session.get("max_heart_rate"), existing.max_heart_rate
            ),
            avg_power=_as_int(parsed_session.get("avg_power"), existing.avg_power),
            max_power=_as_int(parsed_session.get("max_power"), existing.max_power),
            avg_speed=_as_float(parsed_session.get("avg_speed"), existing.avg_speed),
            max_speed=_as_float(parsed_session.get("max_speed"), existing.max_speed),
            avg_temperature=_as_int(
                parsed_session.get("avg_temperature"), existing.avg_temperature
            ),
            max_temperature=_as_int(
                parsed_session.get("max_temperature"), existing.max_temperature
            ),
            intensity_factor=_as_float(
                parsed_session.get("intensity_factor"), existing.intensity_factor
            ),
            normalized_power=_as_int(
                parsed_session.get("normalized_power"), existing.normalized_power
            ),
            training_stress_score=_as_float(
                parsed_session.get("training_stress_score"),
                existing.training_stress_score,
            ),
            fit_file_path=str(fit_path),
            fit_file_status=fit_status,
        )


def _parse_start_time(raw_activity: dict[str, Any]) -> datetime | None:
    for key in ("StartTime", "startTime", "StartDate", "start_date"):
        value = raw_activity.get(key)
        if not isinstance(value, str) or not value:
            continue
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            continue
    return None


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_str(value: object, default: str = "") -> str:
    if isinstance(value, str) and value:
        return value
    return default
