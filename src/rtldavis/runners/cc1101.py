import asyncio
import logging

from .. import protocol
from ..cc1101 import CC1101
from ..hopper import Hopper
from ..integrations import setup_integrations

async def run(args, log_level, sensor_store, mqtt_publisher):
    """Diagnostic loop running purely on the CC1101 backend."""
    logger = logging.getLogger("rtldavis.cc1101")
    tasks = []

    try:
        radio = CC1101(spi_bus=args.cc1101_spi_bus, spi_device=args.cc1101_spi_device)
        radio.open()
        radio.configure_for_davis()

        p = protocol.Parser(symbol_length=14, station_id=args.station_id, include_crc_failed=args.include_crc_failed)

        if args.channel is not None and 0 <= args.channel <= 50:
            hop_idx = p.hop_pattern.index(args.channel)
            hop = p.set_hop(hop_idx, p.transmitter)
        else:
            hop = p.rand_hop()

        radio.set_frequency(hop.channel_freq + args.cc1101_offset)
        radio.start_rx()

        logger.warning(
            f"CC1101 Tuned to {hop.channel_freq + args.cc1101_offset} Hz - Waiting for sync..."
        )

        tasks, ws_server = setup_integrations(args, sensor_store, mqtt_publisher)

        def set_freq(hop_obj):
            radio.set_frequency(hop_obj.channel_freq + args.cc1101_offset)
            logger.info(
                f"Hopping to {hop_obj.channel_freq + args.cc1101_offset} Hz for transmitter {hop_obj.transmitter}"
            )

        hopper = Hopper(p, set_freq)
        if not args.no_hop:
            hop_task_handle = asyncio.create_task(hopper.run())
            tasks.append(hop_task_handle)

        def _handle_messages(msgs):
            for msg in msgs:
                hopper.trigger()
                logger.info(f"Received: {msg}")
                sensor_store.update(msg)
                if mqtt_publisher:
                    mqtt_publisher.publish(msg)
                if ws_server:
                    asyncio.create_task(ws_server.broadcast("sensor", msg.sensor_values))

        # Poll the CC1101 RXFIFO.
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
        for t in tasks:
            t.cancel()
        radio.close()

    return 0
