import asyncio
import time
import logging

class Hopper:
    def __init__(self, parser, set_freq_callback):
        self.p = parser
        self.set_freq_callback = set_freq_callback
        self.logger = logging.getLogger("rtldavis.hopper")
        self.packet_received_event = asyncio.Event()
        self.MAX_MISSED = 50
        # A transmitter cycles through every channel in the hop table once
        # per full cycle (MAX_MISSED dwell periods, chosen to match: both
        # numbers represent "long enough that a reachable transmitter should
        # have hit every channel at least once"). Camping on a single
        # channel for less than that would abandon it before it could ever
        # have been heard; there's no benefit to waiting longer, since a
        # channel that's stayed silent for a full cycle is either not being
        # reached at all, or something channel-specific (interference,
        # hardware quirk) is blocking it -- in both cases picking a new
        # random channel is worth trying.
        self.SCAN_TIMEOUT_S = self.MAX_MISSED * self.p.dwell_time

    async def run(self):
        """
        Main hop sequence loop. Must be run as an asyncio task.
        """
        while True:
            # Scan/acquisition mode: listen on whatever channel we're
            # currently tuned to. If nothing arrives within one full
            # hop-cycle's worth of dwell time, try a different random
            # channel instead of camping forever on a possibly-bad pick.
            while True:
                try:
                    await asyncio.wait_for(
                        self.packet_received_event.wait(), timeout=self.SCAN_TIMEOUT_S
                    )
                    self.packet_received_event.clear()
                    sync_time = time.time()
                    break
                except asyncio.TimeoutError:
                    self.logger.warning(
                        f"No packet heard in {self.SCAN_TIMEOUT_S:.1f}s while scanning; "
                        "trying a different random channel."
                    )
                    scan_hop = self.p.rand_hop()
                    self.set_freq_callback(scan_hop)

            self.logger.info("Synced! Starting hop sequence.")

            # Wait 500ms before hopping so any SDR workers have time to finish decoding their buffers
            await asyncio.sleep(0.5)

            new_hop = self.p.next_hop()
            self.set_freq_callback(new_hop)

            # Anchor the schedule to when the sync packet arrived, not to when
            # we hopped. Using time.time() here would bake the 500ms sleep into
            # every expected arrival, pushing drift to about -0.5s, right on
            # the "too early" threshold, so real packets get rejected forever.
            last_hop_time = sync_time
            missed_count = 0

            while True:
                target_next_hop_time = last_hop_time + self.p.dwell_time
                timeout = max(0, (target_next_hop_time + 0.3) - time.time())

                try:
                    await asyncio.wait_for(
                        self.packet_received_event.wait(), timeout=timeout
                    )
                    self.packet_received_event.clear()

                    actual_time = time.time()
                    drift = actual_time - target_next_hop_time

                    if drift < -0.5:
                        self.logger.warning(
                            f"Packet received too early ({actual_time - last_hop_time:.4f}s). Ignoring as duplicate/glitch."
                        )
                        continue

                    self.logger.info(
                        f"Packet received. Expected: {target_next_hop_time:.4f}, Actual: {actual_time:.4f}, Drift: {drift:+.4f} s"
                    )

                    last_hop_time = actual_time
                    missed_count = 0

                    # Wait 500ms before hopping so SDR workers can finish decoding their buffers
                    await asyncio.sleep(0.5)

                except asyncio.TimeoutError:
                    missed_count += 1
                    self.logger.warning(
                        f"Missed packet {missed_count}/{self.MAX_MISSED}, hopping anyway."
                    )

                    if missed_count >= self.MAX_MISSED:
                        self.logger.warning(
                            "Too many missed packets. Lost sync. Reverting to scan mode."
                        )
                        scan_hop = self.p.rand_hop()
                        self.set_freq_callback(scan_hop)
                        break

                    last_hop_time = target_next_hop_time

                # Perform the hop
                new_hop = self.p.next_hop()
                self.set_freq_callback(new_hop)

    def trigger(self):
        """
        Signals that a packet was received, triggering the hopper to advance.
        """
        self.packet_received_event.set()
