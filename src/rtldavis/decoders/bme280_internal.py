import logging
from typing import Any, List

from rtldavis.sensor_classes import AbstractSensor, MQTTSensorConfig

class BME280InternalSensor(AbstractSensor):
    """
    Dummy decoder for the local internal BME280.
    It doesn't actually 'decode' raw radio packets, but registering it here
    allows its metadata to automatically populate the SensorStore so it can be 
    published to MQTT and exposed on the REST API transparently.
    """

    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            id="indoor_temperature",
            name="Indoor Temperature",
            device_class="temperature",
            unit_of_measurement="°C",
            state_class="measurement",
        )

    @property
    def all_configs(self) -> List[MQTTSensorConfig]:
        return [
            MQTTSensorConfig(
                id="indoor_temperature",
                name="Indoor Temperature",
                device_class="temperature",
                unit_of_measurement="°C",
                state_class="measurement",
            ),
            MQTTSensorConfig(
                id="indoor_humidity",
                name="Indoor Humidity",
                device_class="humidity",
                unit_of_measurement="%",
                state_class="measurement",
            ),
            MQTTSensorConfig(
                id="barometric_pressure",
                name="Barometric Pressure",
                device_class="pressure",
                unit_of_measurement="hPa",
                state_class="measurement",
            ),
        ]

    def decode(self, data: Any) -> Any:
        # BME280 data is passed in already parsed by the bme280 library.
        # This is essentially a no-op / pass-through for architectural compliance.
        return data
