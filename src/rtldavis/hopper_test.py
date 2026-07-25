import asyncio
import unittest

from . import protocol
from .hopper import Hopper


def _fast_parser() -> protocol.Parser:
    """A real Parser with dwell_time shrunk so scan-timeout tests run fast."""
    p = protocol.Parser(symbol_length=14)
    p.dwell_time = 0.02
    return p


class TestHopperScanMode(unittest.IsolatedAsyncioTestCase):
    async def test_rehops_to_a_new_random_channel_after_scan_timeout(self):
        p = _fast_parser()
        tuned_channels = []
        hopper = Hopper(p, lambda hop: tuned_channels.append(hop.channel_idx))

        task = asyncio.create_task(hopper.run())
        try:
            # SCAN_TIMEOUT_S = MAX_MISSED * dwell_time = 50 * 0.02 = 1.0s;
            # give it a few timeout periods to force several re-hops while
            # never triggering the packet_received_event.
            await asyncio.sleep(hopper.SCAN_TIMEOUT_S * 3.5)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        # Each scan-timeout should have picked a new random channel via
        # rand_hop() and retuned through the callback.
        self.assertGreaterEqual(len(tuned_channels), 3)

    async def test_hearing_a_packet_exits_scan_mode_and_starts_hop_sequence(self):
        p = _fast_parser()
        rand_hop_calls = 0
        next_hop_calls = 0
        real_rand_hop = p.rand_hop
        real_next_hop = p.next_hop

        def counting_rand_hop():
            nonlocal rand_hop_calls
            rand_hop_calls += 1
            return real_rand_hop()

        def counting_next_hop():
            nonlocal next_hop_calls
            next_hop_calls += 1
            return real_next_hop()

        p.rand_hop = counting_rand_hop
        p.next_hop = counting_next_hop

        hopper = Hopper(p, lambda hop: None)
        task = asyncio.create_task(hopper.run())
        try:
            # No trigger yet: should be purely scan-mode rand_hop() re-tunes,
            # never next_hop() (that only happens once synced).
            await asyncio.sleep(hopper.SCAN_TIMEOUT_S * 2.5)
            self.assertGreater(rand_hop_calls, 0)
            self.assertEqual(next_hop_calls, 0)

            # Hearing a packet should exit scan mode and enter the synced
            # hop sequence, which calls next_hop() (after a 0.5s settle delay).
            hopper.trigger()
            await asyncio.sleep(0.6)
            self.assertGreater(next_hop_calls, 0)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_scan_timeout_matches_max_missed_times_dwell_time(self):
        p = _fast_parser()
        hopper = Hopper(p, lambda hop: None)
        self.assertAlmostEqual(hopper.SCAN_TIMEOUT_S, hopper.MAX_MISSED * p.dwell_time)


if __name__ == "__main__":
    unittest.main()
