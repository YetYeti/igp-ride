from __future__ import annotations

import pytest

from igp_ride.parser import normalize_session_data, parse_fit_file


class TestNormalizeSessionData:
    def test_empty_sessions(self):
        assert normalize_session_data({"session": []}) == {}

    def test_no_session_key(self):
        assert normalize_session_data({}) == {}

    def test_basic_session(self):
        data = {
            "session": [
                {
                    "total_distance": 25000.0,
                    "total_moving_time": 3600.0,
                    "total_elapsed_time": 3900.0,
                    "avg_power": 150,
                    "max_power": 300,
                    "avg_heart_rate": 130,
                    "max_heart_rate": 170,
                }
            ]
        }
        result = normalize_session_data(data)
        assert result["total_distance"] == 25000.0
        assert result["total_moving_time"] == 3600.0
        assert result["avg_power"] == 150
        assert result["max_heart_rate"] == 170

    def test_missing_fields_use_defaults(self):
        data = {"session": [{}]}
        result = normalize_session_data(data)
        assert result["total_distance"] == 0.0
        assert result["avg_power"] == 0
        assert result["sport"] == "cycling"

    def test_sport_and_sub_sport(self):
        data = {"session": [{"sport": "running", "sub_sport": "trail"}]}
        result = normalize_session_data(data)
        assert result["sport"] == "running"
        assert result["sub_sport"] == "trail"


class TestParseFitFile:
    def test_nonexistent_file(self):
        with pytest.raises(Exception):
            parse_fit_file("/nonexistent/path/file.fit")
