"""
Emulates a real Davis console's legacy serial protocol (wakeup + WRD + LOOP)
over a plain TCP socket, well enough that the blumzi/ASCOM.VantagePro driver's
"WeatherLinkIP" operational mode (a raw socket to port 22222, no HTTP) treats
this station as a genuine WeatherLink IP-connected console.

Wire format, as expected by ASCOM.VantagePro's SerialProtocolFetcher/SocketFetcher:
  - Wakeup: client sends any byte(s); console replies "\n\r".
  - Get station type: client sends b"WRD\x12\x4d\n"; console replies ACK (0x06)
    followed by one model byte (16 = "Vantage Pro or Vantage Pro 2").
  - Get current conditions: client sends b"LOOP 1\n"; console replies ACK
    followed by a 99-byte LOOP packet: b"LOO" header, a fixed field layout,
    a "\n\r" trailer, and a big-endian CRC-16-CCITT (poly 0x1021, init 0)
    over the preceding 97 bytes such that the CRC over all 99 bytes is 0.

Only the fields ASCOM.VantagePro's SerialProtocolFetcher.ParseSensorData
actually reads are populated meaningfully (temp, wind speed/dir/gust,
humidity, barometer, rain rate); everything else is zeroed, matching how a
real console reports "no data" for fields with a driver that doesn't check
Davis's own missing-data sentinels.
"""
import asyncio
import logging
import time
from typing import Optional

from .crc import CRC
from .weatherlink import MPH_PER_KMH, HPA_PER_INHG, WindRollingWindow

logger = logging.getLogger(__name__)

ACK = 0x06
LOOP_PACKET_LEN = 99
STATION_MODEL_VANTAGE_PRO2 = 16

_CRC = CRC("Davis LOOP", 0, 0x1021, 0)


def _clamp(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, round(value)))


def _put_u16le(buf: bytearray, offset: int, value: int) -> None:
    value = _clamp(value, 0, 0xFFFF)
    buf[offset] = value & 0xFF
    buf[offset + 1] = (value >> 8) & 0xFF


def _put_i16le(buf: bytearray, offset: int, value: int) -> None:
    value = _clamp(value, -32768, 32767) & 0xFFFF
    buf[offset] = value & 0xFF
    buf[offset + 1] = (value >> 8) & 0xFF


def build_loop_packet(
    sensor_store,
    wind_window: WindRollingWindow,
    stale_after_s: float,
    now: Optional[float] = None,
) -> Optional[bytes]:
    """
    Builds a 99-byte Davis LOOP packet from the latest sensor readings.

    Fails safe: returns None if no real Davis packet has been received
    within `stale_after_s`, so the caller can refuse the request rather than
    hand out fabricated/stale conditions (mirrors the WeatherLink Live
    compatibility endpoint's staleness handling in weatherlink.py).
    """
    now = now if now is not None else time.time()
    age = wind_window.seconds_since_last_sample(now)
    if age is None or age > stale_after_s:
        return None

    readings = sensor_store.to_response()

    def val(key: str):
        entry = readings.get(key)
        return entry["value"] if entry else None

    temp_f = val("temperature") or 0.0
    humidity = val("humidity") or 0.0
    wind_speed_kmh = val("wind_speed") or 0.0
    wind_dir = val("wind_direction") or 0
    wind_gust_kmh = val("wind_gust_speed") or 0.0
    rain_rate_inhr = val("rain_rate") or 0.0

    bar_entry = readings.get("barometric_pressure")
    bar_hpa = bar_entry["value"] if bar_entry is not None else None

    buf = bytearray(LOOP_PACKET_LEN)
    buf[0:3] = b"LOO"
    buf[3] = 0  # bar trend: unknown/steady
    buf[4] = 0  # packet type 0 == classic "LOOP" (not LOOP2)

    bar_inhg_thousandths = round(bar_hpa / HPA_PER_INHG * 1000) if bar_hpa is not None else 0
    _put_u16le(buf, 7, bar_inhg_thousandths)

    _put_i16le(buf, 12, temp_f * 10)

    wind_mph = wind_speed_kmh * MPH_PER_KMH
    buf[14] = _clamp(wind_mph, 0, 255)
    buf[15] = buf[14]  # 10-min avg wind speed; not read by the driver, mirror current

    _put_u16le(buf, 16, wind_dir)

    # ASCOM.VantagePro's SerialProtocolFetcher re-multiplies this field by 10
    # before converting mph->m/s (a quirk of that driver, not the real Davis
    # spec), so pre-divide here to compensate. This caps gust resolution to
    # multiples of 10 mph on the ASCOM side -- a limitation baked into the
    # driver we're deliberately not forking.
    gust_mph = wind_gust_kmh * MPH_PER_KMH
    _put_u16le(buf, 22, gust_mph / 10.0)

    buf[33] = _clamp(humidity, 0, 100)

    # Davis convention: rain rate field is "clicks/hour" with a 0.01in bucket.
    # ASCOM.VantagePro's driver uses this raw value directly with no unit
    # conversion, so the ASCOM RainRate property will read in hundredths-of-
    # an-inch-per-hour rather than true in/h -- another upstream driver quirk.
    _put_u16le(buf, 41, rain_rate_inhr * 100)

    buf[95] = 0x0A  # \n
    buf[96] = 0x0D  # \r

    crc_val = int(_CRC.checksum(bytes(buf[0:97])))
    buf[97] = (crc_val >> 8) & 0xFF
    buf[98] = crc_val & 0xFF

    return bytes(buf)


