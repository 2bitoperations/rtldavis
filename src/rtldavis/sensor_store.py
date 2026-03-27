"""
In-memory store for the latest sensor readings.
"""
import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .sensor_classes import AbstractSensor, MQTTSensorConfig
from . import decoders

logger = logging.getLogger(__name__)


@dataclass
class SensorReading:
    description: str
    value: Any
    timestamp_ms: int
    units: Optional[str]


class SensorStore:
    """Holds the most recent reading for each sensor."""

    def __init__(self) -> None:
        self._metadata: Dict[str, MQTTSensorConfig] = {}
        self._readings: Dict[str, SensorReading] = {}

        # Collect metadata from all registered decoder classes via all_configs
        for decoder_class in vars(decoders).values():
            if (
                isinstance(decoder_class, type)
                and issubclass(decoder_class, AbstractSensor)
                and decoder_class is not AbstractSensor
            ):
                try:
                    instance = decoder_class(logger)
                    for cfg in instance.all_configs:
                        self._metadata[cfg.id] = cfg
                except Exception as exc:
                    logger.warning(f"Could not load config for {decoder_class}: {exc}")

    def update(self, msg: Any) -> None:
        """Record the latest values from a decoded Message."""
        ts_ms = int(time.time() * 1000)
        for sensor_id, value in msg.sensor_values.items():
            if value is None:
                continue
            meta = self._metadata.get(sensor_id)
            description = meta.name if meta else sensor_id
            units = meta.unit_of_measurement if meta else None
            self._readings[sensor_id] = SensorReading(
                description=description,
                value=value,
                timestamp_ms=ts_ms,
                units=units,
            )

    def to_response(self) -> Dict[str, Any]:
        """Return a JSON-serializable map of the latest sensor readings."""
        return {
            sensor_id: {
                "name": sensor_id,
                "description": reading.description,
                "value": reading.value,
                "timestamp_ms": reading.timestamp_ms,
                "units": reading.units,
            }
            for sensor_id, reading in self._readings.items()
        }
