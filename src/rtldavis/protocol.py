import logging
import math
import random
from enum import Enum
from typing import List, NamedTuple, Dict, Set, Optional
from dataclasses import dataclass
import time
from datetime import datetime, timezone, timedelta

import numpy as np

from . import crc, dsp
from .decoders import (
    decode_temperature,
    decode_humidity,
    decode_rain_total,
    decode_rain_rate,
    decode_supercap,
    decode_uv,
    decode_solar,
)

logger = logging.getLogger(__name__)


class Sensor(Enum):
    SUPER_CAP_VOLTAGE = 2
    UV_INDEX = 4
    RAIN_RATE = 5
    SOLAR_RADIATION = 6
    LIGHT = 7
    TEMPERATURE = 8
    WIND_GUST_SPEED = 9
    HUMIDITY = 0xA
    RAIN = 0xE


@dataclass
class Message:
    packet: dsp.Packet
    id: int
    sensor: Optional[Sensor]
    wind_speed: int
    wind_direction: int
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    rain_rate: Optional[float] = None
    rain_total: Optional[float] = None
    solar_radiation: Optional[float] = None
    uv_index: Optional[float] = None
    wind_gust_speed: Optional[int] = None
    super_cap_voltage: Optional[float] = None
    light: Optional[float] = None
    raw_sensor_id: Optional[int] = None
    rssi: Optional[float] = None
    snr: Optional[float] = None


class Hop(NamedTuple):
    channel_idx: int
    channel_freq: int
    freq_error: int


def new_packet_config(symbol_length: int) -> dsp.PacketConfig:
    return dsp.PacketConfig(
        bit_rate=19200,
        symbol_length=symbol_length,
        preamble_symbols=16,
        packet_symbols=80,
        preamble="1100101110001001",
    )


def swap_bit_order(b: int) -> int:
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
    b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
    return b