async def _handle_console(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    sensor_store,
    wind_window: WindRollingWindow,
    stale_after_s: float,
    station_model: int,
) -> None:
    peer = writer.get_extra_info("peername")
    sockname = writer.get_extra_info("sockname")
    start = time.monotonic()
    logger.info(f"Console: connection accepted from {peer} on {sockname}")

    def elapsed() -> str:
        return f"{time.monotonic() - start:.3f}s"

    try:
        # Wakeup: any byte wakes a real console, which replies "\n\r".
        try:
            first_byte = await asyncio.wait_for(reader.read(1), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"Console: {peer} sent no wakeup byte within 5s (t={elapsed()}) -- giving up")
            return
        if not first_byte:
            logger.info(f"Console: {peer} closed the connection before sending a wakeup byte (t={elapsed()})")
            return
        logger.info(f"Console: {peer} wakeup byte {first_byte!r} (t={elapsed()}); replying b'\\n\\r'")
        writer.write(b"\n\r")
        await writer.drain()
        logger.debug(f"Console: {peer} wakeup reply flushed (t={elapsed()})")

        try:
            line = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(
                f"Console: {peer} sent no command line within 5s of the wakeup reply "
                f"(t={elapsed()}) -- giving up"
            )
            return
        logger.info(f"Console: {peer} command {line!r} (t={elapsed()})")

        if line.startswith(b"WRD"):
            logger.info(f"Console: {peer} station-type request -> ACK + model {station_model} (t={elapsed()})")
            writer.write(bytes([ACK, station_model]))
            await writer.drain()
        elif line.strip() == b"LOOP 1":
            age = wind_window.seconds_since_last_sample()
            packet = build_loop_packet(sensor_store, wind_window, stale_after_s)
            if packet is None:
                logger.warning(
                    f"Console: {peer} requested LOOP data but no Davis packet has been "
                    f"received in the last {stale_after_s}s (last sample age: "
                    f"{'never' if age is None else f'{age:.1f}s'}) -- refusing, no ACK sent (t={elapsed()})"
                )
                return
            logger.info(f"Console: {peer} LOOP request -> ACK + {len(packet)}-byte packet (t={elapsed()})")
            writer.write(bytes([ACK]))
            writer.write(packet)
            await writer.drain()
        else:
            logger.warning(f"Console: {peer} sent unrecognized command {line!r} (t={elapsed()})")
    except asyncio.IncompleteReadError as exc:
        logger.warning(
            f"Console: {peer} connection closed mid-read ({len(exc.partial)} bytes received "
            f"before EOF, terminator not found) (t={elapsed()}): partial={exc.partial!r}"
        )
    except ConnectionError as exc:
        logger.warning(f"Console: {peer} connection error (t={elapsed()}): {exc!r}")
    except Exception:
        logger.exception(f"Console: {peer} unexpected error handling connection (t={elapsed()})")
    finally:
        writer.close()
        logger.info(f"Console: connection from {peer} closed (t={elapsed()})")


async def start_console_server(
    port: int,
    sensor_store,
    wind_window: WindRollingWindow,
    stale_after_s: float,
    station_model: int = STATION_MODEL_VANTAGE_PRO2,
) -> None:
    """
    Starts the Davis-console-emulating TCP server used by ASCOM.VantagePro's
    "WeatherLinkIP" operational mode.
    """
    server = await asyncio.start_server(
        lambda r, w: _handle_console(r, w, sensor_store, wind_window, stale_after_s, station_model),
        host="0.0.0.0",
        port=port,
    )
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.warning(f"Davis console emulator (ASCOM WeatherLinkIP) listening on {addrs}")
    async with server:
        await server.serve_forever()
