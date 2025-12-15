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

        The decoding logic is based on the Davis RFM69 message protocol documentation:
        https://github.com/dekay/DavisRFM69/wiki/Message-Protocol

        The rain rate is calculated from the time between bucket tips.
        A bucket tip corresponds to 0.01" of rain for US models.

        The raw packet contains a 10-bit value representing a base time interval.
        - Byte3 contains the lower 8 bits.
        - Bits 4 and 5 of Byte4 contain the upper 2 bits.

        The packet also indicates "light" or "strong" rain, which determines how
        the base time interval is interpreted.
        - Light rain: time_between_clicks = base_time
        - Strong rain: time_between_clicks = base_time / 16

        The rain rate in inches per hour is then calculated as:
        inches_per_hour = (3600 seconds/hour) / time_between_clicks_s * (0.01 inches/click)
                        = 36 / time_between_clicks_s
        """
        # Byte 3 is the low 8 bits of the time value.
        # Byte 4 bits 4 & 5 are the high 2 bits.
        # raw_val is a 10-bit number representing the base time interval.
        raw_val = (((data[4] & 0x30) >> 4) * 256) + data[3]

        self.logger.info(f"    - Raw time value: {raw_val}")

        if data[3] == 0xFF:
            self.logger.info("    - No rain detected (Byte3 == 0xFF)")
            return 0.0

        if raw_val == 0:
            self.logger.info("    - No rain detected (raw time value is 0)")
            return 0.0

        # Bit 6 of Byte4 indicates light or strong rain.
        is_strong_rain = (data[4] & 0x40) != 0
        rain_type = "Strong" if is_strong_rain else "Light"
        self.logger.info(f"    - Rain Type: {rain_type}")

        if is_strong_rain:
            # For strong rain, the time between clicks is divided by 16.
            time_between_clicks = float(raw_val) / 16.0
        else:
            # For light rain, the time is the raw value.
            time_between_clicks = float(raw_val)

        self.logger.info(f"    - Time between clicks: {time_between_clicks:.4f} s")

        # inches_per_hour = 36 / time_between_clicks
        inches_per_hour = 36.0 / time_between_clicks

        self.logger.info(f"    - Rain Rate: {inches_per_hour:.3f} in/hr")

        return inches_per_hour
