import logging
import json
import time
import asyncio
from paho.mqtt import client as mqtt_client
from typing import Any, Dict, Optional, Set, Tuple

from .version import __version__

logger = logging.getLogger(__name__)

# Based on Home Assistant MQTT sensor documentation
# https://www.home-assistant.io/integrations/sensor.mqtt/
SENSOR_DESCRIPTIONS = {
    "temperature": {
        "device_class": "temperature",
        "unit_of_measurement": "°F",
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
        "unit_of_measurement": "in/hr",
        "state_class": "measurement",
        "icon": "mdi:weather-rainy",
    },
    "rain_total": {
        "device_class": "precipitation",
        "unit_of_measurement": "in",
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
    "wind_gust_speed": {
        "device_class": "wind_speed",
        "unit_of_measurement": "mph",
        "state_class": "measurement",
    },
    "super_cap_voltage": {
        "device_class": "voltage",
        "unit_of_measurement": "V",
        "state_class": "measurement",
    },
    "light": {
        "device_class": "illuminance",
        "unit_of_measurement": "lx",
        "state_class": "measurement",
    },
    "rssi": {
        "device_class": "signal_strength",
        "unit_of_measurement": "dB",
        "state_class": "measurement",
    },
    "snr": {
        "device_class": "signal_strength",
        "unit_of_measurement": "dB",
        "state_class": "measurement",
    },
    "seconds_since_last_data": {
        "device_class": "duration",
        "unit_of_measurement": "s",
        "state_class": "measurement",
        "icon": "mdi:timer-sand",
    },
}


class MQTTPublisher:
    def __init__(self, broker: str, port: int, discovery_prefix: str, state_prefix: str, client_id: str,
                 username: Optional[str] = None, password: Optional[str] = None) -> None:
        self.broker: str = broker
        self.port: int = port
        self.discovery_prefix: str = discovery_prefix
        self.state_prefix: str = state_prefix
        self.client_id: str = client_id
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.client: mqtt_client.Client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION1, client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._configured_sensors: Set[Tuple[int, str]] = set()
        self._availability_topics: Dict[int, str] = {}
        self._last_data_time: Optional[float] = None
        self._timer_task: Optional[asyncio.Task] = None

    def connect(self) -> None:
        try:
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            
            # Set Last Will and Testament for all potential station IDs
            for i in range(8):
                availability_topic = f"{self.state_prefix}/{i}/status"
                self.client.will_set(availability_topic, payload="offline", retain=True)

            self.client.connect(self.broker, self.port)
            self.client.loop_start()
        except Exception as e:
            logger.error("Failed to connect to MQTT broker: %s", e)
            raise

    def disconnect(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
        for topic in self._availability_topics.values():
            self.client.publish(topic, payload="offline", retain=True)
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

        config_topic = f"{self.discovery_prefix}/sensor/{unique_id}/config"
        state_topic = f"{self.state_prefix}/{station_id}/state"
        availability_topic = f"{self.state_prefix}/{station_id}/status"
        self._availability_topics[station_id] = availability_topic

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
                "sw_version": __version__,
            },
            "availability_topic": availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            **description,
        }

        logger.info("Publishing config for %s to %s", sensor_name, config_topic)
        self.client.publish(config_topic, json.dumps(payload), retain=True)
        self.client.publish(availability_topic, payload="online", retain=True)

    async def _timer_loop(self, station_id: int):
        """Periodically publishes the time since the last data packet."""
        while True:
            await asyncio.sleep(1)
            if self._last_data_time:
                seconds_since = int(time.time() - self._last_data_time)
                state_topic = f"{self.state_prefix}/{station_id}/state"
                payload = json.dumps({"seconds_since_last_data": seconds_since})
                self.client.publish(state_topic, payload, retain=False)

    def publish(self, message: Dict[str, Any]) -> None:
        station_id = message.get("id")
        if station_id is None:
            logger.warning("Message is missing station ID, cannot publish.")
            return

        self._last_data_time = time.time()
        if self._timer_task is None:
            self._timer_task = asyncio.create_task(self._timer_loop(station_id))

        if 'sensor' in message and message['sensor'] is not None:
            message['sensor'] = message['sensor'].name
        else:
            if 'sensor' in message:
                del message['sensor']

        for sensor_name, value in message.items():
            if value is not None and sensor_name in SENSOR_DESCRIPTIONS:
                if (station_id, sensor_name) not in self._configured_sensors:
                    self._publish_config(station_id, sensor_name, SENSOR_DESCRIPTIONS[sensor_name])
                    self._configured_sensors.add((station_id, sensor_name))

        state_topic = f"{self.state_prefix}/{station_id}/state"
        payload = json.dumps({k: v for k, v in message.items() if v is not None})
        
        logger.info("Publishing message to topic '%s': %s", state_topic, payload)
        result = self.client.publish(state_topic, payload, retain=False)

        status = result[0]
        if status == 0:
            logger.debug("Successfully published message to topic '%s'", state_topic)
        else:
            logger.warning("Failed to send message to topic '%s', status: %d", status, state_topic)
