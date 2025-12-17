"""
Decoder for Davis rain total data.
"""
import logging
from typing import Optional, Deque
from collections import deque
import time
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class RainTotalSensor(AbstractSensor):
    """
    A stateful decoder for cumulative rain total from a Davis weather station.
    """
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)
        self.last_clicks: Optional[int] = None
        self.total_clicks_raw: int = 0
        self.rollover_count: int = 0
        self.clicks_history: Deque[float] = deque()

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Rain Total Raw",
            id="rain_total_raw",
            device_class="precipitation",
            unit_of_measurement="in",
            state_class="total_increasing",
            icon="mdi:weather-pouring",
        )

    def decode(self, data: bytes) -> dict:
        """
        Decodes the cumulative rain total from a raw data packet.
        """
        current_clicks = data[3] & 0x7F
        
        self.logger.info(f"  - Rain Data (Byte 3):\n    - Raw Click Counter: {current_clicks}")

        if self.last_clicks is not None and current_clicks < self.last_clicks:
            self.rollover_count += 1
            clicks_since_last = (128 - self.last_clicks) + current_clicks
            self.logger.warning(
                f"    - Rollover detected! (Last: {self.last_clicks}, Current: {current_clicks}). "
                f"Clicks since last: {clicks_since_last}. Total rollovers: {self.rollover_count}"
            )
            # Per user request, do not add this anomalous value to the total, just log it
            self.logger.info(f"    - Raw message type 3 value: {data[3]}")
        elif self.last_clicks is not None:
            clicks_since_last = current_clicks - self.last_clicks
            if clicks_since_last > 0:
                self.total_clicks_raw += clicks_since_last
                now = time.time()
                for _ in range(clicks_since_last):
                    self.clicks_history.append(now)
        
        self.last_clicks = current_clicks
        
        total_inches = self.total_clicks_raw * 0.01

        self.logger.info(f"    - Cumulative Clicks (Raw): {self.total_clicks_raw}")
        self.logger.info(f"    - Total Rainfall (Raw): {total_inches:.2f} inches")

        now = time.time()
        one_hour_ago = now - 3600
        one_day_ago = now - 86400
        one_week_ago = now - 604800

        while self.clicks_history and self.clicks_history[0] < one_week_ago:
            self.clicks_history.popleft()
        
        hourly_clicks = sum(1 for t in self.clicks_history if t > one_hour_ago)
        daily_clicks = sum(1 for t in self.clicks_history if t > one_day_ago)
        weekly_clicks = len(self.clicks_history)

        return {
            "rain_total_raw": total_inches,
            "rain_total_hourly": hourly_clicks * 0.01,
            "rain_total_daily": daily_clicks * 0.01,
            "rain_total_weekly": weekly_clicks * 0.01,
        }
