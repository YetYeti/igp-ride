from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from igp_ride.client import DataSyncError, IGPSportClient, _looks_like_fit_file


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


class TestDownloadFitFile:
    def test_download_fit_file_uses_clean_request_for_signed_url(
        self, tmp_path: Path
    ):
        save_path = tmp_path / "123.fit"
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com",
            session_path=tmp_path / "session.json",
        )
        client._authenticated = True
        client._session_saved_at = datetime.now(UTC)
        client._session.headers.update({"Authorization": "Bearer token"})
        download_url_response = Mock()
        download_url_response.raise_for_status.return_value = None
        download_url_response.json.return_value = {
            "data": "https://cdn.example.com/123.fit"
        }
        fit_response = Mock()
        fit_response.raise_for_status.return_value = None
        fit_response.content = b"\x0e\x10\x00\x00\x00\x00\x00\x00.FITdata"

        with (
            patch.object(client._session, "get", return_value=download_url_response)
            as authenticated_get,
            patch("igp_ride.client.requests.get", return_value=fit_response)
            as clean_get,
        ):
            client.download_fit_file(123, save_path)

        authenticated_get.assert_called_once()
        clean_get.assert_called_once_with("https://cdn.example.com/123.fit", timeout=60)
        assert save_path.read_bytes() == fit_response.content
        client.close()

    def test_download_fit_file_rejects_http_url(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com",
            session_path=tmp_path / "session.json",
        )
        client._authenticated = True
        client._session_saved_at = datetime.now(UTC)
        download_url_response = Mock()
        download_url_response.raise_for_status.return_value = None
        download_url_response.json.return_value = {"data": "http://cdn.example.com/123.fit"}

        with (
            patch.object(client._session, "get", return_value=download_url_response),
            patch("igp_ride.client.requests.get") as clean_get,
            pytest.raises(DataSyncError),
        ):
            client.download_fit_file(123, tmp_path / "123.fit")

        clean_get.assert_not_called()
        client.close()

    def test_download_fit_file_rejects_non_fit_content(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com",
            session_path=tmp_path / "session.json",
        )
        client._authenticated = True
        client._session_saved_at = datetime.now(UTC)
        download_url_response = Mock()
        download_url_response.raise_for_status.return_value = None
        download_url_response.json.return_value = {
            "data": "https://cdn.example.com/123.fit"
        }
        fit_response = Mock()
        fit_response.raise_for_status.return_value = None
        fit_response.content = b"<html>expired</html>"

        with (
            patch.object(client._session, "get", return_value=download_url_response),
            patch("igp_ride.client.requests.get", return_value=fit_response),
            pytest.raises(DataSyncError),
        ):
            client.download_fit_file(123, tmp_path / "123.fit")

        assert not (tmp_path / "123.fit").exists()
        client.close()


class TestLooksLikeFitFile:
    def test_accepts_fit_header(self):
        assert _looks_like_fit_file(b"\x0e\x10\x00\x00\x00\x00\x00\x00.FITdata")

    def test_rejects_short_content(self):
        assert not _looks_like_fit_file(b".FIT")

    def test_rejects_non_fit_header(self):
        assert not _looks_like_fit_file(b"\x0e\x10\x00\x00\x00\x00\x00\x00.HTMLdata")
