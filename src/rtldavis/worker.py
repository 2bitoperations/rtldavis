import logging
import multiprocessing
import time
from typing import Optional
import queue

from . import protocol
from .protocol import Message

def worker_main(
    data_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    station_id: Optional[int],
    symbol_length: int,
    log_level: int,
) -> None:
    """
    Main loop for the DSP worker process.
    """
    # Configure logging for the worker process
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger("rtldavis.worker")
    logger.info("DSP worker process started")

    # Initialize DSP and Parser
    try:
        p = protocol.Parser(symbol_length=symbol_length, station_id=station_id)
    except Exception as e:
        logger.exception(f"Failed to initialize worker: {e}")
        return

    while True:
        try:
            # Get raw samples from the main process
            samples = data_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        except KeyboardInterrupt:
            break

        if samples is None:
            # Sentinel value to stop the worker
            logger.info("Worker received stop signal")
            break

        try:
            packets = p.demodulator.demodulate(samples)
            messages = p.parse(packets)
            
            for msg in messages:
                # Send decoded message back to main process
                result_queue.put(msg)

        except Exception as e:
            logger.error(f"Error in DSP loop: {e}")
            continue
