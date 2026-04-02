from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from igp_ride.utils import ensure_dir


class ConfigurationError(Exception):
    pass


KEYRING_PASSWORD_SERVICE: Final[str] = "igp-ride"
KEYRING_SESSION_SERVICE: Final[str] = "igp-ride-session"
DEFAULT_BASE_URL: Final[str] = "https://my.igpsport.com"

XDG_CONFIG_HOME = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
XDG_DATA_HOME = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))

CONFIG_DIR = XDG_CONFIG_HOME / "igp-ride"
DATA_DIR = XDG_DATA_HOME / "igp-ride"
FIT_DIR = DATA_DIR / "fit"
SESSION_FILE = CONFIG_DIR / "session.json"
DB_FILE = DATA_DIR / "rides.db"


@dataclass(frozen=True, slots=True)
class AppConfig:
    username: str
    password: str
    base_url: str = DEFAULT_BASE_URL
    data_dir: Path = DATA_DIR
    fit_dir: Path = FIT_DIR
    session_file: Path = SESSION_FILE
    db_path: Path = DB_FILE

    @classmethod
    def load(cls, require_credentials: bool = False) -> "AppConfig":
        ensure_runtime_dirs()
        username = _first_non_empty(
            os.getenv("IGP_USERNAME"),
            _read_session_username(),
        )
        password = _first_non_empty(
            os.getenv("IGP_PASSWORD"),
            _load_password(username),
        )
        config = cls(username=username, password=password)
        if require_credentials and (not config.username or not config.password):
            raise ConfigurationError("Missing credentials. Run `igp-ride login` first.")
        return config


def ensure_runtime_dirs() -> None:
    ensure_dir(CONFIG_DIR)
    ensure_dir(DATA_DIR)
    ensure_dir(FIT_DIR)


def save_credentials(username: str, password: str) -> None:
    keyring.set_password(KEYRING_PASSWORD_SERVICE, username, password)


def delete_credentials(username: str) -> None:
    try:
        keyring.delete_password(KEYRING_PASSWORD_SERVICE, username)
    except PasswordDeleteError:
        pass


def load_session_data(username: str) -> dict[str, object]:
    if not username:
        return {}
    try:
        payload = keyring.get_password(KEYRING_SESSION_SERVICE, username)
    except KeyringError:
        return {}
    if not payload:
        return {}
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def save_session_data(
    username: str,
    *,
    cookies: dict[str, str],
    authorization: str,
) -> None:
    payload = {
        "cookies": cookies,
        "authorization": authorization,
    }
    keyring.set_password(
        KEYRING_SESSION_SERVICE,
        username,
        json.dumps(payload, ensure_ascii=True),
    )


def delete_session_data(username: str) -> None:
    try:
        keyring.delete_password(KEYRING_SESSION_SERVICE, username)
    except PasswordDeleteError:
        pass


def _read_session_username() -> str | None:
    if not SESSION_FILE.exists():
        return None
    try:
        payload = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("username")
    return value if isinstance(value, str) and value else None


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ""


def _load_password(username: str) -> str | None:
    if not username:
        return None
    try:
        return keyring.get_password(KEYRING_PASSWORD_SERVICE, username)
    except KeyringError:
        return None
