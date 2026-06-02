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

    def test_list_activities_can_sort_by_distance_ascending(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, total_distance=50000))
        db.upsert(_make_activity(ride_id=2, total_distance=32000))
        db.upsert(_make_activity(ride_id=3, total_distance=78000))
        activities = db.list_activities(sort_by="distance", descending=False)
        assert [activity.ride_id for activity in activities] == [2, 1, 3]
        db.close()

    def test_list_activities_can_sort_by_power_descending(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, avg_power=180))
        db.upsert(_make_activity(ride_id=2, avg_power=260))
        db.upsert(_make_activity(ride_id=3, avg_power=150))
        activities = db.list_activities(sort_by="power", descending=True)
        assert [activity.ride_id for activity in activities] == [2, 1, 3]
        db.close()

    def test_list_activities_keeps_missing_power_last(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, avg_power=0))
        db.upsert(_make_activity(ride_id=2, avg_power=220))
        db.upsert(_make_activity(ride_id=3, avg_power=150))
        activities = db.list_activities(sort_by="power", descending=False)
        assert [activity.ride_id for activity in activities] == [3, 2, 1]
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

    def test_force_icu_sync_returns_already_synced_downloads(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, fit_file_status="downloaded"))
        db.upsert(_make_activity(ride_id=2, fit_file_status="downloaded"))
        db.mark_icu_synced(
            2,
            icu_activity_id="icu-2",
            icu_external_id="igp-2",
            synced_at=datetime(2026, 3, 2),
        )

        pending = db.get_activities_pending_icu_sync()
        forced = db.get_activities_pending_icu_sync(force=True)

        assert [activity.ride_id for activity in pending] == [1]
        assert [activity.ride_id for activity in forced] == [1, 2]
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

    def test_icu_sync_status_defaults_to_pending(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1))

        activity = db.get_by_ride_id(1)

        assert activity is not None
        assert activity.icu_activity_id == ""
        assert activity.icu_external_id == ""
        assert activity.icu_synced_at is None
        assert activity.icu_sync_status == "pending"
        assert activity.icu_sync_error == ""
        db.close()

    def test_get_activities_pending_icu_sync(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, fit_file_status="downloaded"))
        db.upsert(_make_activity(ride_id=2, fit_file_status="missing"))
        db.upsert(_make_activity(ride_id=3, fit_file_status="downloaded"))
        db.mark_icu_synced(
            3,
            icu_activity_id="icu-3",
            icu_external_id="igp-3",
            synced_at=datetime(2026, 3, 1, 12, 0, 0),
        )

        pending = db.get_activities_pending_icu_sync()

        assert [activity.ride_id for activity in pending] == [1]
        db.close()

    def test_mark_icu_sync_failed_can_be_retried_when_requested(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, fit_file_status="downloaded"))
        db.mark_icu_sync_failed(1, icu_external_id="igp-1", error="upload failed")

        assert db.get_activities_pending_icu_sync() == []
        pending = db.get_activities_pending_icu_sync(include_failed=True)

        assert [activity.ride_id for activity in pending] == [1]
        assert pending[0].icu_external_id == "igp-1"
        assert pending[0].icu_sync_status == "failed"
        assert pending[0].icu_sync_error == "upload failed"
        db.close()

    def test_get_by_ride_id_not_found(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        assert db.get_by_ride_id(999) is None
        db.close()

    def test_set_get_and_clear_activity_note(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1))

        note = db.set_activity_note(1, "  Legs felt good.  ")
        retrieved = db.get_activity_note(1)

        assert note.note == "Legs felt good."
        assert retrieved is not None
        assert retrieved.note == "Legs felt good."
        assert retrieved.icu_note_sync_status == "pending"
        assert db.clear_activity_note(1) is True
        assert db.get_activity_note(1) is None
        db.close()

    def test_activity_note_requires_existing_activity(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")

        try:
            db.set_activity_note(999, "Missing")
        except Exception as exc:
            assert "Activity not found: 999" in str(exc)
        else:
            raise AssertionError("Expected missing activity error")
        db.close()

    def test_activity_note_sync_state_tracks_hash_changes(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1))
        note = db.set_activity_note(1, "First note")
        db.mark_activity_note_icu_synced(
            1,
            note_hash=note.note_hash,
            synced_at=datetime(2026, 3, 2, 12, 0, 0),
        )

        same_note = db.set_activity_note(1, "First note")
        changed_note = db.set_activity_note(1, "Changed note")

        assert same_note.icu_note_sync_status == "synced"
        assert changed_note.icu_note_sync_status == "pending"
        assert changed_note.icu_note_synced_hash == note.note_hash
        db.close()

    def test_get_activities_pending_icu_note_sync(self, tmp_path: Path):
        db = ActivityDatabase(tmp_path / "test.db")
        db.upsert(_make_activity(ride_id=1, fit_file_status="downloaded"))
        db.upsert(_make_activity(ride_id=2, fit_file_status="missing"))
        db.upsert(_make_activity(ride_id=3, fit_file_status="downloaded"))
        note_1 = db.set_activity_note(1, "Pending note")
        note_2 = db.set_activity_note(2, "Missing fit note")
        note_3 = db.set_activity_note(3, "Synced note")
        db.mark_activity_note_icu_synced(
            2,
            note_hash=note_2.note_hash,
            synced_at=datetime(2026, 3, 2, 12, 0, 0),
        )
        db.mark_activity_note_icu_synced(
            3,
            note_hash=note_3.note_hash,
            synced_at=datetime(2026, 3, 2, 12, 0, 0),
        )
        db.set_activity_note(3, "Changed note")

        pending = db.get_activities_pending_icu_note_sync()

        assert note_1.note_hash
        assert [activity.ride_id for activity in pending] == [1, 3]
        db.close()
