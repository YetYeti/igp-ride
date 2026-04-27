from __future__ import annotations

import functools
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, TypeVar, cast

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from igp_ride.config import load_session_data, save_session_data
from igp_ride.utils import ensure_dir, get_logger


logger = get_logger(__name__)


T = TypeVar("T")
SESSION_MAX_AGE = timedelta(hours=12)
MIN_FIT_HEADER_BYTES = 14

DEFAULT_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)


class AuthenticationError(Exception):
    pass


class DataSyncError(Exception):
    pass


def auth_retry(max_retries: int = 2, backoff: float = 1.0):
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(self: "IGPSportClient", *args, **kwargs) -> T:
            for attempt in range(max_retries + 1):
                try:
                    return func(self, *args, **kwargs)
                except requests.HTTPError as exc:
                    status = exc.response.status_code if exc.response is not None else 0
                    if status in (401, 403) and attempt < max_retries:
                        time.sleep(backoff * (2**attempt))
                        self._authenticated = False
                        self.login()
                        continue
                    raise
            raise RuntimeError("unreachable")

        return wrapper

    return decorator


class IGPSportClient:
    def __init__(
        self,
        *,
        username: str,
        password: str,
        base_url: str,
        session_path: Path,
    ):
        self.username = username
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.session_path = session_path
        self.timeout = 30
        self._session = self._create_session()
        self._authenticated = False
        self._session_saved_at: datetime | None = None
        self._load_session()

    def close(self) -> None:
        self._session.close()

    def login(self) -> None:
        logger.debug("Attempting login for user: %s", self.username)
        url = f"{self.base_url}/Auth/Login"
        data = {"username": self.username, "password": self.password}
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Encoding": "gzip, deflate",
        }

        response = self._session.post(
            url, data=data, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        set_cookie = response.headers.get("Set-Cookie", "")
        if "loginTicket" not in set_cookie:
            raise AuthenticationError("Login failed: unable to get login ticket.")

        login_match = re.search(r"loginToken=(.*?);", set_cookie)
        if login_match:
            self._session.headers.update(
                {"Authorization": f"Bearer {login_match.group(1)}"}
            )

        self._authenticated = True
        self._session_saved_at = datetime.now(UTC)
        self._save_session()
        logger.info("Login successful for user: %s", self.username)

    @auth_retry()
    def get_activity_page(
        self, *, page: int, page_size: int
    ) -> tuple[list[dict[str, object]], int | None]:
        self._ensure_authenticated()
        logger.debug("Fetching activity page %d (page_size=%d)", page, page_size)
        response = self._session.get(
            f"{self.base_url}/Activity/ActivityList",
            params={"pageIndex": page, "pageSize": page_size},
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = cast(object, response.json(strict=False))
        if not isinstance(result, dict):
            return [], None
        items = result.get("item", [])
        total = result.get("total")
        total_int = total if isinstance(total, int) else None
        if not isinstance(items, list):
            logger.warning("Unexpected response format: items is not a list")
            return [], total_int
        result = [item for item in items if isinstance(item, dict)]
        logger.debug("Page %d: got %d items, total=%s", page, len(result), total)
        return result, total_int

    @auth_retry()
    def download_fit_file(self, ride_id: int, save_path: Path) -> None:
        self._ensure_authenticated()
        logger.debug("Downloading FIT file for ride %d", ride_id)
        ensure_dir(save_path.parent)
        response = self._session.get(
            f"https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/getDownloadUrl/{ride_id}",
            timeout=30,
        )
        response.raise_for_status()
        result = cast(object, response.json(strict=False))
        if not isinstance(result, dict):
            raise DataSyncError(f"Unexpected FIT response for ride {ride_id}.")
        fit_url = result.get("data")
        if not isinstance(fit_url, str) or not fit_url.startswith("https://"):
            raise DataSyncError(f"FIT download URL not available for ride {ride_id}.")

        file_response = requests.get(fit_url, timeout=60)
        file_response.raise_for_status()
        content = file_response.content
        if not _looks_like_fit_file(content):
            raise DataSyncError(f"Downloaded file is not a valid FIT file: {ride_id}.")
        save_path.write_bytes(content)
        logger.info("FIT file saved for ride %d: %s", ride_id, save_path)

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

    def _ensure_authenticated(self) -> None:
        if not self._authenticated or self._session_is_stale():
            self.login()

    def _load_session(self) -> None:
        if not self.session_path.exists():
            logger.debug("No existing session file found")
            return
        logger.debug("Loading session from: %s", self.session_path)
        try:
            payload = cast(
                object, json.loads(self.session_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load session file %s: %s", self.session_path, exc)
            return
        if not isinstance(payload, dict):
            return
        username = payload.get("username")
        if isinstance(username, str) and username:
            self.username = username
        session_data = load_session_data(self.username)
        cookies = session_data.get("cookies")
        if isinstance(cookies, dict):
            filtered_cookies = {
                key: value
                for key, value in cookies.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            self._session.cookies.update(filtered_cookies)
        else:
            filtered_cookies = {}
        authorization = session_data.get("authorization")
        if isinstance(authorization, str) and authorization:
            self._session.headers.update({"Authorization": authorization})
        saved_at = payload.get("saved_at")
        if isinstance(saved_at, str):
            self._session_saved_at = _parse_iso_datetime(saved_at)
        self._authenticated = bool(filtered_cookies or authorization)
        if self._authenticated:
            logger.debug("Session loaded successfully")

    def _save_session(self) -> None:
        ensure_dir(self.session_path.parent)
        logger.debug("Saving session to: %s", self.session_path)
        authorization_header = self._session.headers.get("Authorization", "")
        authorization = (
            authorization_header.decode("utf-8")
            if isinstance(authorization_header, bytes)
            else authorization_header
        )
        save_session_data(
            self.username,
            cookies=requests.utils.dict_from_cookiejar(self._session.cookies),
            authorization=authorization,
        )
        payload = {
            "username": self.username,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        self.session_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

    def _session_is_stale(self) -> bool:
        if not self._authenticated:
            return True
        if self._session_saved_at is None:
            return True
        return datetime.now(UTC) - self._session_saved_at >= SESSION_MAX_AGE


def _parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _looks_like_fit_file(content: bytes) -> bool:
    if len(content) < MIN_FIT_HEADER_BYTES:
        return False
    header_size = content[0]
    if header_size < 12 or len(content) < header_size:
        return False
    return content[8:12] == b".FIT"
