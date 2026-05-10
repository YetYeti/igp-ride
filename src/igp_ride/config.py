from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from igp_ride.crypto import decrypt_value, encrypt_value
from igp_ride.utils import ensure_dir, get_config_dir, get_data_dir


class ConfigurationError(Exception):
    pass


DEFAULT_BASE_URL: Final[str] = "https://prod.zh.igpsport.com/service"


def get_default_config_dir() -> Path:
    return get_config_dir()


def get_default_data_dir() -> Path:
    return get_data_dir()


def get_default_fit_dir() -> Path:
    return get_default_data_dir() / "fit"


def get_default_session_file() -> Path:
    return get_default_config_dir() / "session.json"


def get_default_credentials_file() -> Path:
    return get_default_config_dir() / "credentials.json"


def get_default_icu_config_file() -> Path:
    return get_default_config_dir() / "icu.json"


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
    icu_api_key: str = ""

    @classmethod
    def load(cls, require_credentials: bool = False) -> "AppConfig":
        ensure_runtime_dirs()
        username = _first_non_empty(
            os.getenv("IGP_USERNAME"),
            _read_stored_username(),
        )
        password = _first_non_empty(
            os.getenv("IGP_PASSWORD"),
            _load_password(username),
        )
        config = cls(
            username=username,
            password=password,
            icu_api_key=_first_non_empty(
                os.getenv("IGP_RIDE_ICU_API_KEY"),
                os.getenv("INTERVALS_ICU_API_KEY"),
                load_icu_api_key(),
            ),
        )
        if require_credentials and (not config.username or not config.password):
            raise ConfigurationError("Missing credentials. Run `igp-ride login` first.")
        return config


def ensure_runtime_dirs() -> None:
    ensure_dir(get_default_config_dir())
    ensure_dir(get_default_data_dir())
    ensure_dir(get_default_fit_dir())


def save_credentials(username: str, password: str) -> None:
    path = get_default_credentials_file()
    ensure_dir(path.parent)
    payload = {
        "username": username,
        "password_encrypted": encrypt_value(password),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    path.chmod(0o600)


def delete_credentials(username: str) -> None:
    try:
        get_default_credentials_file().unlink()
    except FileNotFoundError:
        pass


def delete_session_data(username: str) -> None:
    try:
        get_default_session_file().unlink()
    except FileNotFoundError:
        pass


def save_icu_config(*, api_key: str) -> Path:
    if not api_key:
        raise ConfigurationError("Intervals.icu API key is required.")
    save_icu_api_key(api_key)
    return get_default_icu_config_file()


def clear_icu_config() -> None:
    delete_icu_api_key()


def save_icu_api_key(api_key: str) -> None:
    path = get_default_icu_config_file()
    ensure_dir(path.parent)
    payload = {
        "api_key_encrypted": encrypt_value(api_key),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    path.chmod(0o600)


def load_icu_api_key() -> str | None:
    path = get_default_icu_config_file()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    encrypted = payload.get("api_key_encrypted")
    if not isinstance(encrypted, str) or not encrypted:
        return None
    return decrypt_value(encrypted)


def delete_icu_api_key() -> None:
    try:
        get_default_icu_config_file().unlink()
    except FileNotFoundError:
        pass


def _read_stored_username() -> str | None:
    path = get_default_credentials_file()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
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
    path = get_default_credentials_file()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    encrypted = payload.get("password_encrypted")
    if not isinstance(encrypted, str) or not encrypted:
        return None
    return decrypt_value(encrypted)
