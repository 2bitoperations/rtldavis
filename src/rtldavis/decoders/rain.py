"""
Decoder for Davis rain total data.
"""

import logging
from typing import Optional
from ..sensor_classes import AbstractSensor, MQTTSensorConfig


class RainTotalSensor(AbstractSensor):
    """
    A stateful decoder for cumulative rain total from a Davis weather station.

    This decoder is necessary because the ISS sends a running total of bucket
    tips that wraps around to 0 after 127 (0x7F). To get a true cumulative
    total, we need to track the previous value and add the difference.

    From https://github.com/dekay/DavisRFM69/wiki/Message-Protocol:
    > Message e:
    > Rain is in Byte 3. It is a running total of bucket tips that wraps
    > back around to 0 eventually from the ISS. It is up to the console
    > to keep track of changes in this byte. Only bits 0 through 6 of
    > byte 3 are used, so the counter will overflow after 0x7F (127).
    """

    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        self.last_clicks: Optional[int] = None
        self.total_clicks: int = 0
        self.rollover_count: int = 0

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Rain Total",
            id="rain_total",
            device_class="precipitation",
            unit_of_measurement="in",
            state_class="total_increasing",
            icon="mdi:weather-pouring",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes the cumulative rain total from a raw data packet.

        Returns the total rainfall in inches.
        """
        current_clicks = data[3] & 0x7F

        self.logger.info(f"    - Raw Click Counter (Byte3 & 0x7F): {current_clicks}")

        if self.last_clicks is None:
            # First reading, initialize the total.
            self.total_clicks = current_clicks
            self.logger.info("    - Initializing rain total.")
        else:
            if current_clicks < self.last_clicks:
                # Rollover detected. The counter has wrapped from 127 to 0.
                self.rollover_count += 1
                # Add the clicks from before the rollover plus the new clicks.
                clicks_since_last = (128 - self.last_clicks) + current_clicks
                self.logger.info(
                    f"    - Rollover detected! (Last: {self.last_clicks}, Current: {current_clicks})"
                )
                self.logger.info(
                    f"    - Clicks since last reading: (128 - {self.last_clicks}) + {current_clicks} = {clicks_since_last}"
                )
            else:
                # Normal increase.
                clicks_since_last = current_clicks - self.last_clicks
                self.logger.info(
                    f"    - Clicks since last reading: {current_clicks} - {self.last_clicks} = {clicks_since_last}"
                )

            if clicks_since_last > 0:
                self.total_clicks += clicks_since_last

        self.last_clicks = current_clicks

        # Each click is 0.01 inches of rain for US models.
        total_inches = self.total_clicks * 0.01

        self.logger.info(f"    - Cumulative Clicks: {self.total_clicks}")
        self.logger.info(f"    - Total Rainfall: {total_inches:.2f} inches")

        return total_inches
