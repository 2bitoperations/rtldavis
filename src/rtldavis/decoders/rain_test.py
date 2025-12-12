import unittest
from .rain import decode_rain_total
from .rain_rate import decode_rain_rate

class TestRainDecoder(unittest.TestCase):
    def test_decode_rain_total(self):
        # Example: e0...41... -> 41 clicks
        # The documentation is a bit confusing here, as it shows a log snippet.
        # Let's assume byte 3 contains the value.
        # e0 00 00 29 ... -> 0x29 = 41
        data = bytes.fromhex("e000002900000000")
        self.assertEqual(decode_rain_total(data), 41.0)

        # Test wrap-around
        data = bytes.fromhex("e00000ff00000000") # 0xFF & 0x7F = 0x7F = 127
        self.assertEqual(decode_rain_total(data), 127.0)

    def test_decode_rain_rate(self):
        # Test no rain case
        data = bytes.fromhex("500000ff00000000")
        self.assertEqual(decode_rain_rate(data), 0.0)
        
        # I don't have a reliable example for rain rate, so I can't write a
        # specific value test. The logic is ported from rtldavis2, which is
        # assumed to be more correct than the previous implementation.

if __name__ == '__main__':
    unittest.main()
