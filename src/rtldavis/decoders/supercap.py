"""
Decoder for Davis supercap voltage data.
"""
import logging
from ..sensor_classes import AbstractSensor, MQTTSensorConfig

class SupercapSensor(AbstractSensor):
    def __init__(self, logger: logging.Logger):
        super().__init__(logger)

    @property
    def config(self) -> MQTTSensorConfig:
        return MQTTSensorConfig(
            name="Supercap Voltage",
            id="super_cap_voltage",
            device_class="voltage",
            unit_of_measurement="V",
            state_class="measurement",
        )

    def decode(self, data: bytes) -> float:
        """
        Decodes the supercap voltage from a raw data packet.
        """
        raw_voltage = (data[3] << 2) + ((data[4] & 0xC0) >> 6)
        voltage = float(raw_voltage) / 100.0
        
        self.logger.info(
            f"  - Supercap Voltage Data (Bytes 3-4):\n"
            f"    - Raw Value: 0x{raw_voltage:03X} ({raw_voltage})\n"
            f"    - Formula: ((Byte3 << 2) + ((Byte4 & 0xC0) >> 6)) / 100.0\n"
            f"    - Supercap Voltage: {voltage:.2f} V"
        )

        return voltage
