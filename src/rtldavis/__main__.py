import logging
import sys
import asyncio
import argparse
from typing import List, Optional
import subprocess
import time
from dataclasses import dataclass
import multiprocessing
import queue

try:
    from rtlsdr.rtlsdr import RtlSdr, librtlsdr
    from rtlsdr.rtlsdraio import RtlSdrAio
    HAS_RTLSDR = True
except ImportError:
    HAS_RTLSDR = False

from .version import __version__
from . import protocol
from .cc1101 import CC1101
from .mqtt import MQTTPublisher
from .worker import worker_main
from .sensor_store import SensorStore
from .rest_api import start_rest_server


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


async def _main_cc1101_async(args: argparse.Namespace, log_level: int) -> int:
    """Main loop for the CC1101 radio backend."""
    logger = logging.getLogger("rtldavis")

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

    radio = CC1101(spi_bus=args.cc1101_spi_bus, spi_device=args.cc1101_spi_device)

    try:
        radio.open()
        radio.configure_for_davis()

        p = protocol.Parser(symbol_length=14, station_id=args.station_id, include_crc_failed=args.include_crc_failed)

        hop = p.rand_hop()
        radio.set_frequency(hop.channel_freq + args.cc1101_offset)
        radio.start_rx()
        logger.warning(f"CC1101 tuned to {hop.channel_freq + args.cc1101_offset} Hz - Waiting for sync...")

        packet_received_event = asyncio.Event()

        rest_server_task = asyncio.create_task(
            start_rest_server(args.http_port, sensor_store.to_response)
        )

        from .websocket_server import start_ws_server
        ws_server = start_ws_server(args.ws_port)
        if args.buttons:
            from .buttons import init_buttons
            init_buttons(asyncio.get_running_loop(), ws_server.broadcast)

        def _handle_messages(msgs):
            for msg in msgs:
                packet_received_event.set()
                logger.info(f"Received: {msg}")
                sensor_store.update(msg)
                if mqtt_publisher:
                    mqtt_publisher.publish(msg)
                asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))

        bme280_task_handle = None
        if args.bme280:
            from .bme280_reader import start_bme280_task
            def _handle_bme280(msg):
                sensor_store.update(msg)
                if mqtt_publisher:
                    mqtt_publisher.publish(msg)
                asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))
            
            bme280_task_handle = start_bme280_task(
                bus_num=args.bme280_i2c_bus,
                address=int(args.bme280_i2c_address, 0),
                interval_s=60,
                callback=_handle_bme280
            )

        async def hop_task():
            MAX_MISSED = 50

            while True:
                await packet_received_event.wait()
                packet_received_event.clear()
                logger.info("Synced! Starting hop sequence.")

                new_hop = p.next_hop()
                radio.set_frequency(new_hop.channel_freq + args.cc1101_offset)
                logger.info(
                    f"Hopping to {new_hop.channel_freq + args.cc1101_offset} Hz for transmitter {new_hop.transmitter}"
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
                            scan_hop = p.rand_hop()
                            radio.set_frequency(scan_hop.channel_freq + args.cc1101_offset)
                            logger.warning(
                                f"CC1101 tuned to {scan_hop.channel_freq + args.cc1101_offset} Hz - Waiting for sync..."
                            )
                            break

                        last_hop_time = target_next_hop_time

                    if not args.no_hop:
                        new_hop = p.next_hop()
                        radio.set_frequency(new_hop.channel_freq + args.cc1101_offset)
                        logger.info(
                            f"Hopping to {new_hop.channel_freq + args.cc1101_offset} Hz for transmitter {new_hop.transmitter}"
                        )

        if not args.no_hop:
            hop_task_handle = asyncio.create_task(hop_task())

        # Poll the CC1101 RXFIFO. 10 ms keeps CPU usage low while still
        # being fast enough to drain a new packet before the next one arrives
        # (Davis transmits every ~2.5 s so there is no backlog risk).
        while True:
            pkt = await asyncio.to_thread(radio.receive_packet)
            if pkt is not None:
                msgs = p.parse([pkt])
                _handle_messages(msgs)
            else:
                await asyncio.sleep(0.01)

    except asyncio.CancelledError:
        logger.info("Stopping...")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        return 1
    finally:
        if "rest_server_task" in locals():
            rest_server_task.cancel()
        if "hop_task_handle" in locals() and not args.no_hop:
            hop_task_handle.cancel()
        if "bme280_task_handle" in locals() and bme280_task_handle is not None:
            bme280_task_handle.cancel()
        radio.close()
        logger.warning("CC1101 closed.")
        if mqtt_publisher:
            mqtt_publisher.disconnect()

    return 0


async def _main_dual_async(args: argparse.Namespace, log_level: int) -> int:
    """Diagnostic loop running RTLSDR and CC1101 concurrently."""
    logger = logging.getLogger("rtldavis")

    if not HAS_RTLSDR:
        logger.error("Cannot use 'dual' mode: librtlsdr is not installed.")
        return 1

    try:
        devices = list_sdr_devices()
    except RuntimeError as e:
        logger.error(str(e))
        return 1

    selected_device = None
    if devices:
        selected_device = devices[0]
        
    if not selected_device:
        logger.error("No RTL-SDR devices found. Cannot run dual mode.")
        return 1

    sensor_store = SensorStore()

    mqtt_publisher = None
    if args.mqtt_broker:
        mqtt_publisher = MQTTPublisher(
            broker=args.mqtt_broker, port=args.mqtt_port,
            discovery_prefix=args.mqtt_discovery_prefix, state_prefix=args.mqtt_state_prefix,
            client_id=args.mqtt_client_id, username=args.mqtt_username, password=args.mqtt_password,
        )
        mqtt_publisher.connect()

    radio = CC1101(spi_bus=args.cc1101_spi_bus, spi_device=args.cc1101_spi_device)
    sdr = None
    worker_process = None

    try:
        radio.open()
        radio.configure_for_davis()

        sdr = RtlSdrAio(device_index=selected_device.index)
        await asyncio.sleep(1)

        p = protocol.Parser(symbol_length=14, station_id=args.station_id, include_crc_failed=args.include_crc_failed)
        sdr.sample_rate = p.cfg.sample_rate
        sdr.gain = 'auto' if args.gain.lower() == 'auto' else float(args.gain)
        if args.ppm != 0: sdr.freq_correction = args.ppm

        if args.channel is not None and 0 <= args.channel <= 50:
            hop_idx = p.hop_pattern.index(args.channel)
            hop = p.set_hop(hop_idx, p.transmitter)
        else:
            hop = p.rand_hop()
            
        sdr.center_freq = hop.channel_freq + hop.freq_corr
        radio.set_frequency(hop.channel_freq + args.cc1101_offset)
        radio.start_rx()

        logger.warning(f"Dual Mode: RTLSDR tuned to {sdr.center_freq} Hz, CC1101 tuned to {hop.channel_freq + args.cc1101_offset} Hz - Waiting for sync...")

        data_queue = multiprocessing.Queue()
        result_queue = multiprocessing.Queue()
        
        worker_process = multiprocessing.Process(
            target=worker_main,
            args=(data_queue, result_queue, args.station_id, 14, log_level),
        )
        worker_process.start()

        packet_received_event = asyncio.Event()

        rest_server_task = asyncio.create_task(
            start_rest_server(args.http_port, sensor_store.to_response)
        )

        from .websocket_server import start_ws_server
        ws_server = start_ws_server(args.ws_port)
        if args.buttons:
            from .buttons import init_buttons
            init_buttons(asyncio.get_running_loop(), ws_server.broadcast)

        def _handle_msg_unified(msg):
            packet_received_event.set()
            sensor_store.update(msg)
            if mqtt_publisher: mqtt_publisher.publish(msg)
            asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))

        bme280_task_handle = None
        if args.bme280:
            from .bme280_reader import start_bme280_task
            def _handle_bme280(msg):
                sensor_store.update(msg)
                if mqtt_publisher: mqtt_publisher.publish(msg)
                asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))
            
            bme280_task_handle = start_bme280_task(
                bus_num=args.bme280_i2c_bus,
                address=int(args.bme280_i2c_address, 0),
                interval_s=60,
                callback=_handle_bme280
            )

        async def result_queue_reader(q: multiprocessing.Queue):
            while True:
                try:
                    msg = await asyncio.to_thread(q.get_nowait)
                    if msg:
                        logger.warning(f"[RTLSDR] Received: {msg}")
                        
                        # Immediately freeze and dump the CC1101 hardware state
                        state = await asyncio.to_thread(radio.debug_state)
                        logger.debug(f"[CC1101] Hardware State at Sync: {state}")
                        
                        _handle_msg_unified(msg)
                except queue.Empty:
                    await asyncio.sleep(0.01)

        result_reader_task = asyncio.create_task(result_queue_reader(result_queue))

        async def hop_task():
            MAX_MISSED = 50
            while True:
                await packet_received_event.wait()
                packet_received_event.clear()
                logger.info("Synced! Starting hop sequence.")

                # Wait 500ms before hopping so the RTLSDR worker has time to finish decoding its buffer
                await asyncio.sleep(0.5)

                new_hop = p.next_hop()
                sdr.center_freq = new_hop.channel_freq + new_hop.freq_corr
                radio.set_frequency(new_hop.channel_freq + args.cc1101_offset)

                last_hop_time = time.time()
                missed_count = 0

                while True:
                    target_next_hop_time = last_hop_time + p.dwell_time
                    timeout = max(0, (target_next_hop_time + 0.3) - time.time())

                    try:
                        await asyncio.wait_for(packet_received_event.wait(), timeout=timeout)
                        packet_received_event.clear()

                        actual_time = time.time()
                        drift = actual_time - target_next_hop_time

                        if drift < -0.5: continue

                        last_hop_time = actual_time
                        missed_count = 0
                        
                        # Wait 500ms before hopping so the RTLSDR worker has time to finish decoding its buffer
                        await asyncio.sleep(0.5)

                    except asyncio.TimeoutError:
                        missed_count += 1
                        if missed_count >= MAX_MISSED:
                            logger.warning("Lost sync. Reverting to scan mode.")
                            scan_hop = p.rand_hop()
                            sdr.center_freq = scan_hop.channel_freq + scan_hop.freq_corr
                            radio.set_frequency(scan_hop.channel_freq + args.cc1101_offset)
                            break
                        last_hop_time = target_next_hop_time

                    if not args.no_hop:
                        new_hop = p.next_hop()
                        sdr.center_freq = new_hop.channel_freq + new_hop.freq_corr
                        radio.set_frequency(new_hop.channel_freq + args.cc1101_offset)

        if not args.no_hop:
            hop_task_handle = asyncio.create_task(hop_task())

        async def cc1101_poller():
            while True:
                pkt = await asyncio.to_thread(radio.receive_packet)
                if pkt is not None:
                    logger.debug(f"[CC1101] Hardware Triggered! FIFO extracted: {pkt.data}")
                    msgs = p.parse([pkt])
                    for msg in msgs:
                        logger.warning(f"[CC1101] Received: {msg}")
                        _handle_msg_unified(msg)
                else:
                    await asyncio.sleep(0.01)

        cc1101_task = asyncio.create_task(cc1101_poller())

        read_size = p.cfg.block_size
        async for samples in sdr.stream(num_samples_or_bytes=read_size):
            data_queue.put(samples)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        return 1
    finally:
        if "rest_server_task" in locals(): rest_server_task.cancel()
        if "bme280_task_handle" in locals() and bme280_task_handle: bme280_task_handle.cancel()
        if "result_reader_task" in locals(): result_reader_task.cancel()
        if "hop_task_handle" in locals(): hop_task_handle.cancel()
        if "cc1101_task" in locals(): cc1101_task.cancel()
        if worker_process:
            data_queue.put(None)  # Sentinel to stop worker
            worker_process.join(timeout=2)
            if worker_process.is_alive():
                worker_process.terminate()
        if sdr:
            try:
                await sdr.stop()
            except Exception:
                pass
            sdr.close()
        radio.close()
        if mqtt_publisher: mqtt_publisher.disconnect()

    return 0


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

    if args.radio == "cc1101":
        return await _main_cc1101_async(args, log_level)
    elif args.radio == "dual":
        return await _main_dual_async(args, log_level)

    if not HAS_RTLSDR:
        logger.error("Cannot use 'rtlsdr' radio backend: librtlsdr is not installed. Did you mean '--radio cc1101'?")
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
        # Try to match by serial first
        selected_device = next(
            (d for d in devices if d.serial == args.rtlsdr_device), None
        )
        # If not found, try to match by index
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

    sdr = None
    worker_process = None
    try:
        logger.warning(f"Initializing RTL-SDR device with index {selected_device.index} (Serial: {selected_device.serial})...")
        sdr = RtlSdrAio(device_index=selected_device.index)
        await asyncio.sleep(1)  # Allow device to settle
        
        logger.info(f"Tuner: {sdr.get_tuner_type()}")
        logger.info(f"Gain values: {sdr.get_gains()}")

        p = protocol.Parser(symbol_length=14, station_id=args.station_id, include_crc_failed=args.include_crc_failed)
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

        if args.channel is not None and 0 <= args.channel <= 50:
            hop_idx = p.hop_pattern.index(args.channel)
            hop = p.set_hop(hop_idx, p.transmitter)
        else:
            hop = p.rand_hop()
            
        sdr.center_freq = hop.channel_freq + hop.freq_corr
        
        logger.info(f"SDR Initial State: Gain={sdr.get_gain()}, Sample Rate={sdr.get_sample_rate()}, Center Freq={sdr.get_center_freq()}, Freq Correction={sdr.get_freq_correction()}ppm")

        logger.warning(f"Tuned to {sdr.center_freq} Hz (US Band) - Waiting for sync...")

        # Set up multiprocessing
        data_queue = multiprocessing.Queue()
        result_queue = multiprocessing.Queue()
        
        worker_process = multiprocessing.Process(
            target=worker_main,
            args=(data_queue, result_queue, args.station_id, 14, log_level),
        )
        worker_process.start()

        packet_received_event = asyncio.Event()

        async def result_queue_reader(q: multiprocessing.Queue):
            while True:
                try:
                    msg = await asyncio.to_thread(q.get_nowait)
                    if msg:
                        packet_received_event.set()
                        logger.info(f"Received: {msg}")
                        sensor_store.update(msg)
                        if mqtt_publisher:
                            mqtt_publisher.publish(msg)
                        asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))
                except queue.Empty:
                    await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"Error reading from result queue: {e}")

        result_reader_task = asyncio.create_task(result_queue_reader(result_queue))

        rest_server_task = asyncio.create_task(
            start_rest_server(args.http_port, sensor_store.to_response)
        )

        from .websocket_server import start_ws_server
        ws_server = start_ws_server(args.ws_port)
        if args.buttons:
            from .buttons import init_buttons
            init_buttons(asyncio.get_running_loop(), ws_server.broadcast)

        bme280_task_handle = None
        if args.bme280:
            from .bme280_reader import start_bme280_task
            def _handle_bme280(msg):
                sensor_store.update(msg)
                if mqtt_publisher:
                    mqtt_publisher.publish(msg)
                asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))
            
            bme280_task_handle = start_bme280_task(
                bus_num=args.bme280_i2c_bus,
                address=int(args.bme280_i2c_address, 0),
                interval_s=60,
                callback=_handle_bme280
            )

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

                    if not args.no_hop:
                        new_hop = p.next_hop()
                        sdr.center_freq = new_hop.channel_freq + new_hop.freq_corr
                        logger.info(
                            f"Hopping to {sdr.center_freq} Hz for transmitter {new_hop.transmitter}"
                        )

        if not args.no_hop:
            hop_task_handle = asyncio.create_task(hop_task())

        read_size = p.cfg.block_size
        
        async for samples in sdr.stream(num_samples_or_bytes=read_size):
            data_queue.put(samples)

    except asyncio.CancelledError:
        logger.info("Stopping...")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        return 1
    finally:
        if "result_reader_task" in locals():
            result_reader_task.cancel()
        if "rest_server_task" in locals():
            rest_server_task.cancel()
        if "hop_task_handle" in locals() and not args.no_hop:
            hop_task_handle.cancel()
        if "bme280_task_handle" in locals() and bme280_task_handle is not None:
            bme280_task_handle.cancel()
        if worker_process:
            data_queue.put(None)  # Sentinel to stop worker
            worker_process.join(timeout=5)
            if worker_process.is_alive():
                worker_process.terminate()
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
        # Set start method for multiprocessing
        multiprocessing.set_start_method("fork")
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
