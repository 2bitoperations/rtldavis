import logging
import sys
import asyncio
import argparse
from typing import List, Optional
import subprocess
import time
from dataclasses import dataclass

try:
    from rtlsdr.rtlsdr import RtlSdr, librtlsdr
    from rtlsdr.rtlsdraio import RtlSdrAio
    HAS_RTLSDR = True
except ImportError:
    HAS_RTLSDR = False

from .version import __version__
from .sensor_store import SensorStore
from .mqtt import MQTTPublisher

@dataclass
class GitInfo:
    commit_hash: str
    is_dirty: bool

@dataclass
class SDRDevice:
    index: int
    name: str
    serial: str

def get_git_info() -> Optional[GitInfo]:
    try:
        commit_hash = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .strip()
            .decode("utf-8")
        )
        status = (
            subprocess.check_output(["git", "status", "--porcelain"])
            .strip()
            .decode("utf-8")
        )
        is_dirty = bool(status)
        return GitInfo(commit_hash, is_dirty)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def list_sdr_devices() -> List[SDRDevice]:
    """List available RTL-SDR devices."""
    if not HAS_RTLSDR:
        raise RuntimeError("RTL-SDR python module or C library (librtlsdr) is not installed on this system.")
        
    devices: List[SDRDevice] = []
    try:
        serials = RtlSdr.get_device_serial_addresses()
        for i, serial in enumerate(serials):
            devices.append(SDRDevice(index=i, name="RTL-SDR", serial=serial))
        return devices
    except Exception as e:
        raise RuntimeError(f"Failed to enumerate RTL-SDR devices: {e}") from e

def setup_logging(verbosity: int) -> int:
    """Configure logging."""
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    return level


