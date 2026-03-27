import logging
import unittest

from .temperature import TemperatureSensor


class TestTemperatureDecoder(unittest.TestCase):
    def setUp(self):
        self.decoder = TemperatureSensor(logging.getLogger())

    def test_decode_temperature(self):
        # From our logs: 80052c2cf90b649e -> Expected ~71.95F
        # Formula: ((data[3] << 8) | data[4]) / 160.0
        # data[3]=0x2c, data[4]=0xf9 -> 0x2cf9=11513 -> 11513/160=71.95625
        data = bytes.fromhex("80052c2cf90b649e")
        self.assertAlmostEqual(self.decoder.decode(data), 71.95, delta=0.1)


if __name__ == "__main__":
    unittest.main()
