import logging
import math
import random
from enum import Enum
from typing import List, NamedTuple, Dict, Set, Optional
from dataclasses import dataclass

import numpy as np

from . import crc, dsp

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
    raw_sensor_id: Optional[int] = None


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

            checksum = self.crc.checksum(data[2:])
            if checksum != 0:
                logger.debug("CRC check failed: 0x%04X", checksum)
                continue

            logger.info("CRC check OK")

            lower = pkt.index + 8 * self.cfg.symbol_length
            upper = pkt.index + 24 * self.cfg.symbol_length
            tail = self.demodulator.discriminated[lower:upper]

            mean = np.mean(tail)
            freq_error = -int(9600 + (mean * self.cfg.sample_rate) / (2 * math.pi))

            self.channel_freq_err[self.hop_pattern[self.hop_idx]] = self.current_freq_err + freq_error
            self.current_freq_err += freq_error
            logger.info("Frequency error: %d Hz", freq_error)

            msg_data = data[2:]
            msg_id = msg_data[0] & 0xF

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

            msg = self._parse_sensor_data(pkt, msg_id, sensor, msg_data)

            raw_hex = msg_data.hex()
            log_msg = f"Decoded message for station ID {msg.id} (sensor: {msg.sensor.name}):\n"
            log_msg += f"  Raw data:      {raw_hex}\n"
            log_msg += f"  - Header:      {raw_hex[0:2]} (Sensor ID: {sensor_id}, Station ID: {msg.id})\n"
            log_msg += f"  - Wind Speed:    {raw_hex[2:4]} ({msg.wind_speed} mph)\n"
            log_msg += f"  - Wind Dir:      {raw_hex[4:6]} ({msg.wind_direction} deg)\n"

            sensor_data_hex = raw_hex[6:]
            log_msg += f"  - Sensor data ({msg.sensor.name}): {sensor_data_hex}\n"
            if msg.temperature is not None:
                log_msg += f"    - Temperature: {msg.temperature}°F\n"
            if msg.humidity is not None:
                log_msg += f"    - Humidity: {msg.humidity}%\n"
            if msg.rain_rate is not None:
                log_msg += f"    - Rain Rate: {msg.rain_rate} clicks/hr\n"
            if msg.rain_total is not None:
                log_msg += f"    - Rain Total: {msg.rain_total} clicks\n"
            if msg.uv_index is not None:
                log_msg += f"    - UV Index: {msg.uv_index}\n"
            if msg.solar_radiation is not None:
                log_msg += f"    - Solar Radiation: {msg.solar_radiation} W/m^2\n"

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

        if sensor == Sensor.TEMPERATURE:
            # Temperature is a 10-bit value in 1/10ths of a degree F
            temp_raw = (msg_data[3] << 8 | msg_data[4]) & 0x3FF
            temp = temp_raw / 10.0
        elif sensor == Sensor.HUMIDITY:
            # Humidity is a 10-bit value in 1/10ths of a percent
            hum_raw = (msg_data[3] << 8 | msg_data[4]) & 0x3FF
            humidity = hum_raw / 10.0
        elif sensor == Sensor.RAIN_RATE:
            # Rain rate is a 12-bit value, number of clicks per hour
            rain_rate_raw = (msg_data[3] << 8 | msg_data[4]) & 0x0FFF
            rain_rate = float(rain_rate_raw)
        elif sensor == Sensor.RAIN:
            # Rain is a 12-bit value, number of clicks
            rain_total_raw = (msg_data[3] << 8 | msg_data[4]) & 0x0FFF
            rain_total = float(rain_total_raw)
        elif sensor == Sensor.UV_INDEX:
            # UV is an 8-bit value
            uv_index = float(msg_data[3])
        elif sensor == Sensor.SOLAR_RADIATION:
            # Solar radiation is a 10-bit value in W/m^2
            solar_raw = (msg_data[3] << 8 | msg_data[4]) & 0x3FF
            solar_radiation = float(solar_raw)

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
        )
