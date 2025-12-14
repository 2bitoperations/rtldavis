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

        The decoding logic is based on the analysis in this forum post:
        https://www.wxforum.net/index.php?topic=27244.0

        The formula is derived from empirical data:
        UVI = round(((VALUE >> 4) - 4) / 200, 1)
        where VALUE is the 16-bit value from Bytes 3 and 4.
        """
        if data[3] == 0xFF:
            self.logger.info("    - No UV sensor detected")
            return 0.0

        raw_value = (data[3] << 8) + data[4]
        
        # The lower nibble of Byte4 is not used
        value_shifted = raw_value >> 4
        
        # The '0' value is represented by 4
        if value_shifted <= 4:
            return 0.0

        uv_index = round(((value_shifted) - 4) / 200.0, 1)
        
        log_msg = f"    - Raw 16-bit Value: 0x{raw_value:04X}\n"
        log_msg += f"    - Value >> 4: 0x{value_shifted:03X} ({value_shifted})\n"
        log_msg += f"    - Formula: round(((VALUE >> 4) - 4) / 200, 1)\n"
        log_msg += f"    - UV Index: {uv_index:.1f}"
        self.logger.info(log_msg)

        return uv_index
