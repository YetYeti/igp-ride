from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Activity:
    ride_id: int
    member_id: int
    title: str
    sport: str
    sub_sport: str
    start_time: datetime | None = None
    total_ascent: int = 0
    total_descent: int = 0
    total_calories: int = 0
    total_distance: float = 0.0
    total_elapsed_time: float = 0.0
    total_moving_time: float = 0.0
    avg_cadence: int = 0
    max_cadence: int = 0
    avg_heart_rate: int = 0
    min_heart_rate: int = 0
    max_heart_rate: int = 0
    avg_power: int = 0
    max_power: int = 0
    avg_speed: float = 0.0
    max_speed: float = 0.0
    avg_temperature: int = 0
    max_temperature: int = 0
    intensity_factor: float = 0.0
    normalized_power: int = 0
    training_stress_score: float = 0.0
    fit_file_path: str = ""
    fit_file_status: str = "missing"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class SyncSummary:
    remote_fetched: int = 0
    new_activities: int = 0
    updated_activities: int = 0
    activities_skipped: int = 0
    fit_files_failed: int = 0


@dataclass(slots=True)
class PeriodStats:
    period: str
    count: int = 0
    total_distance: float = 0.0
    total_moving_time: float = 0.0
    avg_speed: float = 0.0
    avg_power: float = 0.0
    total_ascent: int = 0
