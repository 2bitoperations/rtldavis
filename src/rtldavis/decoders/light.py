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
        light_raw = (data[3] << 8 | data[4]) & 0x3FF
        light = float(light_raw)
        self.logger.info(f"    - Light: {light}")
        return light
