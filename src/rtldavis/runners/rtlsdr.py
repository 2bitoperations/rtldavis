import asyncio
import logging
import multiprocessing
import queue

from .. import protocol
from ..worker import worker_main
from ..hopper import Hopper
from ..integrations import setup_integrations

try:
    from rtlsdr import RtlSdrAio
    HAS_RTLSDR = True
except ImportError:
    HAS_RTLSDR = False

async def run(args, log_level, devices, selected_device, sensor_store, mqtt_publisher):
    """Asynchronous runner for RTLSDR backend."""
    logger = logging.getLogger("rtldavis.rtlsdr")

    sdr = None
    worker_process = None
    try:
        logger.warning(f"Initializing RTL-SDR device with index {selected_device.index} (Serial: {selected_device.serial})...")
        sdr = RtlSdrAio(device_index=selected_device.index)
        
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

        # Set up peripherals
        tasks, ws_server = setup_integrations(args, sensor_store, mqtt_publisher)

        # Set up Hopper
        def set_freq(hop_obj):
            sdr.center_freq = hop_obj.channel_freq + hop_obj.freq_corr
            logger.info(f"Hopping to {sdr.center_freq} Hz for transmitter {hop_obj.transmitter}")

        hopper = Hopper(p, set_freq)
        if not args.no_hop:
            hop_task_handle = asyncio.create_task(hopper.run())
            tasks.append(hop_task_handle)

        async def result_queue_reader(q: multiprocessing.Queue):
            while True:
                try:
                    msg = await asyncio.to_thread(q.get_nowait)
                    if msg:
                        hopper.trigger()
                        logger.info(f"Received: {msg}")
                        sensor_store.update(msg)
                        if mqtt_publisher:
                            mqtt_publisher.publish(msg)
                        if ws_server:
                            asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))
                except queue.Empty:
                    await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"Error reading from result queue: {e}")

        result_reader_task = asyncio.create_task(result_queue_reader(result_queue))
        tasks.append(result_reader_task)

        read_size = p.cfg.block_size
        
        async for samples in sdr.stream(num_samples_or_bytes=read_size):
            data_queue.put(samples)

    except asyncio.CancelledError:
        logger.info("Stopping...")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        return 1
    finally:
        for t in tasks:
            t.cancel()
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

    return 0
