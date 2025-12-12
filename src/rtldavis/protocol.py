import logging
import math
import random
from enum import Enum
from typing import List, NamedTuple, Dict, Set, Optional
from dataclasses import dataclass, field
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

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
    freq_corr: int
    transmitter: int


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


@dataclass
class Parser:
    symbol_length: int
    station_id: Optional[int] = None
    cfg: dsp.PacketConfig = field(init=False)
    demodulator: dsp.Demodulator = field(init=False)
    crc: crc.CRC = field(init=False)
    dwell_time: float = field(init=False)
    channels: List[int] = field(init=False)
    channel_count: int = field(init=False)
    hop_pattern: List[int] = field(init=False)
    hop_idx: int = 0
    transmitter: int = 0
    freq_corr: int = 0
    max_tr_ch_list: int = 10
    factor: float = 0.0
    freq_err_tr_ch_list: Dict[int, Dict[int, List[int]]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(lambda: [0] * 10)))
    freq_err_tr_ch_ptr: Dict[int, Dict[int, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))

    def __post_init__(self):
        self.cfg = new_packet_config(self.symbol_length)
        self.demodulator = dsp.Demodulator(self.cfg)
        self.crc = crc.CRC("CCITT-16", 0, 0x1021, 0)
        self.dwell_time = 2.5625 + (self.station_id or 0) * 0.0625
        self.channels = [
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
        self.channel_count = len(self.channels)
        self.hop_pattern = [
            0, 19, 41, 25, 8, 47, 32, 13, 36, 22, 3, 29, 44, 16, 5, 27, 38, 10,
            49, 21, 2, 30, 42, 14, 48, 7, 24, 34, 45, 1, 17, 39, 26, 9, 31, 50,
            37, 12, 20, 33, 4, 43, 28, 15, 35, 6, 40, 11, 23, 46, 18,
        ]
        self.hop_idx = random.randint(0, self.channel_count - 1)
        self.factor = (float(self.max_tr_ch_list / 2) + 0.5) * 2.0

    def _hop(self) -> Hop:
        channel_idx = self.hop_pattern[self.hop_idx]
        channel_freq = self.channels[channel_idx]
        return Hop(channel_idx, channel_freq, self.freq_corr, self.transmitter)

    def set_hop(self, n: int, tr: int) -> Hop:
        self.hop_idx = n % self.channel_count
        self.transmitter = tr
        ch = self.hop_pattern[self.hop_idx]
        ptr = self.freq_err_tr_ch_ptr[tr][ch]

        new_freq_corr = 0
        for i in range(self.max_tr_ch_list):
            error = self.freq_err_tr_ch_list[tr][ch][ptr]
            new_freq_corr += (error * (i + 1) / self.max_tr_ch_list)
            ptr = (ptr + 1) % self.max_tr_ch_list
        
        self.freq_corr = int(float(new_freq_corr) / self.factor)
        return self._hop()

    def next_hop(self) -> Hop:
        self.hop_idx = (self.hop_idx + 1) % self.channel_count
        return self.set_hop(self.hop_idx, self.transmitter)

    def rand_hop(self) -> Hop:
        self.hop_idx = random.randint(0, self.channel_count - 1)
        return self.set_hop(self.hop_idx, self.transmitter)

    def parse(self, pkts: List[dsp.Packet]) -> List[Message]:
        seen: Set[bytes] = set()
        msgs: List[Message] = []
        for pkt in pkts:
            data = bytes(swap_bit_order(b) for b in pkt.data)

            if data in seen:
                continue
            seen.add(data)

            if self.crc.checksum(data[2:]) != 0:
                logger.debug("CRC check failed")
                continue

            logger.info("CRC check OK. RSSI: %.2f dB, SNR: %.2f dB", pkt.rssi, pkt.snr)

            preamble_start = pkt.index
            preamble_end = pkt.index + self.cfg.preamble_length
            preamble_samples = self.demodulator.discriminated[preamble_start:preamble_end]
            
            mean = np.mean(preamble_samples)
            freq_err = -int((mean * float(self.cfg.sample_rate)) / (2 * math.pi))
            logger.info("Frequency error: %d Hz", freq_err)

            msg_data = data[2:]
            msg_id = msg_data[0] & 0x7
            
            tr = msg_id
            ch = self.hop_pattern[self.hop_idx]
            ptr = self.freq_err_tr_ch_ptr[tr][ch]
            self.freq_err_tr_ch_list[tr][ch][ptr] = freq_err
            self.freq_err_tr_ch_ptr[tr][ch] = (ptr + 1) % self.max_tr_ch_list
            self.transmitter = tr

            if self.station_id is not None and msg_id != self.id:
                logger.info("Ignoring message for station ID %d", msg_id)
                continue

            sensor_id = msg_data[0] >> 4
            try:
                sensor = Sensor(sensor_id)
            except ValueError:
                logger.warning("Unknown sensor type: 0x%02X", sensor_id)
                continue

            if sensor not in [Sensor.TEMPERATURE, Sensor.WIND_GUST_SPEED]:
                try:
                    with open("sensor.log", "a") as f:
                        ts = time.time()
                        ct = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=-5)))
                        f.write(f"{ts} {ct.isoformat()} {msg_data.hex()}\n")
                except Exception as e:
                    logger.error(f"Failed to write to sensor.log: {e}")

            msg = self._parse_sensor_data(pkt, msg_id, sensor, msg_data)
            msgs.append(msg)
        return msgs

    def _parse_sensor_data(self, pkt: dsp.Packet, msg_id: int, sensor: Sensor, msg_data: bytes) -> Message:
        temp, humidity, rain_rate, rain_total, solar_radiation, uv_index, wind_gust_speed, super_cap_voltage, light = (None,) * 9
        
        raw_hex = msg_data.hex()
        log_msg = f"Decoded message for station ID {msg_id} (sensor: {sensor.name}):\n"
        log_msg += f"  Raw data:      {raw_hex}\n"
        log_msg += f"  - Header:      {raw_hex[0:2]} (Sensor ID: {sensor.value}, Station ID: {msg_id})\n"
        log_msg += f"  - Wind Speed:    {raw_hex[2:4]} ({msg_data[1]} mph)\n"
        log_msg += f"  - Wind Dir:      {raw_hex[4:6]} ({msg_data[2]} deg)\n"
        log_msg += f"  - Sensor data ({sensor.name}): {raw_hex[6:]}\n"
        
        logger.info(log_msg)

        try:
            if sensor == Sensor.TEMPERATURE:
                temp = decode_temperature(msg_data, logger)
            elif sensor == Sensor.HUMIDITY:
                humidity = decode_humidity(msg_data, logger)
            elif sensor == Sensor.RAIN_RATE:
                rain_rate = decode_rain_rate(msg_data, logger)
            elif sensor == Sensor.RAIN:
                rain_total = decode_rain_total(msg_data, logger)
            elif sensor == Sensor.UV_INDEX:
                uv_index = decode_uv(msg_data, logger)
            elif sensor == Sensor.SOLAR_RADIATION:
                solar_radiation = decode_solar(msg_data, logger)
            elif sensor == Sensor.WIND_GUST_SPEED:
                wind_gust_speed = msg_data[3]
                logger.info(f"    - Wind Gust: {wind_gust_speed} mph")
            elif sensor == Sensor.SUPER_CAP_VOLTAGE:
                super_cap_voltage = decode_supercap(msg_data, logger)
            elif sensor == Sensor.LIGHT:
                light_raw = (msg_data[3] << 8 | msg_data[4]) & 0x3FF
                light = float(light_raw)
                logger.info(f"    - Light: {light}")
        except Exception as e:
            logger.error(f"Failed to decode sensor {sensor.name}: {e}")

        return Message(
            packet=pkt, id=msg_id, sensor=sensor,
            wind_speed=msg_data[1], wind_direction=msg_data[2],
            temperature=temp, humidity=humidity, rain_rate=rain_rate,
            rain_total=rain_total, solar_radiation=solar_radiation,
            uv_index=uv_index, wind_gust_speed=wind_gust_speed,
            super_cap_voltage=super_cap_voltage, light=light,
            rssi=pkt.rssi, snr=pkt.snr,
        )
