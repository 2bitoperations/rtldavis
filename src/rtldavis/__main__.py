import logging
import sys
import asyncio
import argparse
from typing import List, Optional
import subprocess
import time
from dataclasses import dataclass

from rtlsdr.rtlsdr import RtlSdr
from rtlsdr.rtlsdraio import RtlSdrAio

from .version import __version__
from . import protocol
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
    devices: List[SDRDevice] = []
    try:
        serials = RtlSdr.get_device_serial_addresses()
        for i, serial in enumerate(serials):
            devices.append(SDRDevice(index=i, name="RTL-SDR", serial=serial))
        return devices
    except Exception as e:
        raise RuntimeError(f"Failed to enumerate RTL-SDR devices: {e}") from e


def setup_logging(verbosity: int) -> None:
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


async def main_async() -> int:
    """Asynchronous main function."""
    parser = argparse.ArgumentParser(
        description="Davis Instruments weather station receiver using RTL-SDR"
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
        "--rtlsdr-serial", help="Select RTL-SDR device by serial number"
    )
    parser.add_argument(
        "--rtlsdr-index", type=int, help="Select RTL-SDR device by index"
    )
    parser.add_argument(
        "--station-id", type=int, help="Davis station ID to filter for (0-7)"
    )
    parser.add_argument(
        "--ppm", type=int, default=0, help="Frequency correction in PPM"
    )
    parser.add_argument(
        "--gain",
        type=str,
        default="auto",
        help="Tuner gain. Can be 'auto' or a value in tenths of a dB (e.g., 49.6).",
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

    args = parser.parse_args()

    setup_logging(args.verbose)
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
    if args.rtlsdr_serial:
        selected_device = next(
            (d for d in devices if d.serial == args.rtlsdr_serial), None
        )
    elif args.rtlsdr_index is not None:
        selected_device = next(
            (d for d in devices if d.index == args.rtlsdr_index), None
        )
    elif len(devices) == 1:
        selected_device = devices[0]

    if not selected_device:
        logger.error("Multiple RTL-SDR devices found. Please specify one.")
        return 1

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

    sdr: Optional[RtlSdrAio] = None
    try:
        logger.warning(f"Initializing RTL-SDR device with index {selected_device.index}...")
        sdr = RtlSdrAio(device_index=selected_device.index)
        await asyncio.sleep(1)  # Allow device to settle

        p = protocol.Parser(symbol_length=14, station_id=args.station_id)
        sdr.sample_rate = p.cfg.sample_rate
        
        if args.gain.lower() == 'auto':
            sdr.gain = 'auto'
        else:
            try:
                sdr.gain = float(args.gain)
            except ValueError:
                logger.error(f"Invalid gain value: {args.gain}. Must be 'auto' or a number.")
                return 1

        if args.ppm != 0:
            sdr.freq_correction = args.ppm

        hop = p.rand_hop()
        sdr.center_freq = hop.channel_freq + hop.freq_corr
        logger.warning(f"Tuned to {sdr.center_freq} Hz (US Band) - Waiting for sync...")

        packet_received_event = asyncio.Event()

        async def hop_task():
            MAX_MISSED = 50

            while True:
                await packet_received_event.wait()
                packet_received_event.clear()
                logger.info("Synced! Starting hop sequence.")

                new_hop = p.next_hop()
                sdr.center_freq = new_hop.channel_freq + new_hop.freq_corr
                logger.info(
                    f"Hopping to {sdr.center_freq} Hz for transmitter {new_hop.transmitter}"
                )

                last_hop_time = time.time()
                missed_count = 0

                while True:
                    target_next_hop_time = last_hop_time + p.dwell_time
                    timeout = (target_next_hop_time + 0.3) - time.time()

                    if timeout < 0:
                        timeout = 0

                    try:
                        await asyncio.wait_for(
                            packet_received_event.wait(), timeout=timeout
                        )
                        packet_received_event.clear()

                        actual_time = time.time()
                        drift = actual_time - target_next_hop_time

                        if drift < -0.5:
                            logger.warning(
                                f"Packet received too early ({actual_time - last_hop_time:.4f}s). Ignoring as duplicate/glitch."
                            )
                            continue

                        logger.info(
                            f"Packet received. Expected: {target_next_hop_time:.4f}, Actual: {actual_time:.4f}, Drift: {drift:+.4f} s"
                        )

                        last_hop_time = actual_time
                        missed_count = 0
                    except asyncio.TimeoutError:
                        missed_count += 1
                        logger.warning(
                            f"Missed packet {missed_count}/{MAX_MISSED}, hopping anyway."
                        )

                        if missed_count >= MAX_MISSED:
                            logger.warning(
                                "Too many missed packets. Lost sync. Reverting to scan mode."
                            )
                            hop = p.rand_hop()
                            sdr.center_freq = hop.channel_freq + hop.freq_corr
                            logger.warning(
                                f"Tuned to {sdr.center_freq} Hz - Waiting for sync..."
                            )
                            break

                        last_hop_time = target_next_hop_time

                    new_hop = p.next_hop()
                    sdr.center_freq = new_hop.channel_freq + new_hop.freq_corr
                    logger.info(
                        f"Hopping to {sdr.center_freq} Hz for transmitter {new_hop.transmitter}"
                    )

        hop_task_handle = asyncio.create_task(hop_task())

        read_size = p.cfg.block_size * 8
        last_msg_data = None

        async for samples in sdr.stream(num_samples_or_bytes=read_size):
            for i in range(0, len(samples), p.cfg.block_size):
                chunk = samples[i : i + p.cfg.block_size]
                if len(chunk) == p.cfg.block_size:
                    packets = p.demodulator.demodulate(chunk)
                    messages = p.parse(packets)

                    valid_messages = []
                    for msg in messages:
                        msg_data_bytes = msg.packet.data.tobytes()
                        if msg_data_bytes == last_msg_data:
                            logger.debug(
                                f"Duplicate packet ignored: {msg_data_bytes.hex()}"
                            )
                            continue
                        last_msg_data = msg_data_bytes
                        valid_messages.append(msg)

                    if valid_messages:
                        packet_received_event.set()

                    for msg in valid_messages:
                        logger.info(f"Received: {msg}")
                        if mqtt_publisher:
                            mqtt_publisher.publish(msg)

    except asyncio.CancelledError:
        logger.info("Stopping...")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        return 1
    finally:
        if "hop_task_handle" in locals():
            hop_task_handle.cancel()
        if sdr:
            try:
                await sdr.stop()
            except Exception:
                pass
            sdr.close()
            logger.warning("Device closed.")
        if mqtt_publisher:
            mqtt_publisher.disconnect()

    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
