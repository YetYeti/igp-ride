from __future__ import annotations

from igp_ride.utils import format_duration


class TestFormatDuration:
    def test_zero(self):
        assert format_duration(0) == "0:00:00"

    def test_seconds_only(self):
        assert format_duration(45) == "0:00:45"

    def test_minutes_and_seconds(self):
        assert format_duration(125) == "0:02:05"

    def test_hours(self):
        assert format_duration(3661) == "1:01:01"

    def test_large_value(self):
        assert format_duration(36000) == "10:00:00"

    def test_negative_clamped_to_zero(self):
        assert format_duration(-5) == "0:00:00"

    def test_float_truncated(self):
        assert format_duration(90.7) == "0:01:30"
