"""
Decoder for Davis temperature data.
"""
import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class TemperatureSensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Temperature",
            id="temperature",
            device_class="temperature",
            unit_of_measurement="°F",
            state_class="measurement",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes temperature from a raw data packet.

        From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
        > tempF = ((Byte3 * 256 + Byte4) / 160
        """
        raw_temp = (data[3] << 8) | data[4]
        temp_f = float(raw_temp) / 160.0
        
        self.logger.info(f"    - Raw Value: 0x{raw_temp:04X} ({raw_temp})")
        self.logger.info(f"    - Formula: {raw_temp} / 160.0")
        self.logger.info(f"    - Temperature: {temp_f:.1f}°F")

        return temp_f
