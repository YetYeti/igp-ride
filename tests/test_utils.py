from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from igp_ride.utils import format_duration, get_config_dir, get_data_dir, get_log_dir


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


class TestSetupLogging:
    def _reset(self):
        import logging

        from igp_ride import utils

        utils._logging_initialized = False
        logger = logging.getLogger("igp_ride")
        logger.handlers = []
        return utils, logger

    def test_verbose_mirrors_debug_to_console(self):
        import logging

        utils, logger = self._reset()
        try:
            with patch("igp_ride.utils.RotatingFileHandler"):
                utils.setup_logging(verbose=True)
            console_levels = [
                h.level
                for h in logger.handlers
                if type(h).__name__ == "StreamHandler"
            ]
            assert logging.DEBUG in console_levels
        finally:
            logger.handlers = []
            utils._logging_initialized = False

    def test_default_keeps_console_at_warning(self):
        import logging

        utils, logger = self._reset()
        try:
            with patch("igp_ride.utils.RotatingFileHandler"):
                utils.setup_logging(verbose=False)
            console_levels = [
                h.level
                for h in logger.handlers
                if type(h).__name__ == "StreamHandler"
            ]
            assert console_levels == [logging.WARNING]
        finally:
            logger.handlers = []
            utils._logging_initialized = False


class TestPlatformDirs:
    def test_get_config_dir_uses_platformdirs(self):
        with (
            patch("igp_ride.utils.sys.platform", "win32"),
            patch(
                "igp_ride.utils.user_config_path",
                return_value="C:/Users/demo/AppData/Roaming/igp-ride",
            ),
        ):
            assert get_config_dir() == Path("C:/Users/demo/AppData/Roaming/igp-ride")

    def test_get_data_dir_uses_platformdirs(self):
        with (
            patch("igp_ride.utils.sys.platform", "win32"),
            patch(
                "igp_ride.utils.user_data_path",
                return_value="C:/Users/demo/AppData/Local/igp-ride",
            ),
        ):
            assert get_data_dir() == Path("C:/Users/demo/AppData/Local/igp-ride")

    def test_get_log_dir_uses_platformdirs(self):
        with (
            patch("igp_ride.utils.sys.platform", "win32"),
            patch(
                "igp_ride.utils.user_log_path",
                return_value="C:/Users/demo/AppData/Local/igp-ride/Logs",
            ),
        ):
            assert get_log_dir() == Path("C:/Users/demo/AppData/Local/igp-ride/Logs")
