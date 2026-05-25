from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from igp_ride.client import (
    AuthenticationError,
    DataSyncError,
    IGPSportClient,
    _looks_like_fit_file,
)


def _write_session_file(session_path: Path, **overrides: object) -> None:
    payload: dict[str, object] = {
        "username": "stored-user",
        "saved_at": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
        "cookies": {},
        "authorization": "",
        "access_token": "",
        "refresh_token": "",
        "expires_at": "",
    }
    payload.update(overrides)
    session_path.write_text(json.dumps(payload), encoding="utf-8")


class TestSessionPersistence:
    def test_save_session_stores_everything_in_session_file(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com",
            session_path=session_path,
        )
        client._session.cookies.set("sessionid", "abc")
        client._session.headers.update({"Authorization": "Bearer token"})

        client.save_session()

        payload = json.loads(session_path.read_text(encoding="utf-8"))
        assert payload["username"] == "tester"
        assert "saved_at" in payload
        assert payload["cookies"] == {"sessionid": "abc"}
        assert payload["authorization"] == "Bearer token"
        assert payload["access_token"] == "token"
        assert payload["refresh_token"] == ""
        client.close()

    def test_load_session_restores_full_state(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        _write_session_file(
            session_path,
            cookies={"sessionid": "abc"},
            authorization="Bearer token",
            access_token="token",
            refresh_token="refresh",
            expires_at="2026-03-01T12:00:00+00:00",
        )

        client = IGPSportClient(
            username="ignored",
            password="secret",
            base_url="https://example.com",
            session_path=session_path,
        )

        assert client.username == "stored-user"
        assert client._session.cookies.get("sessionid") == "abc"
        assert client._session.headers["Authorization"] == "Bearer token"
        assert client._refresh_token == "refresh"
        assert client._authenticated is True
        client.close()

    def test_load_session_without_auth_data_requires_reauth(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        _write_session_file(session_path)

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


class TestLogin:
    def test_login_posts_json_and_stores_bearer_token(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com/service",
            session_path=tmp_path / "session.json",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 604800,
            },
        }

        with (
            patch.object(client._session, "post", return_value=response) as post,
            patch.object(client, "save_session") as save_session,
        ):
            client.login()

        post.assert_called_once()
        _, kwargs = post.call_args
        assert (
            post.call_args.args[0] == "https://example.com/service/auth/account/login"
        )
        assert kwargs["json"] == {
            "appId": "igpsport-web",
            "username": "tester",
            "password": "secret",
        }
        assert client._session.headers["Authorization"] == "Bearer access-token"
        assert client._refresh_token == "refresh-token"
        assert client._session_expires_at is not None
        save_session.assert_called_once()
        client.close()

    def test_login_can_skip_session_save(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com/service",
            session_path=tmp_path / "session.json",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "code": 0,
            "data": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "expires_in": 604800,
            },
        }

        with (
            patch.object(client._session, "post", return_value=response),
            patch.object(client, "save_session") as save_session,
        ):
            client.login(save_session=False)

        assert client._session.headers["Authorization"] == "Bearer access-token"
        save_session.assert_not_called()
        client.close()

    def test_can_skip_loading_existing_session(self, tmp_path: Path):
        session_path = tmp_path / "session.json"
        _write_session_file(session_path, username="stored-user")

        client = IGPSportClient(
            username="new-user",
            password="secret",
            base_url="https://example.com/service",
            session_path=session_path,
            load_session=False,
        )

        assert client.username == "new-user"
        assert client._authenticated is False
        client.close()

    def test_login_raises_authentication_error_for_business_error(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="bad",
            base_url="https://example.com/service",
            session_path=tmp_path / "session.json",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 1002, "message": "Password error"}

        with (
            patch.object(client._session, "post", return_value=response),
            pytest.raises(AuthenticationError, match="Password error"),
        ):
            client.login()
        client.close()

    def test_login_raises_authentication_error_when_token_is_missing(
        self, tmp_path: Path
    ):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com/service",
            session_path=tmp_path / "session.json",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 0, "data": {}}

        with (
            patch.object(client._session, "post", return_value=response),
            pytest.raises(AuthenticationError, match="missing access token"),
        ):
            client.login()
        client.close()


class TestActivityPage:
    def test_get_activity_page_uses_new_api_and_normalizes_rows(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com/service",
            session_path=tmp_path / "session.json",
        )
        client._authenticated = True
        client._session_saved_at = datetime.now(UTC)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "code": 0,
            "message": "success",
            "data": {
                "rows": [
                    {
                        "rideId": 123,
                        "memberId": 456,
                        "title": "Morning Ride",
                        "rideDistance": 12.3,
                        "totalAscent": 100,
                        "startTime": "2026-05-09T07:00:00",
                    }
                ],
                "totalRows": 7,
            },
        }

        with patch.object(client._session, "get", return_value=response) as get:
            items, total = client.get_activity_page(page=2, page_size=20)

        get.assert_called_once_with(
            "https://example.com/service/web-gateway/web-analyze/activity/queryMyActivity",
            params={"pageNo": 2, "pageSize": 20, "reqType": 0, "sort": 1},
            timeout=client.timeout,
        )
        assert total == 7
        assert items == [
            {
                "rideId": 123,
                "memberId": 456,
                "title": "Morning Ride",
                "rideDistance": 12.3,
                "totalAscent": 100,
                "startTime": "2026-05-09T07:00:00",
                "RideId": 123,
                "MemberId": 456,
                "Title": "Morning Ride",
                "RideDistance": 12.3,
                "TotalAscent": 100,
                "StartTime": "2026-05-09T07:00:00",
            }
        ]
        client.close()

    def test_get_activity_page_raises_for_business_error(self, tmp_path: Path):
        client = IGPSportClient(
            username="tester",
            password="secret",
            base_url="https://example.com/service",
            session_path=tmp_path / "session.json",
        )
        client._authenticated = True
        client._session_saved_at = datetime.now(UTC)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 401, "message": "token expired"}

        with (
            patch.object(client._session, "get", return_value=response),
            patch.object(client, "login"),
            pytest.raises(AuthenticationError, match="token expired"),
        ):
            client.get_activity_page(page=1, page_size=20)
        client.close()


class TestDownloadFitFile:
    def test_download_fit_file_uses_session_get_for_signed_url(self, tmp_path: Path):
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

        with patch.object(
            client._session, "get", side_effect=[download_url_response, fit_response]
        ) as session_get:
            client.download_fit_file(123, save_path)

        assert session_get.call_count == 2
        args0, _ = session_get.call_args_list[0]
        assert "getDownloadUrl" in args0[0]
        args1, kwargs1 = session_get.call_args_list[1]
        assert args1[0] == "https://cdn.example.com/123.fit"
        assert kwargs1["timeout"] == 60
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
        download_url_response.json.return_value = {
            "data": "http://cdn.example.com/123.fit"
        }

        with (
            patch.object(
                client._session, "get", return_value=download_url_response
            ) as session_get,
            pytest.raises(DataSyncError),
        ):
            client.download_fit_file(123, tmp_path / "123.fit")

        session_get.assert_called_once()
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
            patch.object(
                client._session, "get", side_effect=[download_url_response, fit_response]
            ),
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
