import logging
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
        for key in ("rain_total_raw", "rain_total_hourly", "rain_total_daily", "rain_total_weekly"):
            self.assertIn(key, result)


class TestRainRateDecoder(unittest.TestCase):
    def setUp(self):
        self.decoder = RainRateSensor(logging.getLogger())

    def test_no_rain_ff(self):
        # Byte 3 == 0xFF signals no rain
        data = bytes.fromhex("500000ff00000000")
        self.assertEqual(self.decoder.decode(data), 0.0)


if __name__ == "__main__":
    unittest.main()
