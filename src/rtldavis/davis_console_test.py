import asyncio
import unittest
from types import SimpleNamespace

from .crc import CRC
from .sensor_store import SensorStore
from .weatherlink import WindRollingWindow
from .davis_console import (
    ACK,
    LOOP_PACKET_LEN,
    STATION_MODEL_VANTAGE_PRO2,
    build_loop_packet,
    start_console_server,
)

_CRC = CRC("CCITT-16", 0, 0x1021, 0)


def _msg(**sensor_values):
    return SimpleNamespace(sensor_values=sensor_values)


class TestBuildLoopPacket(unittest.TestCase):
    def setUp(self):
        self.store = SensorStore()
        self.window = WindRollingWindow()

    def test_stale_with_no_samples_returns_none(self):
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=1000)
        self.assertIsNone(packet)

    def test_stale_with_old_sample_returns_none(self):
        self.window.record(10.0, timestamp=0)
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=1000)
        self.assertIsNone(packet)

    def test_fresh_data_has_valid_header_trailer_and_crc(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=now)

        self.assertIsNotNone(packet)
        self.assertEqual(len(packet), LOOP_PACKET_LEN)
        self.assertEqual(packet[0:3], b"LOO")
        self.assertEqual(packet[4], 0)
        self.assertEqual(packet[95:97], b"\n\r")
        # A valid Davis-style CRC-CCITT trailer makes the checksum over the
        # *entire* packet (payload + trailer) come out to 0.
        self.assertEqual(_CRC.checksum(packet), 0)

    def test_temperature_and_humidity_fields(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        self.store.update(_msg(temperature=68.4, humidity=45.0))
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=now)

        temp_raw = packet[12] | (packet[13] << 8)
        self.assertEqual(temp_raw, 684)  # 68.4F * 10
        self.assertEqual(packet[33], 45)  # humidity, whole percent

    def test_wind_speed_direction_and_gust_conversion(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        # 16.0934 km/h == 10 mph
        self.store.update(_msg(wind_speed=16.0934, wind_direction=270, wind_gust_speed=160.934))
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=now)

        self.assertEqual(packet[14], 10)  # wind speed, whole mph
        dir_raw = packet[16] | (packet[17] << 8)
        self.assertEqual(dir_raw, 270)
        # gust: 160.934 km/h == 100 mph; driver re-multiplies this field by
        # 10 on its side, so we pre-divide (100 / 10 == 10) to compensate.
        gust_raw = packet[22] | (packet[23] << 8)
        self.assertEqual(gust_raw, 10)

    def test_rain_rate_encoded_as_hundredths_per_hour(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        self.store.update(_msg(rain_rate=0.5))
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=now)

        rain_raw = packet[41] | (packet[42] << 8)
        self.assertEqual(rain_raw, 50)  # 0.5 in/h -> 50 clicks/hr @ 0.01in bucket

    def test_barometer_zero_when_no_bme280_reading(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=now)

        bar_raw = packet[7] | (packet[8] << 8)
        self.assertEqual(bar_raw, 0)

    def test_barometer_populated_when_bme280_reading_present(self):
        now = 1000.0
        self.window.record(10.0, timestamp=now - 5)
        self.store.update(_msg(barometric_pressure=1013.25))
        packet = build_loop_packet(self.store, self.window, stale_after_s=60, now=now)

        bar_raw = packet[7] | (packet[8] << 8)
        # 1013.25 hPa -> ~29.921 inHg -> ~29921 thousandths
        self.assertAlmostEqual(bar_raw, 29921, delta=2)


class TestConsoleServerHandshake(unittest.IsolatedAsyncioTestCase):
    """
    Exercises the wire protocol via the same per-connection handler
    start_console_server() installs, bound directly to an ephemeral port
    (start_console_server itself blocks forever in serve_forever(), so it
    can't hand its bound port back out for a test to connect to).
    """

    async def asyncSetUp(self):
        self.store = SensorStore()
        self.window = WindRollingWindow()

        from .davis_console import _handle_console

        self.server = await asyncio.start_server(
            lambda r, w: _handle_console(r, w, self.store, self.window, 60, STATION_MODEL_VANTAGE_PRO2),
            host="127.0.0.1",
            port=0,
        )
        self.port = self.server.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_wrd_command_returns_ack_and_model_byte(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"\r")
        await writer.drain()
        wakeup = await reader.readexactly(2)
        self.assertEqual(wakeup, b"\n\r")

        writer.write(b"WRD\x12\x4d\n")
        await writer.drain()
        reply = await reader.readexactly(2)
        self.assertEqual(reply[0], ACK)
        self.assertEqual(reply[1], STATION_MODEL_VANTAGE_PRO2)
        writer.close()

    async def test_loop_command_returns_ack_and_packet_when_fresh(self):
        self.window.record(10.0, timestamp=None)
        self.store.update(_msg(temperature=70.0, humidity=50.0))

        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"\r")
        await writer.drain()
        await reader.readexactly(2)

        writer.write(b"LOOP 1\n")
        await writer.drain()
        ack = await reader.readexactly(1)
        self.assertEqual(ack[0], ACK)
        packet = await reader.readexactly(LOOP_PACKET_LEN)
        self.assertEqual(packet[0:3], b"LOO")
        self.assertEqual(_CRC.checksum(packet), 0)
        writer.close()

    async def test_loop_command_closes_connection_without_ack_when_stale(self):
        # No samples recorded -> build_loop_packet returns None -> fail-safe refusal.
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(b"\r")
        await writer.drain()
        await reader.readexactly(2)

        writer.write(b"LOOP 1\n")
        await writer.drain()
        remaining = await reader.read(1)
        self.assertEqual(remaining, b"")
        writer.close()


class TestStartConsoleServer(unittest.IsolatedAsyncioTestCase):
    async def test_binds_and_accepts_a_connection(self):
        store = SensorStore()
        window = WindRollingWindow()
        server_task = asyncio.create_task(
            start_console_server(0, store, window, stale_after_s=60)
        )
        try:
            # start_console_server doesn't expose its bound port, but its
            # startup log line (via the module logger) fires right after
            # asyncio.start_server() returns; a short sleep is enough for
            # that bind to have happened before we assert the task is alive.
            await asyncio.sleep(0.05)
            self.assertFalse(server_task.done())
        finally:
            server_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await server_task


if __name__ == "__main__":
    unittest.main()
