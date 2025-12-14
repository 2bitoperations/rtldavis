"""
Decoders for common (simple) sensor types.
"""
import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class WindSpeedSensor(AbstractSensor):
    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Wind Speed",
            id="wind_speed",
            device_class="wind_speed",
            unit_of_measurement="mph",
            state_class="measurement",
        )

    def decode(self, data: bytes) -> int:
        val = data[1]
        self.logger.info(f"    - Wind Speed: {val} mph")
        return val

class WindDirectionSensor(AbstractSensor):
    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Wind Direction",
            id="wind_direction",
            unit_of_measurement="°",
            icon="mdi:compass-rose",
        )

    def decode(self, data: bytes) -> int:
        val = data[2]
        self.logger.info(f"    - Wind Direction: {val}°")
        return val

class WindGustSensor(AbstractSensor):
    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Wind Gust",
            id="wind_gust_speed",
            device_class="wind_speed",
            unit_of_measurement="mph",
            state_class="measurement",
        )

    def decode(self, data: bytes) -> int:
        val = data[3]
        self.logger.info(f"    - Wind Gust: {val} mph")
        return val

class RSSISensor(AbstractSensor):
    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="RSSI",
            id="rssi",
            device_class="signal_strength",
            unit_of_measurement="dB",
            state_class="measurement",
        )

    def decode(self, data: float) -> float:
        return data

class SNRSensor(AbstractSensor):
    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="SNR",
            id="snr",
            device_class="signal_strength",
            unit_of_measurement="dB",
            state_class="measurement",
        )

    def decode(self, data: float) -> float:
        return data
