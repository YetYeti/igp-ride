from __future__ import annotations

from datetime import datetime

from igp_ride.models import Activity, SyncSummary


class TestActivity:
    def test_default_values(self):
        a = Activity(
            ride_id=1, member_id=2, title="Test Ride", sport="cycling", sub_sport="road"
        )
        assert a.ride_id == 1
        assert a.total_distance == 0.0
        assert a.total_moving_time == 0.0
        assert a.start_time is None
        assert a.fit_file_status == "missing"

    def test_all_fields(self):
        now = datetime(2026, 3, 1, 10, 0, 0)
        a = Activity(
            ride_id=100,
            member_id=5,
            title="Morning Ride",
            sport="cycling",
            sub_sport="road",
            start_time=now,
            total_distance=50000.0,
            total_moving_time=5400.0,
            total_elapsed_time=5700.0,
            total_ascent=500,
            total_descent=480,
            avg_power=180,
            max_power=350,
            fit_file_path="/tmp/100.fit",
            fit_file_status="downloaded",
        )
        assert a.ride_id == 100
        assert a.start_time == now
        assert a.total_distance == 50000.0
        assert a.avg_power == 180


class TestSyncSummary:
    def test_defaults(self):
        s = SyncSummary()
        assert s.remote_fetched == 0
        assert s.new_activities == 0
        assert s.updated_activities == 0
        assert s.activities_skipped == 0
        assert s.fit_files_failed == 0

    def test_values(self):
        s = SyncSummary(
            remote_fetched=10,
            new_activities=3,
            updated_activities=2,
            activities_skipped=4,
            fit_files_failed=1,
        )
        assert s.remote_fetched == 10
        assert s.new_activities == 3
