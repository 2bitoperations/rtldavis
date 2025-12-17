"""
Decoder for Davis humidity data.
"""
import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class HumiditySensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Humidity",
            id="humidity",
            device_class="humidity",
            unit_of_measurement="%",
            state_class="measurement",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes humidity from a raw data packet.

        From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
        > humidity = (((Byte4 >> 4) << 8) + Byte3) / 10.0
        """
        raw_humidity = ((data[4] >> 4) << 8) + data[3]
        humidity = float(raw_humidity) / 10.0
        
        self.logger.info(
            f"  - Humidity Data (Bytes 3-4):\n"
            f"    - Raw Value: 0x{raw_humidity:03X} ({raw_humidity})\n"
            f"    - Formula: ((((Byte4 >> 4) << 8) + Byte3) / 10.0)\n"
            f"    - Humidity: {humidity:.1f}%"
        )

        return humidity
