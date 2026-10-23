import asyncio
import logging

from rtldavis.hopper import Hopper


class FakeParser:
    def __init__(self, dwell_time):
        self.dwell_time = dwell_time

    def next_hop(self):
        return "next"

    def rand_hop(self):
        return "rand"


async def _run_hopper(dwell_time, n_packets, period):
    hops = []
    hopper = Hopper(FakeParser(dwell_time), hops.append)
    task = asyncio.create_task(hopper.run())
    try:
        for i in range(n_packets):
            hopper.trigger()
            if i < n_packets - 1:
                await asyncio.sleep(period)
        # Let the last packet's post-receive hop (0.5s later) happen, but stop
        # before its next deadline (dwell + 0.3s) could register a miss.
        await asyncio.sleep(0.7)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return hops


def test_on_schedule_packets_after_sync_are_accepted(caplog):
    # Packets arriving ~one dwell period apart must be accepted as on-time,
    # not rejected as "too early". That used to happen because the schedule
    # was anchored to the post-sync hop (500ms after the sync packet), which
    # put drift at about -0.5s, right on the rejection threshold. The packets
    # run 50ms early here, so the old anchor lands clearly past it.
    caplog.set_level(logging.INFO, logger="rtldavis.hopper")
    hops = asyncio.run(_run_hopper(dwell_time=1.0, n_packets=3, period=0.95))

    messages = [r.getMessage() for r in caplog.records]
    assert not any("too early" in m for m in messages), messages
    assert not any("Missed packet" in m for m in messages), messages
    assert sum(m.startswith("Packet received.") for m in messages) == 2
    # One hop after the sync packet, then one after each accepted packet.
    assert hops == ["next", "next", "next"]
