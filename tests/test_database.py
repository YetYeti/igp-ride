from __future__ import annotations

from datetime import datetime
from pathlib import Path

from igp_ride.database import ActivityDatabase
from igp_ride.models import Activity


def _make_activity(ride_id: int = 1, **overrides) -> Activity:
    defaults = dict(
        ride_id=ride_id,
        member_id=1,
        title="Test Ride",
        sport="cycling",
        sub_sport="road",
        start_time=datetime(2026, 3, 1, 10, 0, 0),
        total_distance=50000.0,
        total_moving_time=3600.0,
        total_elapsed_time=3900.0,
        total_ascent=300,
        total_descent=280,
        fit_file_path="/tmp/test.fit",
        fit_file_status="downloaded",
    )
    defaults.update(overrides)
    return Activity(**defaults)


class TestActivityDatabase:
    def test_create_and_upsert(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        activity = _make_activity()
        db.upsert(activity)
        retrieved = db.get_by_ride_id(1)
        assert retrieved is not None
        assert retrieved.ride_id == 1
        assert retrieved.title == "Test Ride"
        assert retrieved.total_distance == 50000.0
        db.close()

    def test_upsert_is_idempotent(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        a1 = _make_activity(ride_id=1, title="First")
        a2 = _make_activity(ride_id=1, title="Updated")
        db.upsert(a1)
        db.upsert(a2)
        retrieved = db.get_by_ride_id(1)
        assert retrieved is not None
        assert retrieved.title == "Updated"
        ids = db.get_all_ride_ids()
        assert ids == {1}
        db.close()

    def test_get_all_ride_ids(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        for i in range(1, 4):
            db.upsert(_make_activity(ride_id=i))
        ids = db.get_all_ride_ids()
        assert ids == {1, 2, 3}
        db.close()

    def test_list_activities(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, start_time=datetime(2026, 3, 1)))
        db.upsert(_make_activity(ride_id=2, start_time=datetime(2026, 3, 15)))
        db.upsert(_make_activity(ride_id=3, start_time=datetime(2026, 2, 1)))
        activities = db.list_activities()
        assert len(activities) == 3
        # Default order: start_time DESC
        assert activities[0].ride_id == 2
        db.close()

    def test_list_activities_with_limit(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        for i in range(1, 6):
            db.upsert(_make_activity(ride_id=i, start_time=datetime(2026, 3, i)))
        activities = db.list_activities(limit=2)
        assert len(activities) == 2
        db.close()

    def test_list_activities_with_since(self, tmp_path: Path):
        from datetime import date

        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, start_time=datetime(2026, 3, 1)))
        db.upsert(_make_activity(ride_id=2, start_time=datetime(2026, 2, 1)))
        activities = db.list_activities(since=date(2026, 3, 1))
        assert len(activities) == 1
        assert activities[0].ride_id == 1
        db.close()

    def test_get_activities_with_missing_fit(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, fit_file_status="downloaded"))
        db.upsert(_make_activity(ride_id=2, fit_file_status="missing"))
        db.upsert(_make_activity(ride_id=3, fit_file_status="invalid"))
        broken = db.get_activities_with_missing_fit()
        assert len(broken) == 2
        assert {a.ride_id for a in broken} == {2, 3}
        db.close()

    def test_sync_meta(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        assert db.get_sync_meta("last_sync_time") is None
        db.set_sync_meta("last_sync_time", "2026-03-29T10:00:00+00:00")
        assert db.get_sync_meta("last_sync_time") == "2026-03-29T10:00:00+00:00"
        # Overwrite
        db.set_sync_meta("last_sync_time", "2026-03-30T10:00:00+00:00")
        assert db.get_sync_meta("last_sync_time") == "2026-03-30T10:00:00+00:00"
        db.close()

    def test_get_by_ride_id_not_found(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        assert db.get_by_ride_id(999) is None
        db.close()
