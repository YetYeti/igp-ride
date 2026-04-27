from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from igp_ride.service import (
    RideSyncService,
    SyncProgress,
    _as_float,
    _as_int,
    _as_str,
    _calculate_fetch_limits,
)
from igp_ride.parser import FitParseError


class TestAsInt:
    def test_int(self):
        assert _as_int(42) == 42

    def test_float(self):
        assert _as_int(3.7) == 3

    def test_string(self):
        assert _as_int("10") == 10

    def test_string_float(self):
        assert _as_int("3.7") == 3

    def test_none(self):
        assert _as_int(None) == 0

    def test_empty_string(self):
        assert _as_int("") == 0

    def test_bool(self):
        assert _as_int(True) == 1


class TestAsFloat:
    def test_int(self):
        assert _as_float(42) == 42.0

    def test_float(self):
        assert _as_float(3.14) == 3.14

    def test_string(self):
        assert _as_float("2.5") == 2.5

    def test_none(self):
        assert _as_float(None) == 0.0


class TestAsStr:
    def test_string(self):
        assert _as_str("hello") == "hello"

    def test_empty_string_returns_default(self):
        assert _as_str("", "fallback") == "fallback"

    def test_none_returns_default(self):
        assert _as_str(None, "fallback") == "fallback"

    def test_non_string_returns_default(self):
        assert _as_str(42, "fallback") == "fallback"


class TestSyncProgress:
    def test_defaults(self):
        p = SyncProgress(stage="fetching", done=0, total=0)
        assert p.stage == "fetching"
        assert p.new_activities == 0
        assert p.current_ride_id is None

    def test_all_fields(self):
        p = SyncProgress(
            stage="processing",
            done=5,
            total=10,
            new_activities=3,
            updated_activities=1,
            activities_skipped=1,
            fit_files_failed=0,
            current_ride_id=12345,
        )
        assert p.done == 5
        assert p.total == 10
        assert p.current_ride_id == 12345


class TestCalculateFetchLimits:
    def test_full_sync_when_no_last_sync(self):
        page_size, max_pages = _calculate_fetch_limits(None)
        assert page_size == 200
        assert max_pages == 1000

    def test_incremental_uses_fixed_page_size(self):
        now = datetime.now(UTC).isoformat()
        page_size, max_pages = _calculate_fetch_limits(now)
        assert page_size == 20
        assert max_pages == 1000


class TestSyncModes:
    def test_sync_force_full(self):
        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = Path("/tmp/fit")
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = Path("/tmp/session.json")

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase") as MockDB,
        ):
            mock_client = MockClient.return_value
            mock_db = MockDB.return_value
            mock_db.get_sync_meta.return_value = "2026-03-01T00:00:00+00:00"
            mock_db.get_all_ride_ids.return_value = set()
            mock_client.get_activity_page.return_value = ([], None)

            service = RideSyncService(config)
            service.sync(force_full=True)

            mock_client.get_activity_page.assert_called()
            call_kwargs = mock_client.get_activity_page.call_args
            actual_page_size = call_kwargs.kwargs.get("page_size") or call_kwargs[
                1
            ].get("page_size")
            assert actual_page_size == 200

    def test_sync_incremental(self):
        from datetime import timedelta

        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = Path("/tmp/fit")
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = Path("/tmp/session.json")

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase") as MockDB,
        ):
            mock_client = MockClient.return_value
            mock_db = MockDB.return_value
            three_days_ago = (datetime.now(UTC) - timedelta(days=3)).isoformat()
            mock_db.get_sync_meta.return_value = three_days_ago
            mock_db.get_all_ride_ids.return_value = set()
            mock_client.get_activity_page.return_value = ([], None)

            service = RideSyncService(config)
            service.sync(force_full=False)

            call_kwargs = mock_client.get_activity_page.call_args
            actual_page_size = call_kwargs.kwargs.get("page_size") or call_kwargs[
                1
            ].get("page_size")
            assert actual_page_size == 20

    def test_sync_incremental_fetches_until_known_activity_boundary(self):
        from datetime import timedelta

        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = Path("/tmp/fit")
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = Path("/tmp/session.json")

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase") as MockDB,
            patch("igp_ride.service.parse_fit_file", side_effect=FitParseError("bad")),
        ):
            mock_client = MockClient.return_value
            mock_db = MockDB.return_value
            three_days_ago = (datetime.now(UTC) - timedelta(days=3)).isoformat()
            mock_db.get_sync_meta.return_value = three_days_ago
            mock_db.get_all_ride_ids.return_value = {1, 2}
            mock_client.get_activity_page.side_effect = [
                ([{"RideId": 4}], 4),
                ([{"RideId": 3}], 4),
                ([{"RideId": 2}, {"RideId": 1}], 4),
            ]
            mock_client.download_fit_file.side_effect = lambda _ride_id, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_bytes(b"bad fit"),
            )

            service = RideSyncService(config)
            summary = service.sync(force_full=False)

            assert summary.remote_fetched == 4
            assert mock_client.get_activity_page.call_count == 3
            mock_db.set_sync_meta.assert_called_once()

    def test_sync_incremental_does_not_advance_watermark_without_known_boundary(self):
        from datetime import timedelta

        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = Path("/tmp/fit")
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = Path("/tmp/session.json")

        with (
            patch("igp_ride.service.MAX_ACTIVITY_PAGES", 2),
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase") as MockDB,
            patch("igp_ride.service.parse_fit_file", side_effect=FitParseError("bad")),
        ):
            mock_client = MockClient.return_value
            mock_db = MockDB.return_value
            three_days_ago = (datetime.now(UTC) - timedelta(days=3)).isoformat()
            mock_db.get_sync_meta.return_value = three_days_ago
            mock_db.get_all_ride_ids.return_value = set()
            mock_client.get_activity_page.side_effect = [
                ([{"RideId": 4}], 4),
                ([{"RideId": 3}], 4),
            ]
            mock_client.download_fit_file.side_effect = lambda _ride_id, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_bytes(b"bad fit"),
            )

            service = RideSyncService(config)
            summary = service.sync(force_full=False)

            assert summary.remote_fetched == 2
            assert mock_client.get_activity_page.call_count == 2
            mock_db.set_sync_meta.assert_not_called()


