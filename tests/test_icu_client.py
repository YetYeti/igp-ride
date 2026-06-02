from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

from igp_ride.icu_client import (
    ICUClientError,
    INTERVALS_ICU_API_BASE_URL,
    INTERVALS_ICU_CURRENT_USER,
    IntervalsIcuClient,
)


def _response(payload: object, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        http_error = requests.HTTPError()
        http_error.response = response
        response.raise_for_status.side_effect = http_error
    else:
        response.raise_for_status.return_value = None
    return response


class TestIntervalsIcuClient:
    def test_configures_basic_auth(self):
        client = IntervalsIcuClient(api_key="secret")

        assert client._session.auth == ("API_KEY", "secret")
        client.close()

    def test_get_athlete(self):
        client = IntervalsIcuClient(api_key="secret")
        response = _response({"id": "i123456", "name": "Tester"})

        with patch.object(client._session, "get", return_value=response) as get:
            payload = client.get_athlete()

        get.assert_called_once_with(
            f"{INTERVALS_ICU_API_BASE_URL}/athlete/{INTERVALS_ICU_CURRENT_USER}",
            timeout=30,
        )
        assert payload == {"id": "i123456", "name": "Tester"}
        client.close()

    def test_list_activities_normalizes_summary_fields(self):
        client = IntervalsIcuClient(api_key="secret")
        response = _response(
            [
                {
                    "id": "i1",
                    "external_id": "igp-1",
                    "source": "UPLOAD",
                    "type": "Ride",
                    "start_date_local": "2026-05-01T08:00:00",
                },
                {"id": "strava-1", "source": "STRAVA"},
            ]
        )

        with patch.object(client._session, "get", return_value=response) as get:
            activities = client.list_activities(
                oldest="2026-05-01",
                newest="2026-05-09",
            )

        get.assert_called_once_with(
            f"{INTERVALS_ICU_API_BASE_URL}/athlete/{INTERVALS_ICU_CURRENT_USER}/activities",
            params={"oldest": "2026-05-01", "newest": "2026-05-09"},
            timeout=30,
        )
        assert activities[0].id == "i1"
        assert activities[0].external_id == "igp-1"
        assert activities[0].activity_type == "Ride"
        assert activities[1].id == "strava-1"
        assert activities[1].source == "STRAVA"
        client.close()

    def test_upload_activity_file_posts_multipart(self, tmp_path: Path):
        fit_path = tmp_path / "ride.fit"
        fit_path.write_bytes(b"fit-data")
        client = IntervalsIcuClient(api_key="secret")
        response = _response({"id": "i999"})

        with patch.object(client._session, "post", return_value=response) as post:
            activity_id = client.upload_activity_file(
                fit_path,
                external_id="igp-1",
                name="Morning Ride",
                description="Uploaded by igp-ride",
            )

        post.assert_called_once()
        assert (
            post.call_args.args[0]
            == f"{INTERVALS_ICU_API_BASE_URL}/athlete/{INTERVALS_ICU_CURRENT_USER}/activities"
        )
        assert post.call_args.kwargs["params"] == {
            "external_id": "igp-1",
            "name": "Morning Ride",
            "description": "Uploaded by igp-ride",
        }
        assert "file" in post.call_args.kwargs["files"]
        assert post.call_args.kwargs["timeout"] == 60
        assert activity_id == "i999"
        client.close()

    def test_add_activity_message_posts_json(self):
        client = IntervalsIcuClient(api_key="secret")
        response = _response({}, status_code=204)

        with patch.object(client._session, "post", return_value=response) as post:
            client.add_activity_message("i999", "Legs felt good.")

        post.assert_called_once_with(
            f"{INTERVALS_ICU_API_BASE_URL}/activity/i999/messages",
            json={"message": "Legs felt good."},
            timeout=30,
        )
        client.close()

    def test_raises_clear_error_for_unauthorized_response(self):
        client = IntervalsIcuClient(api_key="bad")

        with (
            patch.object(client._session, "get", return_value=_response({}, 401)),
            pytest.raises(ICUClientError, match="authentication failed"),
        ):
            client.get_athlete()
        client.close()

    def test_upload_requires_id_in_response(self, tmp_path: Path):
        fit_path = tmp_path / "ride.fit"
        fit_path.write_bytes(b"fit-data")
        client = IntervalsIcuClient(api_key="secret")

        with (
            patch.object(client._session, "post", return_value=_response({})),
            pytest.raises(ICUClientError, match="did not include an id"),
        ):
            client.upload_activity_file(fit_path, external_id="igp-1")
        client.close()
