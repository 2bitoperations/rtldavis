"""
Decoder for Davis UV index data.
"""

import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig


class UVSensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="UV Index",
            id="uv_index",
            device_class="uv_index",
            unit_of_measurement="UV Index",
            state_class="measurement",
            icon="mdi:sun-wireless",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes the UV index from a raw data packet.

        From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
        > Message 4: UV Index
        > Bytes 3 and 4 are for UV Index. The first byte is MSB and the second LSB.
        > A value of FF in the third byte indicates that no sensor is present.
        >
        > UVIndex = ((Byte3 << 8) + Byte4) >> 6) / 50.0
        """
        if data[3] == 0xFF:
            self.logger.info("    - No UV sensor detected")
            return 0.0

        raw_uv = ((data[3] << 8) + data[4]) >> 6
        uv_index = float(raw_uv) / 50.0

        log_msg = f"  - UV Index Data:\n"
        log_msg += f"    - Raw Value (Bytes 3-4 >> 6): 0x{raw_uv:03X} ({raw_uv})\n"
        log_msg += f"    - Formula: {raw_uv} / 50.0\n"
        log_msg += f"    - UV Index: {uv_index:.1f}"
        self.logger.info(log_msg)

        return uv_index
