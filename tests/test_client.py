from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from igp_ride.client import IGPSportClient


def _write_session_file(session_path: Path, **overrides: str) -> None:
    payload = {
        "username": "stored-user",
        "saved_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
    }
    payload.update(overrides)
    session_path.write_text(json.dumps(payload), encoding="utf-8")


class TestSessionPersistence:
    def test_save_session_stores_secrets_in_keyring(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        with patch("igp_ride.client.load_session_data", return_value={}):
            client = IGPSportClient(
                username="tester",
                password="secret",
                base_url="https://example.com",
                session_path=session_path,
            )
        client._session.cookies.set("sessionid", "abc")
        client._session.headers.update({"Authorization": "Bearer token"})

        with patch("igp_ride.client.save_session_data") as mock_save_session_data:
            client._save_session()

        payload = json.loads(session_path.read_text(encoding="utf-8"))
        assert payload["username"] == "tester"
        assert "saved_at" in payload
        assert "cookies" not in payload
        assert "authorization" not in payload
        mock_save_session_data.assert_called_once_with(
            "tester",
            cookies={"sessionid": "abc"},
            authorization="Bearer token",
        )
        client.close()

    def test_load_session_restores_keyring_state(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        _write_session_file(session_path)

        with patch(
            "igp_ride.client.load_session_data",
            return_value={
                "cookies": {"sessionid": "abc"},
                "authorization": "Bearer token",
            },
        ):
            client = IGPSportClient(
                username="ignored",
                password="secret",
                base_url="https://example.com",
                session_path=session_path,
            )

        assert client.username == "stored-user"
        assert client._session.cookies.get("sessionid") == "abc"
        assert client._session.headers["Authorization"] == "Bearer token"
        assert client._authenticated is True
        client.close()

    def test_load_session_without_keyring_data_requires_reauth(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        _write_session_file(session_path)

        with patch("igp_ride.client.load_session_data", return_value={}):
            client = IGPSportClient(
                username="ignored",
                password="secret",
                base_url="https://example.com",
                session_path=session_path,
            )

        assert client.username == "stored-user"
        assert client._authenticated is False
        assert "Authorization" not in client._session.headers
        client.close()
