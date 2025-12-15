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
        # We only need the demodulator and parser logic here.
        # The hopping logic remains in the main process, but we need the parser
        # to decode the packets.
    except Exception as e:
        logger.exception(f"Failed to initialize worker: {e}")
        return

    while True:
        try:
            # Get raw samples from the main process
            # Block with a timeout to allow checking for exit conditions if needed
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
            # Demodulate and parse
            # We assume samples are chunks of size p.cfg.block_size
            # The main process sends chunks of size read_size = block_size * 8
            # So we need to iterate over the chunk
            
            # Note: The original code iterated in chunks of block_size.
            # We should probably do the same here to maintain logic consistency.
            
            block_size = p.cfg.block_size
            for i in range(0, len(samples), block_size):
                chunk = samples[i : i + block_size]
                if len(chunk) == block_size:
                    packets = p.demodulator.demodulate(chunk)
                    messages = p.parse(packets)
                    
                    for msg in messages:
                        # Send decoded message back to main process
                        result_queue.put(msg)
                        
        except Exception as e:
            logger.error(f"Error in DSP loop: {e}")
            continue
