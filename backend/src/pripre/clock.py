"""Source UTC extrapolation independent of Linux clock frequency corrections."""

import asyncio
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

RAW_CLOCK: int | None = getattr(time, "CLOCK_MONOTONIC_RAW", None)


def steady_ns() -> int:
    """CLOCK_MONOTONIC still slews with NTP; RAW does not (Linux deployment)."""
    if RAW_CLOCK is not None:
        return time.clock_gettime_ns(RAW_CLOCK)
    return time.monotonic_ns()


async def wait_until(deadline_ns: int, elapsed_ns: Callable[[], int]) -> None:
    """Recheck raw deadlines because asyncio timers may themselves run on a slewed clock."""
    while (remaining := deadline_ns - elapsed_ns()) > 0:
        await asyncio.sleep(max(0.001, remaining / 1_000_000_000))


@dataclass(frozen=True)
class ClockSample:
    server_us: int
    started_ns: int
    finished_ns: int

    @property
    def rtt_ns(self) -> int:
        return self.finished_ns - self.started_ns


class MonotonicUTC:
    def __init__(
        self, anchor_us: int | None = None, monotonic_ns: Callable[[], int] | None = None
    ) -> None:
        self._monotonic = monotonic_ns or steady_ns
        self.synchronize(time.time_ns() // 1000 if anchor_us is None else anchor_us)

    def synchronize(self, timestamp_us: int) -> None:
        self._anchor_us = timestamp_us
        self._anchor_ns = self._monotonic()

    def synchronize_samples(self, samples: Sequence[ClockSample]) -> int:
        """Choose minimum RTT, reject >2s uncertainty, retain the sample's time anchor."""
        usable = [sample for sample in samples if 0 <= sample.rtt_ns <= 2_000_000_000]
        if not usable:
            raise ValueError("no sufficiently low-latency source clock sample")
        best = min(usable, key=lambda sample: sample.rtt_ns)
        self._anchor_us = best.server_us + best.rtt_ns // 2000
        self._anchor_ns = best.finished_ns
        return best.rtt_ns // 2000

    @property
    def sampled_at_ns(self) -> int:
        return self._anchor_ns

    def __call__(self) -> int:
        return self._anchor_us + (self._monotonic() - self._anchor_ns) // 1000
