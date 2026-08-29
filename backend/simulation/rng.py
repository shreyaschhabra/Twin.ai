"""
Deterministic, isolated RNG streams derived from one master seed.

Problem this solves: a single shared random.Random instance means every
consumer (vehicle arrivals, variant selection, each station's processing
time — and, starting Step 3, sensor noise, scenario occurrence/severity,
defect background noise) draws from the same sequence. Adding a draw
anywhere shifts every later consumer's numbers, which makes it impossible
to add a new stochastic mechanism later without silently changing the
timing of everything already validated.

RNGStreamFactory instead gives each named concern its own independent
random.Random instance, seeded by hashing (master_seed, stream_name)
together. Two streams from the same master seed are therefore both:
  - fully independent (separate random.Random state machines — consuming
    values from one can never affect another, by construction, not by
    convention), and
  - individually reproducible (the same master seed always derives the
    same per-stream seed, so re-running with the same seed reproduces
    every stream's sequence exactly).

Seeds are derived via SHA-256 over a UTF-8 string, never via Python's
built-in hash() — str hash() is randomized per-process (PYTHONHASHSEED)
unless explicitly disabled, which would silently break reproducibility
across processes/machines. SHA-256 has no such randomization.
"""

from __future__ import annotations

import hashlib
import random
from typing import Dict


def derive_seed(master_seed: int, stream_name: str) -> int:
    digest = hashlib.sha256(f"{master_seed}::{stream_name}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)  # 64 bits of the digest is ample for random.Random


class RNGStreamFactory:
    """One master seed in, any number of independent named streams out.
    Streams are created lazily and cached, so asking for the same name
    twice returns the same still-advancing Random instance, while a name
    never asked for is never created and therefore can't perturb anything
    (a future "sensor_noise::S01" stream unused in Step 2 has zero effect
    on Step 2 results)."""

    def __init__(self, master_seed: int):
        self.master_seed = master_seed
        self._streams: Dict[str, random.Random] = {}

    def get(self, stream_name: str) -> random.Random:
        if stream_name not in self._streams:
            self._streams[stream_name] = random.Random(derive_seed(self.master_seed, stream_name))
        return self._streams[stream_name]