class TestRepair:
    def test_repair_includes_downloaded_activity_with_invalid_fit_header(
        self, tmp_path: Path
    ):
        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = tmp_path / "fit"
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = tmp_path / "session.json"
        damaged_path = config.fit_dir / "1.fit"
        damaged_path.parent.mkdir(parents=True)
        damaged_path.write_bytes(b"<html>expired</html>")
        activity = MagicMock()
        activity.ride_id = 1
        activity.fit_file_path = str(damaged_path)
        activity.fit_file_status = "downloaded"

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase") as MockDB,
            patch("igp_ride.service.parse_fit_file", return_value={"session": [{}]}),
        ):
            mock_client = MockClient.return_value
            mock_db = MockDB.return_value
            mock_db.get_activities_with_missing_fit.return_value = []
            mock_db.list_activities.return_value = [activity]
            mock_client.download_fit_file.side_effect = lambda _ride_id, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_bytes(b"\x0e\x10\x00\x00\x00\x00\x00\x00.FITdata"),
            )

            service = RideSyncService(config)
            summary = service.repair()

            assert summary.remote_fetched == 1
            assert summary.updated_activities == 1
            mock_client.download_fit_file.assert_called_once_with(1, config.fit_dir / "1.fit")
            mock_db.upsert.assert_called_once()

    def test_repair_skips_downloaded_activity_with_valid_fit_header(
        self, tmp_path: Path
    ):
        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = tmp_path / "fit"
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = tmp_path / "session.json"
        fit_path = config.fit_dir / "1.fit"
        fit_path.parent.mkdir(parents=True)
        fit_path.write_bytes(b"\x0e\x10\x00\x00\x00\x00\x00\x00.FITdata")
        activity = MagicMock()
        activity.ride_id = 1
        activity.fit_file_path = str(fit_path)
        activity.fit_file_status = "downloaded"

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase") as MockDB,
        ):
            mock_client = MockClient.return_value
            mock_db = MockDB.return_value
            mock_db.get_activities_with_missing_fit.return_value = []
            mock_db.list_activities.return_value = [activity]

            service = RideSyncService(config)
            summary = service.repair()

            assert summary.remote_fetched == 0
            mock_client.download_fit_file.assert_not_called()


