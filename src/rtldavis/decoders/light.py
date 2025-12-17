"""
Decoder for Davis light data.
"""
import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class LightSensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Light",
            id="light",
            device_class="illuminance",
            unit_of_measurement="lx",
            state_class="measurement",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes light from a raw data packet.
        """
        raw_light = (data[3] << 2) + ((data[4] & 0xC0) >> 6)
        light = float(raw_light)
        
        self.logger.info(
            f"  - Light Data (Bytes 3-4):\n"
            f"    - Raw Value: 0x{raw_light:03X} ({raw_light})\n"
            f"    - Formula: (Byte3 * 4) + ((Byte4 & 0xC0) / 64)\n"
            f"    - Light: {light}"
        )

        return light
