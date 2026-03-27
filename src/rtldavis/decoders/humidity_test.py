import logging
import unittest

from .humidity import HumiditySensor


class TestHumidityDecoder(unittest.TestCase):
    def setUp(self):
        self.decoder = HumiditySensor(logging.getLogger())

    def test_decode_humidity(self):
        # From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol
        # a0 06 52 83 38 00 5a c8 -> 89.9%
        # data[3]=0x83=131, data[4]=0x38=56 -> ((56>>4)<<8)+131 = 768+131=899 -> 89.9%
        data = bytes.fromhex("a006528338005ac8")
        self.assertAlmostEqual(self.decoder.decode(data), 89.9, delta=0.1)

        # From our logs: a00435d12b00703a -> ~72.1%
        # data[3]=0xd1=209, data[4]=0x2b=43 -> ((43>>4)<<8)+209 = 512+209=721 -> 72.1%
        data = bytes.fromhex("a00435d12b00703a")
        self.assertAlmostEqual(self.decoder.decode(data), 72.1, delta=0.1)


if __name__ == "__main__":
    unittest.main()