class TestBuildActivity:
    def test_build_activity_falls_back_to_remote_summary_when_fit_fields_are_missing(
        self, tmp_path: Path
    ):
        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = tmp_path / "fit"
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = tmp_path / "session.json"
        fit_path = config.fit_dir / "1.fit"
        fit_path.parent.mkdir(parents=True)
        fit_path.write_bytes(b"\x0e\x10\x00\x00\x00\x00\x00\x00.FITdata")

        with (
            patch("igp_ride.service.IGPSportClient"),
            patch("igp_ride.service.ActivityDatabase"),
            patch(
                "igp_ride.service.parse_fit_file",
                return_value={"session": [{"sport": "cycling"}]},
            ),
        ):
            service = RideSyncService(config)
            activity = service._build_activity(
                {
                    "RideId": 1,
                    "MemberId": 2,
                    "Title": "Remote Ride",
                    "RideDistance": 45.2,
                    "TotalAscent": 420,
                },
                fit_path,
                "downloaded",
            )

        assert activity.total_distance == 45200
        assert activity.total_ascent == 420

    def test_build_activity_from_existing_keeps_existing_values_when_fit_fields_are_missing(
        self, tmp_path: Path
    ):
        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = tmp_path / "fit"
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = tmp_path / "session.json"
        existing = MagicMock()
        existing.ride_id = 1
        existing.member_id = 2
        existing.title = "Existing Ride"
        existing.sport = "cycling"
        existing.sub_sport = "road"
        existing.start_time = None
        existing.total_ascent = 420
        existing.total_descent = 410
        existing.total_calories = 1200
        existing.total_distance = 45200
        existing.total_elapsed_time = 5000
        existing.total_moving_time = 4800
        existing.avg_cadence = 85
        existing.max_cadence = 110
        existing.avg_heart_rate = 140
        existing.min_heart_rate = 90
        existing.max_heart_rate = 170
        existing.avg_power = 200
        existing.max_power = 600
        existing.avg_speed = 9.2
        existing.max_speed = 15.5
        existing.avg_temperature = 22
        existing.max_temperature = 29
        existing.intensity_factor = 0.8
        existing.normalized_power = 220
        existing.training_stress_score = 90

        with (
            patch("igp_ride.service.IGPSportClient"),
            patch("igp_ride.service.ActivityDatabase"),
        ):
            service = RideSyncService(config)
            activity = service._build_activity_from_existing(
                existing,
                {"sport": "cycling"},
                tmp_path / "1.fit",
                "downloaded",
            )

        assert activity.total_distance == 45200
        assert activity.total_ascent == 420
        assert activity.avg_power == 200


class TestCredentialCleanup:
    def test_logout_deletes_credentials_and_session(self):
        config = MagicMock()
        config.db_path = ":memory:"
        config.fit_dir = Path("/tmp/fit")
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.session_file = Path("/tmp/session.json")

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase"),
            patch("igp_ride.service.delete_credentials") as mock_delete_credentials,
            patch("igp_ride.service.delete_session_data") as mock_delete_session_data,
            patch("pathlib.Path.exists", return_value=False),
        ):
            mock_client = MockClient.return_value
            mock_client.username = "stored-user"
            service = RideSyncService(config)

            service.logout()

            mock_delete_credentials.assert_called_once_with("stored-user")
            mock_delete_session_data.assert_called_once_with("stored-user")

    def test_reset_deletes_credentials_and_session(self, tmp_path: Path):
        data_dir = tmp_path / "data"
        session_dir = tmp_path / "config"
        data_dir.mkdir()
        session_dir.mkdir()

        config = MagicMock()
        config.db_path = tmp_path / "test.db"
        config.fit_dir = data_dir / "fit"
        config.username = "test"
        config.password = "test"
        config.base_url = "https://example.com"
        config.data_dir = data_dir
        config.session_file = session_dir / "session.json"

        with (
            patch("igp_ride.service.IGPSportClient") as MockClient,
            patch("igp_ride.service.ActivityDatabase"),
            patch("igp_ride.service.delete_credentials") as mock_delete_credentials,
            patch("igp_ride.service.delete_session_data") as mock_delete_session_data,
        ):
            mock_client = MockClient.return_value
            mock_client.username = "stored-user"
            service = RideSyncService(config)

            results = service.reset()

            mock_delete_credentials.assert_called_once_with("stored-user")
            mock_delete_session_data.assert_called_once_with("stored-user")
            assert {item.status for item in results} == {"deleted"}
