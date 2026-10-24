"""UTC anchored to low-latency source samples and monotonic elapsed time."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass


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
        self, anchor_us: int | None = None, monotonic_ns: Callable[[], int] = time.monotonic_ns
    ) -> None:
        self._monotonic = monotonic_ns
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

    def __call__(self) -> int:
        return self._anchor_us + (self._monotonic() - self._anchor_ns) // 1000
