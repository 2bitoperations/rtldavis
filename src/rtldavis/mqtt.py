import logging
import json
import math
import time
import asyncio
from paho.mqtt import client as mqtt_client
from typing import Any, Dict, List, Optional, Set

from .version import __version__
from .protocol import Message
from .sensor_classes import AbstractSensor, MQTTSensorConfig
from . import decoders

logger = logging.getLogger(__name__)

# Sensor ids that must never be averaged: a gust is a peak (take the max in-window),
# and rain totals / seconds-since-last-data are already-accumulated or point-in-time
# values (take the latest sample, not a mean of a monotonic/instantaneous quantity).
_MAX_KEYS = {"wind_gust_speed"}
_LAST_VALUE_KEYS = {
    "rain_total_raw",
    "rain_total_hourly",
    "rain_total_daily",
    "rain_total_weekly",
    "seconds_since_last_data",
}
# Wind direction wraps at 0/360 — a naive mean of e.g. 350 and 10 gives 180 (due
# south) instead of 0 (due north), so it needs a circular mean instead.
_CIRCULAR_KEYS = {"wind_direction"}


def _circular_mean_deg(values: List[float]) -> int:
    sin_sum = sum(math.sin(math.radians(v)) for v in values)
    cos_sum = sum(math.cos(math.radians(v)) for v in values)
    return round(math.degrees(math.atan2(sin_sum, cos_sum))) % 360


def _aggregate(sensor_id: str, values: List[Any]) -> Any:
    """Collapse the samples buffered for one sensor since the last flush."""
    if sensor_id in _LAST_VALUE_KEYS:
        return values[-1]
    if sensor_id in _MAX_KEYS:
        return max(values)
    if sensor_id in _CIRCULAR_KEYS:
        return _circular_mean_deg(values)
    return round(sum(values) / len(values), 2)


