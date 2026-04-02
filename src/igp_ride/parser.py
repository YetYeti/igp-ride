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

    return {
        "sport": session_record.get("sport", "cycling"),
        "sub_sport": session_record.get("sub_sport", "road"),
        "start_time": start_time,
        "total_ascent": session_record.get("total_ascent", 0),
        "total_descent": session_record.get("total_descent", 0),
        "total_calories": session_record.get("total_calories", 0),
        "total_distance": session_record.get("total_distance", 0.0),
        "total_elapsed_time": session_record.get("total_elapsed_time", 0.0),
        "total_moving_time": session_record.get("total_moving_time", 0.0),
        "avg_cadence": session_record.get("avg_cadence", 0),
        "max_cadence": session_record.get("max_cadence", 0),
        "avg_heart_rate": session_record.get("avg_heart_rate", 0),
        "min_heart_rate": session_record.get("min_heart_rate", 0),
        "max_heart_rate": session_record.get("max_heart_rate", 0),
        "avg_power": session_record.get("avg_power", 0),
        "max_power": session_record.get("max_power", 0),
        "avg_speed": session_record.get("avg_speed", 0.0),
        "max_speed": session_record.get("max_speed", 0.0),
        "avg_temperature": session_record.get("avg_temperature", 0),
        "max_temperature": session_record.get("max_temperature", 0),
        "intensity_factor": session_record.get("intensity_factor", 0.0),
        "normalized_power": session_record.get("normalized_power", 0),
        "training_stress_score": session_record.get("training_stress_score", 0.0),
    }
