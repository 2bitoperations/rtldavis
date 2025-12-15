"""
Decoder for Davis solar radiation data.
"""

import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig


class SolarSensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Solar Radiation",
            id="solar_radiation",
            device_class="irradiance",
            unit_of_measurement="W/m²",
            state_class="measurement",
            icon="mdi:weather-sunny",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes solar radiation from a raw data packet.

        The decoding logic is based on the analysis in this forum post:
        https://www.wxforum.net/index.php?topic=27244.0

        The formula is derived from empirical data and is more accurate than
        the simple multiplication factor used in some other implementations.

        w/m^2 = round(((VALUE >> 4) - 4) / 2.27)
        where VALUE is the 16-bit value from Bytes 3 and 4.
        """
        if data[3] == 0xFF:
            self.logger.info("    - No solar sensor detected")
            return 0.0

        raw_value = (data[3] << 8) + data[4]

        # The lower nibble of Byte4 is not used
        value_shifted = raw_value >> 4

        # The '0' value is represented by 4
        if value_shifted <= 4:
            return 0.0

        solar_rad = round(((value_shifted) - 4) / 2.27)

        self.logger.info(f"    - Raw 16-bit Value: 0x{raw_value:04X}")
        self.logger.info(f"    - Value >> 4: 0x{value_shifted:03X} ({value_shifted})")
        self.logger.info("    - Formula: round(((VALUE >> 4) - 4) / 2.27)")
        self.logger.info(f"    - Solar Radiation: {solar_rad:.1f} W/m^2")

        return float(solar_rad)
