from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from igp_ride.models import Activity, PeriodStats
from igp_ride.utils import ensure_dir, get_logger


logger = get_logger(__name__)


class DatabaseError(Exception):
    pass


class ActivityDatabase:
    def __init__(self, db_path: Path):
        ensure_dir(db_path.parent)
        self._db_path = db_path
        self._connection: sqlite3.Connection | None = None
        logger.debug("Initializing database: %s", db_path)
        self._ensure_database()
        logger.debug("Database initialized")

    def close(self) -> None:
        if self._connection is not None:
            logger.debug("Closing database connection")
            self._connection.close()
            self._connection = None

    def get_by_ride_id(self, ride_id: int) -> Activity | None:
        cursor = self._get_connection().cursor()
        cursor.execute("SELECT * FROM activities WHERE ride_id = ?", (ride_id,))
        row = cursor.fetchone()
        return self._row_to_activity(row) if row is not None else None

    def get_latest_activity(self) -> Activity | None:
        cursor = self._get_connection().cursor()
        cursor.execute("SELECT * FROM activities ORDER BY start_time DESC LIMIT 1")
        row = cursor.fetchone()
        return self._row_to_activity(row) if row is not None else None

    def get_all_ride_ids(self) -> set[int]:
        cursor = self._get_connection().cursor()
        cursor.execute("SELECT ride_id FROM activities")
        return {int(row["ride_id"]) for row in cursor.fetchall()}

    def list_activities(
        self, *, limit: int | None = None, since: date | None = None
    ) -> list[Activity]:
        query = "SELECT * FROM activities"
        params: list[object] = []
        if since is not None:
            query += " WHERE date(start_time) >= ?"
            params.append(since.isoformat())
        query += " ORDER BY start_time DESC, ride_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        cursor = self._get_connection().cursor()
        cursor.execute(query, tuple(params))
        return [self._row_to_activity(row) for row in cursor.fetchall()]

    def get_activities_with_missing_fit(self) -> list[Activity]:
        cursor = self._get_connection().cursor()
        cursor.execute(
            "SELECT * FROM activities WHERE fit_file_status IN ('missing', 'invalid')"
        )
        return [self._row_to_activity(row) for row in cursor.fetchall()]

    def get_stats(
        self,
        *,
        group_by: str = "month",
        year: int | None = None,
        activity_type: str | None = None,
    ) -> list[PeriodStats]:
        if group_by == "year":
            period_expr = "strftime('%Y', start_time)"
        else:
            period_expr = "strftime('%Y-%m', start_time)"

        query = f"""
            SELECT
                {period_expr} AS period,
                COUNT(*) AS count,
                COALESCE(SUM(total_distance), 0) AS total_distance,
                COALESCE(SUM(total_moving_time), 0) AS total_moving_time,
                CASE WHEN SUM(total_distance) > 0
                    THEN SUM(total_distance * avg_speed) / SUM(total_distance)
                    ELSE 0 END AS avg_speed,
                CASE WHEN SUM(total_distance) > 0
                    THEN SUM(total_distance * avg_power) / SUM(total_distance)
                    ELSE 0 END AS avg_power,
                COALESCE(SUM(total_ascent), 0) AS total_ascent
            FROM activities
            WHERE start_time IS NOT NULL
        """
        params: list[object] = []
        if year is not None:
            query += " AND strftime('%Y', start_time) = ?"
            params.append(str(year))
        if activity_type is not None:
            query += " AND title = ?"
            params.append(activity_type)
        query += f" GROUP BY {period_expr} ORDER BY period DESC"

        cursor = self._get_connection().cursor()
        cursor.execute(query, tuple(params))
        return [
            PeriodStats(
                period=row["period"],
                count=row["count"],
                total_distance=row["total_distance"],
                total_moving_time=row["total_moving_time"],
                avg_speed=row["avg_speed"],
                avg_power=row["avg_power"],
                total_ascent=row["total_ascent"],
            )
            for row in cursor.fetchall()
        ]

    def upsert(self, activity: Activity) -> None:
        logger.debug(
            "Upserting activity: ride_id=%d, title=%s", activity.ride_id, activity.title
        )
        cursor = self._get_connection().cursor()
        payload = (
            activity.ride_id,
            activity.member_id,
            activity.title,
            activity.sport,
            activity.sub_sport,
            _to_iso(activity.start_time),
            activity.total_ascent,
            activity.total_descent,
            activity.total_calories,
            activity.total_distance,
            activity.total_elapsed_time,
            activity.total_moving_time,
            activity.avg_cadence,
            activity.max_cadence,
            activity.avg_heart_rate,
            activity.min_heart_rate,
            activity.max_heart_rate,
            activity.avg_power,
            activity.max_power,
            activity.avg_speed,
            activity.max_speed,
            activity.avg_temperature,
            activity.max_temperature,
            activity.intensity_factor,
            activity.normalized_power,
            activity.training_stress_score,
            activity.fit_file_path,
            activity.fit_file_status,
        )
        cursor.execute(
            """
            INSERT INTO activities (
                ride_id, member_id, title, sport, sub_sport, start_time,
                total_ascent, total_descent, total_calories, total_distance,
                total_elapsed_time, total_moving_time, avg_cadence, max_cadence,
                avg_heart_rate, min_heart_rate, max_heart_rate, avg_power, max_power,
                avg_speed, max_speed, avg_temperature, max_temperature,
                intensity_factor, normalized_power, training_stress_score,
                fit_file_path, fit_file_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ride_id) DO UPDATE SET
                member_id = excluded.member_id,
                title = excluded.title,
                sport = excluded.sport,
                sub_sport = excluded.sub_sport,
                start_time = excluded.start_time,
                total_ascent = excluded.total_ascent,
                total_descent = excluded.total_descent,
                total_calories = excluded.total_calories,
                total_distance = excluded.total_distance,
                total_elapsed_time = excluded.total_elapsed_time,
                total_moving_time = excluded.total_moving_time,
                avg_cadence = excluded.avg_cadence,
                max_cadence = excluded.max_cadence,
                avg_heart_rate = excluded.avg_heart_rate,
                min_heart_rate = excluded.min_heart_rate,
                max_heart_rate = excluded.max_heart_rate,
                avg_power = excluded.avg_power,
                max_power = excluded.max_power,
                avg_speed = excluded.avg_speed,
                max_speed = excluded.max_speed,
                avg_temperature = excluded.avg_temperature,
                max_temperature = excluded.max_temperature,
                intensity_factor = excluded.intensity_factor,
                normalized_power = excluded.normalized_power,
                training_stress_score = excluded.training_stress_score,
                fit_file_path = excluded.fit_file_path,
                fit_file_status = excluded.fit_file_status,
                updated_at = CURRENT_TIMESTAMP
            """,
            payload,
        )
        self._get_connection().commit()
        logger.debug("Activity upserted: ride_id=%d", activity.ride_id)

    def _ensure_database(self) -> None:
        cursor = self._get_connection().cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS activities (
                ride_id INTEGER PRIMARY KEY,
                member_id INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT '',
                sport TEXT NOT NULL DEFAULT 'cycling',
                sub_sport TEXT NOT NULL DEFAULT 'road',
                start_time TEXT,
                total_ascent INTEGER NOT NULL DEFAULT 0,
                total_descent INTEGER NOT NULL DEFAULT 0,
                total_calories INTEGER NOT NULL DEFAULT 0,
                total_distance REAL NOT NULL DEFAULT 0,
                total_elapsed_time REAL NOT NULL DEFAULT 0,
                total_moving_time REAL NOT NULL DEFAULT 0,
                avg_cadence INTEGER,
                max_cadence INTEGER,
                avg_heart_rate INTEGER,
                min_heart_rate INTEGER,
                max_heart_rate INTEGER,
                avg_power INTEGER,
                max_power INTEGER,
                avg_speed REAL NOT NULL DEFAULT 0,
                max_speed REAL NOT NULL DEFAULT 0,
                avg_temperature INTEGER,
                max_temperature INTEGER,
                intensity_factor REAL,
                normalized_power INTEGER,
                training_stress_score REAL,
                fit_file_path TEXT NOT NULL,
                fit_file_status TEXT NOT NULL DEFAULT 'missing',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._get_connection().commit()

    def get_sync_meta(self, key: str) -> str | None:
        cursor = self._get_connection().cursor()
        cursor.execute("SELECT value FROM sync_meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else None

    def set_sync_meta(self, key: str, value: str) -> None:
        cursor = self._get_connection().cursor()
        cursor.execute(
            "INSERT INTO sync_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._get_connection().commit()

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(self._db_path)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def _row_to_activity(self, row: sqlite3.Row) -> Activity:
        return Activity(
            ride_id=row["ride_id"],
            member_id=row["member_id"],
            title=row["title"],
            sport=row["sport"],
            sub_sport=row["sub_sport"],
            start_time=_from_iso(row["start_time"]),
            total_ascent=row["total_ascent"],
            total_descent=row["total_descent"],
            total_calories=row["total_calories"],
            total_distance=row["total_distance"],
            total_elapsed_time=row["total_elapsed_time"],
            total_moving_time=row["total_moving_time"],
            avg_cadence=row["avg_cadence"] or 0,
            max_cadence=row["max_cadence"] or 0,
            avg_heart_rate=row["avg_heart_rate"] or 0,
            min_heart_rate=row["min_heart_rate"] or 0,
            max_heart_rate=row["max_heart_rate"] or 0,
            avg_power=row["avg_power"] or 0,
            max_power=row["max_power"] or 0,
            avg_speed=row["avg_speed"],
            max_speed=row["max_speed"],
            avg_temperature=row["avg_temperature"] or 0,
            max_temperature=row["max_temperature"] or 0,
            intensity_factor=row["intensity_factor"] or 0.0,
            normalized_power=row["normalized_power"] or 0,
            training_stress_score=row["training_stress_score"] or 0.0,
            fit_file_path=row["fit_file_path"],
            fit_file_status=row["fit_file_status"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