class MQTTPublisher:
    def __init__(
        self,
        broker: str,
        port: int,
        discovery_prefix: str,
        state_prefix: str,
        client_id: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        push_interval: int = 30,
    ) -> None:
        self.broker: str = broker
        self.port: int = port
        self.discovery_prefix: str = discovery_prefix
        self.state_prefix: str = state_prefix
        self.client_id: str = client_id
        self.username: Optional[str] = username
        self.password: Optional[str] = password
        self.push_interval: int = push_interval
        self.client: mqtt_client.Client = mqtt_client.Client(
            mqtt_client.CallbackAPIVersion.VERSION1, client_id
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._configured_stations: Set[int] = set()
        self._availability_topics: Dict[int, str] = {}
        self._last_data_time: Optional[float] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._flush_task: Optional[asyncio.Task] = None
        # station_id -> sensor_id -> samples accumulated since the last flush
        self._pending: Dict[int, Dict[str, List[Any]]] = {}

        self.sensor_configs: Dict[str, MQTTSensorConfig] = {}

        logger.debug("Discovering available sensors...")
        for name, decoder_class in decoders.__dict__.items():
            if (
                isinstance(decoder_class, type)
                and issubclass(decoder_class, AbstractSensor)
                and decoder_class is not AbstractSensor
            ):
                try:
                    instance = decoder_class(logging.getLogger())
                    self.sensor_configs[instance.config.id] = instance.config
                    logger.debug(
                        f"Discovered sensor: {instance.config.name} ({instance.config.id})"
                    )
                except Exception as e:
                    logger.error(f"Failed to instantiate sensor decoder {name}: {e}")

        self.sensor_configs["seconds_since_last_data"] = MQTTSensorConfig(
            name="Seconds Since Last Data",
            id="seconds_since_last_data",
            device_class="duration",
            unit_of_measurement="s",
            state_class="measurement",
            icon="mdi:timer-sand",
            diagnostic=True,
        )
        self.sensor_configs["rain_total_hourly"] = MQTTSensorConfig(
            name="Rain Total Hourly",
            id="rain_total_hourly",
            device_class="precipitation",
            unit_of_measurement="in",
            state_class="total",
            icon="mdi:weather-pouring",
        )
        self.sensor_configs["rain_total_daily"] = MQTTSensorConfig(
            name="Rain Total Daily",
            id="rain_total_daily",
            device_class="precipitation",
            unit_of_measurement="in",
            state_class="total",
            icon="mdi:weather-pouring",
        )
        self.sensor_configs["rain_total_weekly"] = MQTTSensorConfig(
            name="Rain Total Weekly",
            id="rain_total_weekly",
            device_class="precipitation",
            unit_of_measurement="in",
            state_class="total",
            icon="mdi:weather-pouring",
        )

    def connect(self) -> None:
        try:
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)

            for i in range(8):
                availability_topic = f"{self.state_prefix}/{i}/status"
                self.client.will_set(availability_topic, payload="offline", retain=True)

            self.client.connect(self.broker, self.port)
            self.client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def disconnect(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()
        if self._flush_task:
            self._flush_task.cancel()
        for topic in self._availability_topics.values():
            self.client.publish(topic, payload="offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(
        self, client: mqtt_client.Client, userdata: Any, flags: Dict[str, Any], rc: int
    ) -> None:
        if rc == 0:
            logger.info(
                f"Successfully connected to MQTT Broker at {self.broker}:{self.port} with client ID '{self.client_id}'"
            )
        else:
            logger.error(
                f"Failed to connect to MQTT Broker at {self.broker}:{self.port}, return code: {rc}"
            )

    def _on_disconnect(
        self, client: mqtt_client.Client, userdata: Any, rc: int
    ) -> None:
        logger.info("Disconnected from MQTT Broker.")

    def _publish_config(self, station_id: int, config: MQTTSensorConfig) -> None:
        device_id = f"rtldavis_{station_id}"
        effective_id = f"diag_{config.id}" if config.diagnostic else config.id
        unique_id = f"{device_id}_{effective_id}"

        config_topic = f"{self.discovery_prefix}/sensor/{unique_id}/config"
        state_topic = f"{self.state_prefix}/{station_id}/state"
        availability_topic = f"{self.state_prefix}/{station_id}/status"
        self._availability_topics[station_id] = availability_topic

        payload = {
            "name": f"Davis {config.name}",
            "unique_id": unique_id,
            "state_topic": state_topic,
            "value_template": f"{{% if '{effective_id}' in value_json %}}{{{{ value_json.{effective_id} }}}}{{% endif %}}",
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
        }
        if config.device_class:
            payload["device_class"] = config.device_class
        if config.unit_of_measurement and config.device_class != "uv_index":
            payload["unit_of_measurement"] = config.unit_of_measurement
        if config.state_class:
            payload["state_class"] = config.state_class
        if config.icon:
            payload["icon"] = config.icon
        if config.diagnostic:
            payload["entity_category"] = "diagnostic"

        logger.info(f"Publishing config for {config.id} to {config_topic}")
        self.client.publish(config_topic, json.dumps(payload), retain=True)
        self.client.publish(availability_topic, payload="online", retain=True)

    async def _timer_loop(self, station_id: int) -> None:
        """Samples time-since-last-data every second; the flush loop decides when
        that actually gets published, same as every other buffered sensor."""
        while True:
            await asyncio.sleep(1)
            if self._last_data_time:
                seconds_since = int(time.time() - self._last_data_time)
                self._buffer(station_id, "seconds_since_last_data", seconds_since)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.push_interval)
            for station_id in list(self._configured_stations):
                self._flush(station_id)

    def _buffer(self, station_id: int, sensor_id: str, value: Any) -> None:
        self._pending.setdefault(station_id, {}).setdefault(sensor_id, []).append(value)

    def _flush(self, station_id: int) -> None:
        pending = self._pending.pop(station_id, None)
        if not pending:
            return

        payload = {"id": station_id}
        for sensor_id, values in pending.items():
            cfg = self.sensor_configs.get(sensor_id)
            effective_id = f"diag_{sensor_id}" if (cfg and cfg.diagnostic) else sensor_id
            payload[effective_id] = _aggregate(sensor_id, values)

        state_topic = f"{self.state_prefix}/{station_id}/state"
        json_payload = json.dumps(payload)

        logger.info(f"Publishing aggregated message to topic '{state_topic}': {json_payload}")
        result = self.client.publish(state_topic, json_payload, retain=False)

        status = result[0]
        if status != 0:
            logger.warning(
                f"Failed to send message to topic '{state_topic}', status: {status}"
            )

    def publish(self, msg: Message) -> None:
        station_id = msg.id
        self._last_data_time = time.time()
        if self._timer_task is None:
            self._timer_task = asyncio.create_task(self._timer_loop(station_id))
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop())

        is_new_station = station_id not in self._configured_stations
        if is_new_station:
            logger.info(
                f"New station ID {station_id} detected. Publishing sensor configurations."
            )
            for config in self.sensor_configs.values():
                self._publish_config(station_id, config)
            self._configured_stations.add(station_id)

        for sensor_id, value in msg.sensor_values.items():
            if value is None:
                continue
            self._buffer(station_id, sensor_id, value)

        if is_new_station:
            # Publish the first reading immediately so entities don't sit
            # "unavailable" for a full push_interval right after (re)connecting.
            self._flush(station_id)
