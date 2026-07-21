import asyncio
import logging
import multiprocessing
import queue

from .. import protocol
from ..worker import worker_main
from ..cc1101 import CC1101
from ..hopper import Hopper
from ..integrations import setup_integrations

try:
    from rtlsdr import RtlSdrAio
    HAS_RTLSDR = True
except ImportError:
    HAS_RTLSDR = False

async def run(args, log_level, devices, selected_device, sensor_store, mqtt_publisher):
    """Diagnostic loop running RTLSDR and CC1101 concurrently."""
    logger = logging.getLogger("rtldavis.dual")

    radio = CC1101(spi_bus=args.cc1101_spi_bus, spi_device=args.cc1101_spi_device)
    sdr = None
    worker_process = None
    tasks = []

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

        tasks, ws_server = setup_integrations(args, sensor_store, mqtt_publisher)

        def set_freq(hop_obj):
            sdr.center_freq = hop_obj.channel_freq + hop_obj.freq_corr
            radio.set_frequency(hop_obj.channel_freq + args.cc1101_offset)

        hopper = Hopper(p, set_freq)
        if not args.no_hop:
            hop_task_handle = asyncio.create_task(hopper.run())
            tasks.append(hop_task_handle)

        def _handle_msg_unified(msg):
            hopper.trigger()
            sensor_store.update(msg)
            if mqtt_publisher: mqtt_publisher.publish(msg)
            if ws_server:
                asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))

        async def result_queue_reader(q: multiprocessing.Queue):
            while True:
                try:
                    msg = await asyncio.to_thread(q.get_nowait)
                    if msg:
                        logger.warning(f"[RTLSDR] Received: {msg}")
                        state = await asyncio.to_thread(radio.debug_state)
                        logger.debug(f"[CC1101] Hardware State at Sync: {state}")
                        _handle_msg_unified(msg)
                except queue.Empty:
                    await asyncio.sleep(0.01)

        result_reader_task = asyncio.create_task(result_queue_reader(result_queue))
        tasks.append(result_reader_task)

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
        tasks.append(cc1101_task)

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
            data_queue.put(None)
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

    return 0
