import logging
import json
from paho.mqtt import client as mqtt_client
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Based on Home Assistant MQTT sensor documentation
# https://www.home-assistant.io/integrations/sensor.mqtt/
SENSOR_DESCRIPTIONS = {
    "temperature": {
        "device_class": "temperature",
        "unit_of_measurement": "°F",  # Assuming Davis default, can be configured
        "state_class": "measurement",
    },
    "humidity": {
        "device_class": "humidity",
        "unit_of_measurement": "%",
        "state_class": "measurement",
    },
    "wind_speed": {
        "device_class": "wind_speed",
        "unit_of_measurement": "mph",
        "state_class": "measurement",
    },
    "wind_direction": {
        "unit_of_measurement": "°",
        "icon": "mdi:compass-rose",
    },
    "rain_rate": {
        "device_class": "precipitation_intensity",
        "unit_of_measurement": "in/hr", # The raw data is in clicks/hr and needs conversion
        "state_class": "measurement",
        "icon": "mdi:weather-rainy",
    },
    "rain_total": {
        "device_class": "precipitation",
        "unit_of_measurement": "in", # The raw data is in clicks and needs conversion
        "state_class": "total_increasing",
        "icon": "mdi:weather-pouring",
    },
    "solar_radiation": {
        "device_class": "irradiance",
        "unit_of_measurement": "W/m²",
        "state_class": "measurement",
        "icon": "mdi:weather-sunny",
    },
    "uv_index": {
        "device_class": "uv_index",
        "unit_of_measurement": "UV Index",
        "state_class": "measurement",
        "icon": "mdi:sun-wireless",
    },
}


class MQTTPublisher:
    def __init__(self, broker: str, port: int, topic: str, client_id: str,
                 username: Optional[str] = None, password: Optional[str] = None) -> None:
        self.broker: str = broker
        self.port: int = port
        self.base_topic: str = topic  # Should be "homeassistant" for discovery
        self.client_id: str = client_id
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.client: mqtt_client.Client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION1, client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._configured_sensors: Set[Tuple[int, str]] = set()

    def connect(self) -> None:
        try:
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            self.client.connect(self.broker, self.port)
            self.client.loop_start()
        except Exception as e:
            logger.error("Failed to connect to MQTT broker: %s", e)
            raise

    def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client: mqtt_client.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        if rc == 0:
            logger.info("Successfully connected to MQTT Broker at %s:%d with client ID '%s'",
                       self.broker, self.port, self.client_id)
        else:
            logger.error("Failed to connect to MQTT Broker at %s:%d, return code: %d",
                        self.broker, self.port, rc)

    def _on_disconnect(self, client: mqtt_client.Client, userdata: Any, rc: int) -> None:
        logger.info("Disconnected from MQTT Broker.")

    def _publish_config(self, station_id: int, sensor_name: str, description: Dict[str, Any]) -> None:
        device_id = f"rtldavis_{station_id}"
        unique_id = f"{device_id}_{sensor_name}"

        config_topic = f"{self.base_topic}/sensor/{unique_id}/config"
        state_topic = f"rtldavis/{station_id}/state"

        payload = {
            "name": f"Davis {sensor_name.replace('_', ' ').title()}",
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.{sensor_name} }}}}",
            "device": {
                "identifiers": [device_id],
                "name": f"Davis Weather Station {station_id}",
                "model": "RTL-SDR Davis Station",
                "manufacturer": "rtldavis",
            },
            **description,
        }

        # Use the state topic to determine availability
        payload["availability_topic"] = state_topic
        # Publish all other values as attributes
        payload["json_attributes_topic"] = state_topic

        logger.info("Publishing config for %s to %s", sensor_name, config_topic)
        self.client.publish(config_topic, json.dumps(payload), retain=True)

    def publish(self, message: Dict[str, Any]) -> None:
        station_id = message.get("id")
        if station_id is None:
            logger.warning("Message is missing station ID, cannot publish.")
            return

        # The original message has an enum for sensor, convert to string for JSON
        if 'sensor' in message and not isinstance(message['sensor'], str):
            message['sensor'] = message['sensor'].name

        # Publish discovery messages for all sensors in the payload with a value
        for sensor_name, value in message.items():
            if value is not None and sensor_name in SENSOR_DESCRIPTIONS:
                if (station_id, sensor_name) not in self._configured_sensors:
                    self._publish_config(station_id, sensor_name, SENSOR_DESCRIPTIONS[sensor_name])
                    self._configured_sensors.add((station_id, sensor_name))

        # Publish state
        state_topic = f"rtldavis/{station_id}/state"

        # Filter out None values from payload
        payload = json.dumps({k: v for k, v in message.items() if v is not None})
        logger.info("Publishing message to topic '%s': %s", state_topic, payload)
        result = self.client.publish(state_topic, payload)

        status = result[0]
        if status == 0:
            logger.debug("Successfully published message to topic '%s'", state_topic)
        else:
            logger.warning("Failed to send message to topic '%s', status: %d", status, state_topic)
