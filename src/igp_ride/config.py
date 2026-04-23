from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final
from collections.abc import Mapping

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from igp_ride.utils import ensure_dir, get_config_dir, get_data_dir


class ConfigurationError(Exception):
    pass


KEYRING_PASSWORD_SERVICE: Final[str] = "igp-ride"
KEYRING_SESSION_SERVICE: Final[str] = "igp-ride-session"
DEFAULT_BASE_URL: Final[str] = "https://my.igpsport.com"


def get_default_config_dir() -> Path:
    return get_config_dir()


def get_default_data_dir() -> Path:
    return get_data_dir()


def get_default_fit_dir() -> Path:
    return get_default_data_dir() / "fit"


def get_default_session_file() -> Path:
    return get_default_config_dir() / "session.json"


def get_default_session_data_file() -> Path:
    return get_default_config_dir() / "session_data.json"


def get_default_db_file() -> Path:
    return get_default_data_dir() / "rides.db"


@dataclass(frozen=True, slots=True)
class AppConfig:
    username: str
    password: str
    base_url: str = DEFAULT_BASE_URL
    data_dir: Path = field(default_factory=get_default_data_dir)
    fit_dir: Path = field(default_factory=get_default_fit_dir)
    session_file: Path = field(default_factory=get_default_session_file)
    db_path: Path = field(default_factory=get_default_db_file)

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
    ensure_dir(get_default_config_dir())
    ensure_dir(get_default_data_dir())
    ensure_dir(get_default_fit_dir())


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
    if sys.platform == "win32":
        return _load_session_data_file()
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
    if sys.platform == "win32":
        _save_session_data_file(payload)
        return
    keyring.set_password(
        KEYRING_SESSION_SERVICE,
        username,
        json.dumps(payload, ensure_ascii=True),
    )


def delete_session_data(username: str) -> None:
    if sys.platform == "win32":
        _delete_session_data_file()
        return
    try:
        keyring.delete_password(KEYRING_SESSION_SERVICE, username)
    except PasswordDeleteError:
        pass


def _read_session_username() -> str | None:
    session_file = get_default_session_file()
    if not session_file.exists():
        return None
    try:
        payload = json.loads(session_file.read_text(encoding="utf-8"))
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


def _load_session_data_file() -> dict[str, object]:
    session_data_file = get_default_session_data_file()
    try:
        payload = json.loads(session_data_file.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_session_data_file(payload: Mapping[str, object]) -> None:
    session_data_file = get_default_session_data_file()
    ensure_dir(session_data_file.parent)
    session_data_file.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _delete_session_data_file() -> None:
    try:
        get_default_session_data_file().unlink()
    except FileNotFoundError:
        pass
