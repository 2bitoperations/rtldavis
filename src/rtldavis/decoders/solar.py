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
        """
        if data[3] == 0xFF:
            self.logger.info("    - No solar sensor detected")
            return 0.0

        raw_value = (data[3] << 8) + data[4]
        
        value_shifted = raw_value >> 4
        
        if value_shifted <= 4:
            return 0.0

        solar_rad = round(((value_shifted) - 4) / 2.27)
        
        self.logger.info(
            f"  - Solar Radiation Data (Bytes 3-4):\n"
            f"    - Raw 16-bit Value: 0x{raw_value:04X}\n"
            f"    - Value >> 4: 0x{value_shifted:03X} ({value_shifted})\n"
            f"    - Formula: round(((VALUE >> 4) - 4) / 2.27)\n"
            f"    - Solar Radiation: {solar_rad:.1f} W/m^2"
        )

        return float(solar_rad)
