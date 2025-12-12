import logging
import json
from paho.mqtt import client as mqtt_client
from typing import Any, Dict

logger = logging.getLogger(__name__)

class MQTTPublisher:
    def __init__(self, broker: str, port: int, topic: str, client_id: str) -> None:
        self.broker: str = broker
        self.port: int = port
        self.topic: str = topic
        self.client_id: str = client_id
        self.client: mqtt_client.Client = mqtt_client.Client(client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def connect(self) -> None:
        try:
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
            logger.info("Connected to MQTT Broker!")
        else:
            logger.error("Failed to connect, return code %d\n", rc)

    def _on_disconnect(self, client: mqtt_client.Client, userdata: Any, rc: int) -> None:
        logger.info("Disconnected from MQTT Broker.")

    def publish(self, message: Dict[str, Any]) -> None:
        topic = f"{self.topic}/{message['sensor'].lower().replace(' ', '_')}"
        payload = json.dumps(message)
        result = self.client.publish(topic, payload)
        
        status = result[0]
        if status == 0:
            logger.debug("Published message to topic %s", topic)
        else:
            logger.warning("Failed to send message to topic %s", topic)
