from dataclasses import dataclass
from typing import Optional, Any
from abc import ABC, abstractmethod
import logging


@dataclass
class MQTTSensorConfig:
    name: str
    id: str  # Used as the key in the JSON payload and suffix for unique_id
    device_class: Optional[str] = None
    unit_of_measurement: Optional[str] = None
    state_class: Optional[str] = None
    icon: Optional[str] = None


class AbstractSensor(ABC):
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    @property
    @abstractmethod
    def config(self) -> MQTTSensorConfig:
        pass

    @abstractmethod
    def decode(self, data: Any) -> Any:
        """
        Transforms the raw data into a value suitable for MQTT.
        For complex decoders, 'data' might be the raw bytes.
        For simple pass-throughs, 'data' might be the value itself.
        """
        pass
