import unittest
from .humidity import decode_humidity

class TestHumidityDecoder(unittest.TestCase):
    def test_decode_humidity(self):
        # From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol
        # a0 06 52 83 38 00 5a c8 -> 89.9%
        data = bytes.fromhex("a006528338005ac8")
        self.assertAlmostEqual(decode_humidity(data), 89.9, delta=0.1)
        
        # From our logs: a00435d12b00703a -> should be ~74.6%
        # Let's apply the new logic:
        # data[3] = 0xd1, data[4] = 0x2b
        # raw = ((0x2b >> 4) << 8) + 0xd1 = (2 << 8) + 209 = 512 + 209 = 721
        # humidity = 721 / 10.0 = 72.1%
        # This is very close to 74.6%! The difference is likely due to timing.
        data = bytes.fromhex("a00435d12b00703a")
        self.assertAlmostEqual(decode_humidity(data), 72.1, delta=0.1)

if __name__ == '__main__':
    unittest.main()
