import logging
import time
import unittest

from .rain import RainTotalSensor
from .rain_rate import RainRateSensor


def _packet(click_byte: int) -> bytes:
    """Build a minimal 8-byte rain packet with the given byte-3 value."""
    data = bytearray(8)
    data[3] = click_byte & 0xFF
    return bytes(data)


class TestRainTotalDecoder(unittest.TestCase):
    def setUp(self):
        self.decoder = RainTotalSensor(logging.getLogger())

    def test_accumulates_over_packets(self):
        # First packet establishes the baseline counter; no cumulative total yet.
        result = self.decoder.decode(_packet(0x00))
        self.assertAlmostEqual(result["rain_total_raw"], 0.0, delta=0.001)

        # Second packet: counter advances to 0x29=41 clicks -> 41*0.01=0.41 in
        result = self.decoder.decode(_packet(0x29))
        self.assertAlmostEqual(result["rain_total_raw"], 0.41, delta=0.001)

    def test_rollover_not_added_to_total(self):
        # Build up a known total first
        self.decoder.decode(_packet(0x00))   # baseline
        self.decoder.decode(_packet(0x7F))   # +127 clicks -> 1.27 in
        total_before = self.decoder.decode(_packet(0x7F))["rain_total_raw"]

        # Counter wraps to a lower value - rollover should not be added
        result = self.decoder.decode(_packet(0x0A))
        self.assertAlmostEqual(result["rain_total_raw"], total_before, delta=0.001)

    def test_result_contains_all_keys(self):
        self.decoder.decode(_packet(0x00))
        result = self.decoder.decode(_packet(0x01))
        for key in ("rain_total_raw", "rain_total_15min", "rain_total_hourly",
                    "rain_total_daily", "rain_total_weekly"):
            self.assertIn(key, result)

    def test_15min_window_excludes_clicks_older_than_15_minutes(self):
        self.decoder.decode(_packet(0x00))   # baseline
        result = self.decoder.decode(_packet(0x05))  # +5 clicks, all recorded "now"

        # All 5 clicks are fresh, so they should count towards the 15-minute window.
        self.assertAlmostEqual(result["rain_total_15min"], 0.05, delta=0.001)

        # Manually age out all but one of the recorded click timestamps, as if
        # they'd actually happened 20 minutes ago.
        twenty_min_ago = time.time() - 1200
        for i in range(len(self.decoder.clicks_history) - 1):
            self.decoder.clicks_history[i] = twenty_min_ago

        # Re-decoding the same counter value (no new clicks) should now report
        # only the one click timestamp that's still within the 15-minute window.
        result = self.decoder.decode(_packet(0x05))
        self.assertAlmostEqual(result["rain_total_15min"], 0.01, delta=0.001)


class TestRainRateDecoder(unittest.TestCase):
    def setUp(self):
        self.decoder = RainRateSensor(logging.getLogger())

    def test_no_rain_ff(self):
        # Byte 3 == 0xFF signals no rain
        data = bytes.fromhex("500000ff00000000")
        self.assertEqual(self.decoder.decode(data), 0.0)


if __name__ == "__main__":
    unittest.main()
