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

        From rtldavis2, originally from:
        https://www.carluccio.de/davis-vue-hacking-part-2/
        > Goldcap [v]= ((Byte3 * 4) + ((Byte4 && 0xC0) / 64)) / 100
        
        The rtldavis2 Go code implements this as:
        `voltage := float32((m.Data[3]<<2)+((m.Data[4]&0xC0)>>6)) / 100`
        """
        raw_voltage = (data[3] << 2) + ((data[4] & 0xC0) >> 6)
        voltage = float(raw_voltage) / 100.0
        
        self.logger.info(f"    - Raw Value: 0x{raw_voltage:03X} ({raw_voltage})")
        self.logger.info("    - Formula: ((Byte3 << 2) + ((Byte4 & 0xC0) >> 6)) / 100.0")
        self.logger.info(f"    - Supercap Voltage: {voltage:.2f} V")

        return voltage
