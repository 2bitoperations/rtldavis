"""
Decoder for Davis rain rate data.
"""
import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class RainRateSensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Rain Rate",
            id="rain_rate",
            device_class="precipitation_intensity",
            unit_of_measurement="in/h",
            state_class="measurement",
            icon="mdi:weather-rainy",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes rain rate from a raw data packet.
        """
        raw_val = (((data[4] & 0x30) >> 4) * 256) + data[3]
        
        self.logger.info(f"  - Rain Rate Data (Bytes 3-4):\n    - Raw time value: {raw_val}")

        if data[3] == 0xFF:
            self.logger.info("    - No rain detected (Byte3 == 0xFF)")
            return 0.0

        if raw_val == 0:
            self.logger.info("    - No rain detected (raw time value is 0)")
            return 0.0

        is_strong_rain = (data[4] & 0x40) != 0
        rain_type = "Strong" if is_strong_rain else "Light"
        self.logger.info(f"    - Rain Type: {rain_type}")

        if is_strong_rain:
            time_between_clicks = float(raw_val) / 16.0
        else:
            time_between_clicks = float(raw_val)

        self.logger.info(f"    - Time between clicks: {time_between_clicks:.4f} s")

        inches_per_hour = 36.0 / time_between_clicks

        self.logger.info(f"    - Rain Rate: {inches_per_hour:.3f} in/hr")

        return inches_per_hour
