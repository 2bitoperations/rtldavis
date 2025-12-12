import logging
import sys
import asyncio
import argparse
from typing import List, Dict, Any, Optional
import dataclasses
import numpy as np
import subprocess
import time

from rtlsdr.rtlsdr import RtlSdr
from rtlsdr.rtlsdraio import RtlSdrAio

from .version import __version__
from . import protocol
from .mqtt import MQTTPublisher

def get_git_info():
    try:
        commit_hash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).strip().decode('utf-8')
        status = subprocess.check_output(['git', 'status', '--porcelain']).strip().decode('utf-8')
        is_dirty = bool(status)
        return commit_hash, is_dirty
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None

def list_sdr_devices() -> List[Dict[str, Any]]:
    """List available RTL-SDR devices."""
    devices: List[Dict[str, Any]] = []
    try:
        serials = RtlSdr.get_device_serial_addresses()
        for i, serial in enumerate(serials):
            devices.append({
                'index': i,
                'name': 'RTL-SDR',
                'serial': serial
            })
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
        
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

async def main_async() -> int:
    """Asynchronous main function."""
    parser = argparse.ArgumentParser(description="Davis Instruments weather station receiver using RTL-SDR")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase logging verbosity")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--list-rtlsdr-devices", action="store_true", help="List detected RTL-SDR devices")
    parser.add_argument("--rtlsdr-serial", help="Select RTL-SDR device by serial number")
    parser.add_argument("--rtlsdr-index", type=int, help="Select RTL-SDR device by index")
    parser.add_argument("--station-id", type=int, help="Davis station ID to filter for (0-7)")
    parser.add_argument("--ppm", type=int, default=0, help="Frequency correction in PPM")
    parser.add_argument("--mqtt-broker", help="MQTT broker hostname")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--mqtt-discovery-prefix", default="homeassistant", help="MQTT discovery topic prefix")
    parser.add_argument("--mqtt-state-prefix", default="rtldavis", help="MQTT topic prefix for sensor state")
    parser.add_argument("--mqtt-client-id", default="davis-weather", help="MQTT client ID")
    parser.add_argument("--mqtt-username", help="MQTT username")
    parser.add_argument("--mqtt-password", help="MQTT password")
    
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger("rtldavis")

    if args.version:
        commit_hash, is_dirty = get_git_info()
        version_str = f"rtldavis {__version__}"
        if commit_hash:
            version_str += f" (git: {commit_hash}{' dirty' if is_dirty else ''})"
        print(version_str)
        return 0

    logger.warning("Starting rtldavis %s", __version__)
    commit_hash, is_dirty = get_git_info()
    if commit_hash:
        logger.warning("Git commit: %s%s", commit_hash, " (dirty)" if is_dirty else "")


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
                print(f"  Index: {dev['index']}, Name: {dev['name']}, Serial: {dev['serial']}")
        return 0

    if not devices:
        logger.error("No RTL-SDR devices found. Please connect a device.")
        return 1

    selected_device: Optional[Dict[str, Any]] = None
    if args.rtlsdr_serial:
        selected_device = next((d for d in devices if d['serial'] == args.rtlsdr_serial), None)
    elif args.rtlsdr_index is not None:
        selected_device = next((d for d in devices if d['index'] == args.rtlsdr_index), None)
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
        logger.warning("Initializing RTL-SDR device with index %d...", selected_device['index'])
        sdr = RtlSdrAio(device_index=selected_device['index'])
        
        p = protocol.Parser(symbol_length=14, station_id=args.station_id)
        sdr.sample_rate = p.cfg.sample_rate
        sdr.gain = 'auto'
        
        if args.ppm != 0:
            sdr.freq_correction = args.ppm

        # Start with a random hop to find the initial channel
        hop = p.rand_hop()
        sdr.center_freq = hop.channel_freq + hop.freq_corr
        logger.warning("Tuned to %d Hz (US Band) - Waiting for sync...", sdr.center_freq)

        # Synchronization state
        last_hop_time = time.time()
        
        # Event to signal a packet was received, to resync the hop timer
        packet_received_event = asyncio.Event()
        
        # Flag to indicate if we are synced
        is_synced = False

        async def hop_task():
            """Task to follow the station's hopping pattern."""
            nonlocal last_hop_time, is_synced
            
            # Wait until we are synced before starting the hop loop
            await packet_received_event.wait()
            is_synced = True
            packet_received_event.clear()
            last_hop_time = time.time()
            logger.info("Synced! Starting hop sequence.")

            while True:
                # Calculate when the next hop should occur
                next_hop_time = last_hop_time + p.dwell_time
                now = time.time()
                
                sleep_duration = next_hop_time - now
                
                if sleep_duration > 0:
                    try:
                        # Wait for the next hop time, or until a packet is received
                        await asyncio.wait_for(packet_received_event.wait(), timeout=sleep_duration)
                        # If we are here, a packet was received!
                        packet_received_event.clear()
                        # We received a packet, so we are synced.
                        # Reset our base time to prevent drift.
                        last_hop_time = time.time()
                        continue 
                    except asyncio.TimeoutError:
                        # Timeout means no packet received, time to hop!
                        pass
                
                # Time to hop
                new_hop = p.next_hop()
                sdr.center_freq = new_hop.channel_freq + new_hop.freq_corr
                logger.info("Hopping to %d Hz for transmitter %d", sdr.center_freq, new_hop.transmitter)
                last_hop_time = time.time()

        hop_task_handle = asyncio.create_task(hop_task())

        read_size = p.cfg.block_size * 8 # Read in chunks of 8 blocks of complex samples

        async for samples in sdr.stream(num_samples_or_bytes=read_size):
            for i in range(0, len(samples), p.cfg.block_size):
                chunk = samples[i : i + p.cfg.block_size]
                if len(chunk) == p.cfg.block_size:
                    packets = p.demodulator.demodulate(chunk)
                    messages = p.parse(packets)
                    
                    if messages:
                        # Signal the hop task that we received a packet
                        packet_received_event.set()
                        
                    for msg in messages:
                        logger.info("Received: %s", msg)
                        if mqtt_publisher:
                            payload = dataclasses.asdict(msg)
                            # The 'packet' field is not serializable and not needed
                            del payload['packet']
                            mqtt_publisher.publish(payload)

    except asyncio.CancelledError:
        logger.info("Stopping...")
    except Exception as e:
        logger.exception("An error occurred: %s", str(e))
        return 1
    finally:
        if 'hop_task_handle' in locals():
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
