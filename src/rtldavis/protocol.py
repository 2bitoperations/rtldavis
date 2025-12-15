import logging
import math
import random
from enum import Enum
from typing import List, NamedTuple, Dict, Set, Optional, Type
from dataclasses import dataclass, field
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import numpy as np

from . import crc, dsp
from .sensor_classes import AbstractSensor
from .decoders import (
    TemperatureSensor,
    HumiditySensor,
    RainTotalSensor,
    RainRateSensor,
    SupercapSensor,
    UVSensor,
    SolarSensor,
    LightSensor,
    WindSpeedSensor,
    WindDirectionSensor,
    WindGustSensor,
    RSSISensor,
    SNRSensor,
)

logger = logging.getLogger(__name__)


class SensorType(Enum):
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
    sensor_type: Optional[SensorType]
    sensor_values: Dict[str, Any] = field(default_factory=dict)
    raw_sensor_id: Optional[int] = None


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
    
    # Sensor decoders
    sensor_decoders: Dict[SensorType, Type[AbstractSensor]] = field(init=False)
    active_decoders: Dict[Tuple[int, SensorType], AbstractSensor] = field(default_factory=dict)

    def __post_init__(self):
        self.cfg = new_packet_config(self.symbol_length)
        self.demodulator = dsp.Demodulator(self.cfg)
        self.crc = crc.CRC("CCITT-16", 0, 0x1021, 0)
        self.dwell_time = 2.5625
        self.channels = [
            902419338, 902921088, 903422839, 903924589, 904426340, 904928090,
            905429841, 905931591, 906433342, 906935092, 907436843, 907938593,
            908440344, 908942094, 909443845, 909945595, 910447346, 910949096,
            911450847, 911952597, 912454348, 912956099, 913457849, 913959599,
            914461350, 914963100, 915464850, 915966601, 916468351, 916970102,
            917471852, 917973603, 918475353, 918977104, 919478854, 919980605,
            920482355, 920984106, 921485856, 921987607, 922489357, 922991108,
            923492858, 923994609, 924496359, 924998110, 925499860, 926001611,
            926503361, 927005112, 927506862,
        ]
        self.channel_count = len(self.channels)
        self.hop_pattern = [
            0, 19, 41, 25, 8, 47, 32, 13, 36, 22, 3, 29, 44, 16, 5, 27, 38, 10,
            49, 21, 2, 30, 42, 14, 48, 7, 24, 34, 45, 1, 17, 39, 26, 9, 31, 50,
            37, 12, 20, 33, 4, 43, 28, 15, 35, 6, 40, 11, 23, 46, 18,
        ]
        self.hop_idx = random.randint(0, self.channel_count - 1)
        self.factor = (float(self.max_tr_ch_list / 2) + 0.5) * 2.0
        
        self.sensor_decoders = {
            SensorType.TEMPERATURE: TemperatureSensor,
            SensorType.HUMIDITY: HumiditySensor,
            SensorType.RAIN: RainTotalSensor,
            SensorType.RAIN_RATE: RainRateSensor,
            SensorType.SUPER_CAP_VOLTAGE: SupercapSensor,
            SensorType.UV_INDEX: UVSensor,
            SensorType.SOLAR_RADIATION: SolarSensor,
            SensorType.LIGHT: LightSensor,
            SensorType.WIND_GUST_SPEED: WindGustSensor,
        }

    def _get_decoder(self, station_id: int, sensor_type: SensorType) -> AbstractSensor:
        if (station_id, sensor_type) not in self.active_decoders:
            if sensor_type not in self.sensor_decoders:
                raise ValueError(f"No decoder class registered for sensor type {sensor_type.name}")
            decoder_class = self.sensor_decoders[sensor_type]
            self.active_decoders[(station_id, sensor_type)] = decoder_class(logger)
        return self.active_decoders[(station_id, sensor_type)]

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
            new_freq_corr += (error * (i + 1))
            ptr = (ptr + 1) % self.max_tr_ch_list
        
        self.freq_corr = int(float(new_freq_corr) / (self.factor * self.max_tr_ch_list / 2.0))
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

            logger.info(f"CRC check OK. RSSI: {pkt.rssi:.2f} dB, SNR: {pkt.snr:.2f} dB")

            preamble_start = pkt.index
            preamble_end = pkt.index + self.cfg.preamble_length
            preamble_samples = self.demodulator.discriminated[preamble_start:preamble_end]
            
            mean = np.mean(preamble_samples)
            freq_err = -int((mean * float(self.cfg.sample_rate)) / (2 * math.pi))
            logger.info(f"Frequency error: {freq_err} Hz")

            msg_data = data[2:]
            msg_id = msg_data[0] & 0x7
            
            tr = msg_id
            ch = self.hop_pattern[self.hop_idx]
            ptr = self.freq_err_tr_ch_ptr[tr][ch]
            self.freq_err_tr_ch_list[tr][ch][ptr] = freq_err
            self.freq_err_tr_ch_ptr[tr][ch] = (ptr + 1) % self.max_tr_ch_list
            self.transmitter = tr

            if self.station_id is not None and msg_id != self.station_id:
                logger.info(f"Ignoring message for station ID {msg_id}, Raw data: {msg_data.hex()}")
                continue

            msg = self._parse_sensor_data(pkt, msg_id, msg_data)
            if msg:
                msgs.append(msg)
        return msgs

    def _parse_sensor_data(self, pkt: dsp.Packet, msg_id: int, msg_data: bytes) -> Optional[Message]:
        sensor_id = msg_data[0] >> 4
        try:
            sensor_type = SensorType(sensor_id)
        except ValueError:
            logger.warning(f"Unknown sensor type: 0x{sensor_id:02X}. Raw data: {msg_data.hex()}")
            return None

        logger.info(f"Processing message for station ID {msg_id}, sensor type {sensor_type.name} ({sensor_id}), hex data: {msg_data.hex()}")

        sensor_values = {}
        
        # Common values
        sensor_values['wind_speed'] = WindSpeedSensor(logger).decode(msg_data)
        sensor_values['wind_direction'] = WindDirectionSensor(logger).decode(msg_data)
        sensor_values['rssi'] = RSSISensor(logger).decode(pkt.rssi)
        sensor_values['snr'] = SNRSensor(logger).decode(pkt.snr)

        if sensor_type in self.sensor_decoders:
            decoder = self._get_decoder(msg_id, sensor_type)
            value = decoder.decode(msg_data)
            sensor_values[decoder.config.id] = value
        else:
            logger.warning(f"No decoder registered for sensor type {sensor_type.name}")

        return Message(
            packet=pkt,
            id=msg_id,
            sensor_type=sensor_type,
            sensor_values=sensor_values,
            raw_sensor_id=sensor_id,
        )