async def main_async() -> int:
    """Asynchronous main function."""
    parser = argparse.ArgumentParser(
        description="Davis Instruments weather station receiver"
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase logging verbosity"
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument(
        "--list-rtlsdr-devices",
        action="store_true",
        help="List detected RTL-SDR devices",
    )
    parser.add_argument(
        "--radio",
        choices=["rtlsdr", "cc1101", "dual"],
        default="rtlsdr",
        help="Radio backend to use (default: rtlsdr)",
    )
    parser.add_argument(
        "--rtlsdr-device", help="Select RTL-SDR device by serial number or index"
    )
    parser.add_argument(
        "--cc1101-spi-bus", type=int, default=0, help="SPI bus number for CC1101 (default: 0)"
    )
    parser.add_argument(
        "--cc1101-spi-device", type=int, default=0, help="SPI device (chip-select) for CC1101 (default: 0)"
    )
    parser.add_argument(
        "--cc1101-gdo0-pin",
        type=int,
        default=None,
        help="BCM GPIO pin connected to CC1101 GDO0 for interrupt-driven reception (optional)",
    )
    parser.add_argument(
        "--station-id", type=int, help="Davis station ID to filter for (0-7)"
    )
    parser.add_argument(
        "--ppm", type=int, default=0, help="Frequency correction in PPM (RTL-SDR only)"
    )
    parser.add_argument(
        "--cc1101-offset", type=int, default=0, help="Frequency offset in Hz for CC1101 crystal error (e.g., 32600)"
    )
    parser.add_argument(
        "--include-crc-failed", action="store_true", help="Log failed CRCs and raw demod output"
    )
    parser.add_argument(
        "--channel", type=int, default=None, help="Force a specific channel index (0-50)"
    )
    parser.add_argument(
        "--gain",
        type=str,
        default="auto",
        help="Tuner gain. Can be 'auto' or a value in tenths of a dB (e.g., 49.6).",
    )
    parser.add_argument(
        "--no-hop", action="store_true", help="Disable frequency hopping for debugging"
    )
    parser.add_argument("--mqtt-broker", help="MQTT broker hostname")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument(
        "--mqtt-discovery-prefix",
        default="homeassistant",
        help="MQTT discovery topic prefix",
    )
    parser.add_argument(
        "--mqtt-state-prefix",
        default="rtldavis",
        help="MQTT topic prefix for sensor state",
    )
    parser.add_argument(
        "--mqtt-client-id", default="davis-weather", help="MQTT client ID"
    )
    parser.add_argument("--mqtt-username", help="MQTT username")
    parser.add_argument("--mqtt-password", help="MQTT password")
    parser.add_argument(
        "--http-port",
        type=int,
        default=8088,
        help="Port for the REST API server (GET /sensors). Default: 8088.",
    )
    parser.add_argument("--bme280", action="store_true", help="Enable local BME280 I2C sensor reading")
    parser.add_argument("--bme280-i2c-bus", type=int, default=1, help="I2C bus number for BME280 (default: 1)")
    parser.add_argument("--bme280-i2c-address", type=str, default="0x77", help="I2C address for BME280 (default: 0x77)")
    parser.add_argument("--buttons", action="store_true", help="Enable local GPIO 5-way button handling")
    parser.add_argument("--ws-port", type=int, default=8089, help="WebSocket server port (default: 8089)")
    parser.add_argument("--timeout", type=int, default=0, help="Stop after N seconds (0 = run forever)")

    args = parser.parse_args()

    log_level = setup_logging(args.verbose)
    logger = logging.getLogger("rtldavis")

    if args.version:
        git_info = get_git_info()
        version_str = f"rtldavis {__version__}"
        if git_info:
            version_str += (
                f" (git: {git_info.commit_hash}{' dirty' if git_info.is_dirty else ''})"
            )
        print(version_str)
        return 0

    logger.warning(f"Starting rtldavis {__version__}")
    git_info = get_git_info()
    if git_info:
        logger.warning(
            f"Git commit: {git_info.commit_hash}{' (dirty)' if git_info.is_dirty else ''}"
        )

    if args.timeout > 0:
        async def stop_after_timeout():
            import asyncio, os, signal
            await asyncio.sleep(args.timeout)
            logger.warning(f"Timeout of {args.timeout}s reached, stopping rtldavis.")
            os.kill(os.getpid(), signal.SIGINT)
        asyncio.create_task(stop_after_timeout())

    sensor_store = SensorStore()

    mqtt_publisher: Optional[MQTTPublisher] = None
    if args.mqtt_broker:
        mqtt_publisher = MQTTPublisher(
            broker=args.mqtt_broker,
            port=args.mqtt_port,
            discovery_prefix=args.mqtt_discovery_prefix,
            state_prefix=args.mqtt_state_prefix,
            client_id=args.mqtt_client_id,
            username=args.mqtt_username,
            password=args.mqtt_password,
        )
        mqtt_publisher.connect()

    if args.radio == "cc1101":
        from .runners.cc1101 import run
        return await run(args, log_level, sensor_store, mqtt_publisher)
    
    # Dual and RTLSDR modes require librtlsdr
    if not HAS_RTLSDR:
        logger.error("Cannot use 'rtlsdr' or 'dual' radio backend: librtlsdr is not installed. Did you mean '--radio cc1101'?")
        return 1

    try:
        devices = list_sdr_devices()
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    if args.list_rtlsdr_devices:
        if not devices:
            print("No RTL-SDR devices found.")
        else:
            print(f"Found {len(devices)} RTL-SDR device(s):")
            for dev in devices:
                print(f"  Index: {dev.index}, Name: {dev.name}, Serial: {dev.serial}")
        return 0

    if not devices:
        logger.error("No RTL-SDR devices found. Please connect a device.")
        return 1

    selected_device: Optional[SDRDevice] = None
    if args.rtlsdr_device:
        selected_device = next((d for d in devices if d.serial == args.rtlsdr_device), None)
        if not selected_device:
            try:
                idx = int(args.rtlsdr_device)
                selected_device = next((d for d in devices if d.index == idx), None)
            except ValueError:
                pass
    elif len(devices) == 1:
        selected_device = devices[0]

    if not selected_device:
        if args.rtlsdr_device:
            logger.error(f"RTL-SDR device '{args.rtlsdr_device}' not found.")
        else:
            logger.error("Multiple RTL-SDR devices found. Please specify one.")
        return 1

    if args.radio == "dual":
        from .runners.dual import run
        return await run(args, log_level, devices, selected_device, sensor_store, mqtt_publisher)
    else:
        from .runners.rtlsdr import run
        return await run(args, log_level, devices, selected_device, sensor_store, mqtt_publisher)


def main() -> int:
    try:
        import multiprocessing
        multiprocessing.set_start_method("fork")
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
