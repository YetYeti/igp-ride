from __future__ import annotations

from datetime import timezone
from typing import Any

import fitparse

from igp_ride.utils import get_logger


logger = get_logger(__name__)


class FitParseError(Exception):
    pass


def parse_fit_file(file_name: str) -> dict[str, Any]:
    logger.debug("Parsing FIT file: %s", file_name)
    try:
        fit_file = fitparse.FitFile(file_name)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to open FIT file %s: %s", file_name, exc)
        raise FitParseError(f"Unable to open FIT file {file_name}: {exc}") from exc

    try:
        session_records: list[dict[str, Any]] = []
        for record in fit_file.get_messages("session"):
            get_values = getattr(record, "get_values", None)
            if not callable(get_values):
                continue
            values = get_values()
            if not isinstance(values, dict):
                continue
            message: dict[str, Any] = {}
            for key, value in values.items():
                message[str(key)] = value
            session_records.append(message)
        logger.debug(
            "FIT file parsed successfully: %s (sessions=%d)",
            file_name,
            len(session_records),
        )
        return {"session": session_records}
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse FIT file %s: %s", file_name, exc)
        raise FitParseError(f"Unable to parse FIT file {file_name}: {exc}") from exc


def normalize_session_data(parsed_data: dict[str, Any]) -> dict[str, Any]:
    sessions = parsed_data.get("session", [])
    if not sessions:
        logger.debug("No session data found in FIT file")
        return {}

    session_record = sessions[0]
    start_time = session_record.get("start_time")
    if start_time is not None and getattr(start_time, "tzinfo", None) is None:
        start_time = start_time.replace(tzinfo=timezone.utc).astimezone()

    normalized = {
        "sport": session_record.get("sport", "cycling"),
        "sub_sport": session_record.get("sub_sport", "road"),
        "start_time": start_time,
    }
    for key in (
        "total_ascent",
        "total_descent",
        "total_calories",
        "total_distance",
        "total_elapsed_time",
        "total_moving_time",
        "avg_cadence",
        "max_cadence",
        "avg_heart_rate",
        "min_heart_rate",
        "max_heart_rate",
        "avg_power",
        "max_power",
        "avg_speed",
        "max_speed",
        "avg_temperature",
        "max_temperature",
        "intensity_factor",
        "normalized_power",
        "training_stress_score",
    ):
        if key in session_record:
            normalized[key] = session_record[key]
    return normalized
