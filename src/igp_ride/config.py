from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
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
SESSION_DATA_PROTECTION: Final[str] = "dpapi-current-user"


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
    if not isinstance(payload, dict):
        return {}
    if payload.get("protected") != SESSION_DATA_PROTECTION:
        return payload
    encoded = payload.get("data")
    if not isinstance(encoded, str) or not encoded:
        return {}
    try:
        encrypted = base64.b64decode(encoded)
        decoded = json.loads(_unprotect_with_dpapi(encrypted).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _save_session_data_file(payload: Mapping[str, object]) -> None:
    session_data_file = get_default_session_data_file()
    ensure_dir(session_data_file.parent)
    encrypted = _protect_with_dpapi(
        json.dumps(payload, ensure_ascii=True).encode("utf-8")
    )
    protected_payload = {
        "protected": SESSION_DATA_PROTECTION,
        "data": base64.b64encode(encrypted).decode("ascii"),
    }
    session_data_file.write_text(
        json.dumps(protected_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    _restrict_session_data_file_permissions(session_data_file)


def _delete_session_data_file() -> None:
    try:
        get_default_session_data_file().unlink()
    except FileNotFoundError:
        pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _protect_with_dpapi(data: bytes) -> bytes:
    return _call_dpapi(data, protect=True)


def _unprotect_with_dpapi(data: bytes) -> bytes:
    return _call_dpapi(data, protect=False)


def _call_dpapi(data: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise OSError("DPAPI is only available on Windows.")
    buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not operation(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _restrict_session_data_file_permissions(path: Path) -> None:
    if sys.platform != "win32":
        path.chmod(0o600)
        return
    path.chmod(0o600)
    if os.name != "nt":
        return
    identity = _current_windows_identity()
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:(R,W)"],
        check=True,
        capture_output=True,
        text=True,
    )


def _current_windows_identity() -> str:
    domain = os.getenv("USERDOMAIN")
    username = os.getenv("USERNAME")
    if domain and username:
        return f"{domain}\\{username}"
    if username:
        return username
    return os.getlogin()