class Parser:
    def __init__(self, symbol_length: int, station_id: Optional[int] = None) -> None:
        self.cfg: dsp.PacketConfig = new_packet_config(symbol_length)
        self.demodulator: dsp.Demodulator = dsp.Demodulator(self.cfg)
        self.crc: crc.CRC = crc.CRC("CCITT-16", 0, 0x1021, 0)
        self.id: Optional[int] = station_id
        self.dwell_time: float = 2.5625 + (station_id or 0) * 0.0625

        self.channels: List[int] = [
            902355835, 902857585, 903359336, 903861086, 904362837, 904864587,
            905366338, 905868088, 906369839, 906871589, 907373340, 907875090,
            908376841, 908878591, 909380342, 909882092, 910383843, 910885593,
            911387344, 911889094, 912390845, 912892595, 913394346, 913896096,
            914397847, 914899597, 915401347, 915903098, 916404848, 916906599,
            917408349, 917910100, 918411850, 918913601, 919415351, 919917102,
            920418852, 920920603, 921422353, 921924104, 922425854, 922927605,
            923429355, 923931106, 924432856, 924934607, 925436357, 925938108,
            926439858, 926941609, 927443359,
        ]
        self.channel_count: int = len(self.channels)

        self.hop_pattern: List[int] = [
            0, 19, 41, 25, 8, 47, 32, 13, 36, 22, 3, 29, 44, 16, 5, 27, 38, 10,
            49, 21, 2, 30, 42, 14, 48, 7, 24, 34, 45, 1, 17, 39, 26, 9, 31, 50,
            37, 12, 20, 33, 4, 43, 28, 15, 35, 6, 40, 11, 23, 46, 18,
        ]
        self.hop_idx: int = random.randint(0, self.channel_count - 1)

        self.channel_freq_err: Dict[int, int] = {}
        self.current_freq_err: int = 0

    def hop(self) -> Hop:
        channel_idx = self.hop_pattern[self.hop_idx]
        channel_freq = self.channels[channel_idx]

        if channel_idx in self.channel_freq_err:
            self.current_freq_err = self.channel_freq_err[channel_idx]

        return Hop(channel_idx, channel_freq, self.current_freq_err)

    def next_hop(self) -> Hop:
        self.hop_idx = (self.hop_idx + 1) % self.channel_count
        return self.hop()

    def rand_hop(self) -> Hop:
        self.hop_idx = random.randint(0, self.channel_count - 1)
        return self.hop()

    def parse(self, pkts: List[dsp.Packet]) -> List[Message]:
        seen: Set[bytes] = set()
        msgs: List[Message] = []
        for pkt in pkts:
            data = bytes(swap_bit_order(b) for b in pkt.data)

            if data in seen:
                continue
            seen.add(data)

            # The CRC is calculated on the first 6 bytes of the 8-byte message payload
            # The last 2 bytes of the 8-byte payload are the CRC itself
            # The full 10-byte packet from the SDR includes 2 bytes of repeater info
            # which we are ignoring for now.
            # Our `pkt.data` is 10 bytes. Let's assume the first 8 are the message.
            msg_payload = data[:8]
            
            # The CRC check in the original Go code `p.Checksum(pkt.Data[2:])` seems
            # incorrect based on the Davis docs. A full 8-byte check should result in 0.
            # Let's try that.
            if self.crc.checksum(msg_payload) != 0:
                logger.debug("CRC check failed")
                continue

            logger.info("CRC check OK. RSSI: %.2f dB, SNR: %.2f dB", pkt.rssi, pkt.snr)

            lower = pkt.index + 8 * self.cfg.symbol_length
            upper = pkt.index + 24 * self.cfg.symbol_length
            tail = self.demodulator.discriminated[lower:upper]

            mean = np.mean(tail)
            freq_error = -int(9600 + (mean * self.cfg.sample_rate) / (2 * math.pi))

            self.channel_freq_err[self.hop_pattern[self.hop_idx]] = self.current_freq_err + freq_error
            self.current_freq_err += freq_error
            logger.info("Frequency error: %d Hz", freq_error)

            msg_data = msg_payload
            msg_id = msg_data[0] & 0x7 # 3 bits for ID

            if self.id is not None and msg_id != self.id:
                logger.info("Ignoring message for station ID %d", msg_id)
                continue

            sensor_id = msg_data[0] >> 4
            try:
                sensor = Sensor(sensor_id)
            except ValueError:
                logger.warning("Unknown sensor type: 0x%02X", sensor_id)
                msg = Message(
                    packet=pkt,
                    id=msg_id,
                    sensor=None,
                    wind_speed=msg_data[1],
                    wind_direction=msg_data[2],
                    raw_sensor_id=sensor_id,
                    rssi=pkt.rssi,
                    snr=pkt.snr,
                )
                raw_hex = msg_data.hex()
                log_msg = f"Partially decoded message for station ID {msg.id} (sensor: Unknown):\n"
                log_msg += f"  Raw data:      {raw_hex}\n"
                log_msg += f"  - Header:      {raw_hex[0:2]} (Sensor ID: {sensor_id}, Station ID: {msg.id})\n"
                log_msg += f"  - Wind Speed:    {raw_hex[2:4]} ({msg.wind_speed} mph)\n"
                log_msg += f"  - Wind Dir:      {raw_hex[4:6]} ({msg.wind_direction} deg)\n"
                log_msg += f"  - Sensor data: {raw_hex[6:]} (Unknown sensor type)\n"
                logger.info(log_msg)
                msgs.append(msg)
                continue

            # Log raw data for debugging
            if sensor not in [Sensor.TEMPERATURE, Sensor.WIND_GUST_SPEED]:
                try:
                    with open("sensor.log", "a") as f:
                        ts = time.time()
                        ct = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=-5)))
                        f.write(f"{ts} {ct.isoformat()} {msg_data.hex()}\n")
                except Exception as e:
                    logger.error(f"Failed to write to sensor.log: {e}")

            msg = self._parse_sensor_data(pkt, msg_id, sensor, msg_data)

            raw_hex = msg_data.hex()
            log_msg = f"Decoded message for station ID {msg.id} (sensor: {sensor.name if sensor else 'Unknown'}):\n"
            log_msg += f"  Raw data:      {raw_hex}\n"
            log_msg += f"  - Header:      {raw_hex[0:2]} (Sensor ID: {sensor_id}, Station ID: {msg.id})\n"
            log_msg += f"  - Wind Speed:    {raw_hex[2:4]} ({msg.wind_speed} mph)\n"
            log_msg += f"  - Wind Dir:      {raw_hex[4:6]} ({msg.wind_direction} deg)\n"

            sensor_data_hex = raw_hex[6:]
            log_msg += f"  - Sensor data ({sensor.name if sensor else 'Unknown'}): {sensor_data_hex}\n"
            if msg.temperature is not None:
                log_msg += f"    - Temperature: {msg.temperature}°F\n"
            if msg.humidity is not None:
                log_msg += f"    - Humidity: {msg.humidity}%\n"
            if msg.rain_rate is not None:
                log_msg += f"    - Rain Rate: {msg.rain_rate} in/hr\n"
            if msg.rain_total is not None:
                log_msg += f"    - Rain Total: {msg.rain_total} clicks\n"
            if msg.uv_index is not None:
                log_msg += f"    - UV Index: {msg.uv_index}\n"
            if msg.solar_radiation is not None:
                log_msg += f"    - Solar Radiation: {msg.solar_radiation} W/m^2\n"
            if msg.wind_gust_speed is not None:
                log_msg += f"    - Wind Gust Speed: {msg.wind_gust_speed} mph\n"
            if msg.super_cap_voltage is not None:
                log_msg += f"    - Super Cap Voltage: {msg.super_cap_voltage} V\n"
            if msg.light is not None:
                log_msg += f"    - Light: {msg.light}\n"


            logger.info(log_msg)
            msgs.append(msg)
        return msgs

    def _parse_sensor_data(self, pkt: dsp.Packet, msg_id: int, sensor: Sensor, msg_data: bytes) -> Message:
        temp = None
        humidity = None
        rain_rate = None
        rain_total = None
        solar_radiation = None
        uv_index = None
        wind_gust_speed = None
        super_cap_voltage = None
        light = None

        try:
            if sensor == Sensor.TEMPERATURE:
                temp = decode_temperature(msg_data)
            elif sensor == Sensor.HUMIDITY:
                humidity = decode_humidity(msg_data)
            elif sensor == Sensor.RAIN_RATE:
                rain_rate = decode_rain_rate(msg_data)
            elif sensor == Sensor.RAIN:
                rain_total = decode_rain_total(msg_data)
            elif sensor == Sensor.UV_INDEX:
                uv_index = decode_uv(msg_data)
            elif sensor == Sensor.SOLAR_RADIATION:
                solar_radiation = decode_solar(msg_data)
            elif sensor == Sensor.WIND_GUST_SPEED:
                wind_gust_speed = msg_data[3]
            elif sensor == Sensor.SUPER_CAP_VOLTAGE:
                super_cap_voltage = decode_supercap(msg_data)
            elif sensor == Sensor.LIGHT:
                # No specific decoder found, keeping previous logic for now
                light_raw = (msg_data[3] << 8 | msg_data[4]) & 0x3FF
                light = float(light_raw)
        except Exception as e:
            logger.error(f"Failed to decode sensor {sensor.name}: {e}")


        return Message(
            packet=pkt,
            id=msg_id,
            sensor=sensor,
            wind_speed=msg_data[1],
            wind_direction=msg_data[2],
            temperature=temp,
            humidity=humidity,
            rain_rate=rain_rate,
            rain_total=rain_total,
            solar_radiation=solar_radiation,
            uv_index=uv_index,
            wind_gust_speed=wind_gust_speed,
            super_cap_voltage=super_cap_voltage,
            light=light,
            rssi=pkt.rssi,
            snr=pkt.snr,
        )
