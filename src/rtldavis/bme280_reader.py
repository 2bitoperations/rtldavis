import asyncio
import logging
import time
from typing import Callable, Dict, Any

try:
    import smbus2
    import bme280
except ImportError:
    smbus2 = None
    bme280 = None

logger = logging.getLogger(__name__)


class BME280Message:
    """
    A lightweight message object that mimics the `protocol.Message` structure
    so it can be routed directly into SensorStore and MQTTPublisher.
    """
    def __init__(self, values: Dict[str, Any]):
        self.sensor_values = values


def _read_bme280_sync(bus_num: int, address: int) -> Dict[str, Any]:
    if smbus2 is None or bme280 is None:
        logger.error("smbus2 or RPi.bme280 libraries not installed.")
        return {}

    try:
        # Opening and closing the bus each time ensures we don't hold the file descriptor open,
        # and recovers cleanly from temporary bus faults.
        with smbus2.SMBus(bus_num) as bus:
            calibration_params = bme280.load_calibration_params(bus, address)
            data = bme280.sample(bus, address, calibration_params)
            
            return {
                "indoor_temperature": round(data.temperature, 2),
                "indoor_humidity": round(data.humidity, 2),
                "barometric_pressure": round(data.pressure, 2),
            }
    except OSError as e:
        logger.warning(f"OS Error communicating with BME280 at 0x{address:02x}: {e}")
        return {}
    except Exception as e:
        logger.error(f"Failed to read BME280: {e}")
        return {}


async def _bme280_polling_loop(
    bus_num: int, address: int, interval_s: int, callback: Callable[[Any], None]
):
    logger.info(f"Starting BME280 polling task on I2C bus {bus_num}, address 0x{address:02x} every {interval_s}s.")
    while True:
        data = await asyncio.to_thread(_read_bme280_sync, bus_num, address)
        if data:
            msg = BME280Message(data)
            try:
                callback(msg)
            except Exception as e:
                logger.error(f"Error in BME280 callback: {e}")
        
        await asyncio.sleep(interval_s)


def start_bme280_task(
    bus_num: int, address: int, interval_s: int, callback: Callable[[Any], None]
) -> asyncio.Task:
    """
    Spawns an asyncio task to poll the local BME280 sensor.
    """
    return asyncio.create_task(_bme280_polling_loop(bus_num, address, interval_s, callback))
