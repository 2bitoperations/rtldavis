"""
Decoders for common (simple) sensor types.
"""
import math

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
        # From https://github.com/lheijst/weewx-rtldavis/blob/master/bin/user/rtldavis.py#L1049-L1059
        luc_wind_dir = data[2] * 1.40625 + 0.3
        # From https://github.com/dekay/im-me/blob/master/pocketwx/src/protocol.txt
        dekay_wind_dir = data[2] * 360 / 255
        # From https://www.carluccio.de/davis-vue-hacking-part-2/
        dario_wind_dir = 9 + data[2] * 342 / 255

        # From https://www.wxforum.net/index.php?topic=22189.msg247945#msg247945
        raw_direction = (data[2] << 1) | ((data[4] & 2) >> 1)
        kabuki_wind_dir = round(raw_direction * 360 / 512)
        rdsman_wind_dir = round(raw_direction * 0.3515625)

        self.logger.info(
            f"Parsed wind direction: luc={luc_wind_dir:.2f}, kabuki={kabuki_wind_dir}, "
            f"rdsman={rdsman_wind_dir}, dekay={dekay_wind_dir:.2f}, dario={dario_wind_dir:.2f}"
        )

        return kabuki_wind_dir


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
