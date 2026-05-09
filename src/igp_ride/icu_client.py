from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ICUClientError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ICUActivitySummary:
    id: str
    external_id: str = ""
    source: str = ""
    activity_type: str = ""
    start_date_local: str = ""


class IntervalsIcuClient:
    def __init__(
        self,
        *,
        api_key: str,
        athlete_id: str = "0",
        base_url: str = "https://intervals.icu/api/v1",
        timeout: int = 30,
    ):
        self.api_key = api_key
        self.athlete_id = athlete_id or "0"
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = self._create_session()
        self._session.auth = ("API_KEY", api_key)
        self._session.headers.update({"Accept": "application/json"})

    def close(self) -> None:
        self._session.close()

    def get_athlete(self) -> dict[str, Any]:
        response = self._session.get(
            f"{self.base_url}/athlete/{self.athlete_id}",
            timeout=self.timeout,
        )
        payload = _decode_json_response(response)
        if not isinstance(payload, dict):
            raise ICUClientError("Intervals.icu returned an unexpected athlete response.")
        return cast(dict[str, Any], payload)

    def list_activities(
        self,
        *,
        oldest: str | None = None,
        newest: str | None = None,
    ) -> list[ICUActivitySummary]:
        params: dict[str, str] = {}
        if oldest:
            params["oldest"] = oldest
        if newest:
            params["newest"] = newest
        response = self._session.get(
            f"{self.base_url}/athlete/{self.athlete_id}/activities",
            params=params,
            timeout=self.timeout,
        )
        payload = _decode_json_response(response)
        if not isinstance(payload, list):
            raise ICUClientError("Intervals.icu returned an unexpected activity list.")
        return [_parse_activity_summary(item) for item in payload if isinstance(item, dict)]

    def upload_activity_file(
        self,
        fit_path: Path,
        *,
        external_id: str,
        name: str = "",
        description: str = "",
    ) -> str:
        params = {"external_id": external_id}
        if name:
            params["name"] = name
        if description:
            params["description"] = description

        with fit_path.open("rb") as fit_file:
            response = self._session.post(
                f"{self.base_url}/athlete/{self.athlete_id}/activities",
                params=params,
                files={"file": (fit_path.name, fit_file, "application/octet-stream")},
                timeout=60,
            )
        payload = _decode_json_response(response)
        if not isinstance(payload, dict):
            raise ICUClientError("Intervals.icu returned an unexpected upload response.")
        activity_id = payload.get("id")
        if not isinstance(activity_id, str) or not activity_id:
            raise ICUClientError("Intervals.icu upload response did not include an id.")
        return activity_id

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session


def _decode_json_response(response: requests.Response) -> object:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status == 401:
            raise ICUClientError("Intervals.icu authentication failed.") from exc
        raise ICUClientError(f"Intervals.icu request failed with HTTP {status}.") from exc
    try:
        return response.json()
    except ValueError as exc:
        raise ICUClientError("Intervals.icu returned invalid JSON.") from exc


def _parse_activity_summary(payload: dict[str, Any]) -> ICUActivitySummary:
    return ICUActivitySummary(
        id=_string_value(payload.get("id")),
        external_id=_string_value(payload.get("external_id")),
        source=_string_value(payload.get("source")),
        activity_type=_string_value(payload.get("type")),
        start_date_local=_string_value(payload.get("start_date_local")),
    )


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""
