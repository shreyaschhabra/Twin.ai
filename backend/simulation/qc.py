"""
Final QC outcome generation (Step 4). Converts a vehicle's accumulated
latent quality exposure into a probabilistic binary QC outcome — the
first place in the project where an actual PASS/DEFECT label is created.

Deliberately NOT a deterministic threshold (`if exposure > x: defect`),
per instructions — that produces unrealistic, perfectly separable labels.
Instead a smooth, bounded, monotonic mapping from exposure to probability,
then a single Bernoulli draw from an isolated RNG stream.

QCParameters is intentionally small and easy to recalibrate: the
historical generator regenerates data after adjusting these three numbers
until the overall defect rate lands in the target band — see
ASSUMPTIONS.md for the actual calibration history.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class QCParameters:
    # Calibrated empirically, in three rounds, against the ACTUAL 24-shift,
    # 10,800-vehicle full-line historical generation run
    # (dataset_master_seed=20240001) — see ASSUMPTIONS.md for the full
    # history. Round 1 (tuned against a hand-built 3-scenario mix rather
    # than the real shift scheduler's output) landed at 2.1% once actually
    # run at scale. Round 2 (bg=0.017, midpoint=0.06) landed at 4.65% —
    # just outside the 3.5-4.5% band, Bernoulli sampling variance around
    # an expected value of ~4.0%. These round-3 values realize 3.64%.
    # NOT re-derived from any real defect-rate data.
    background_probability: float = 0.015   # requirement 2: non-zero even at zero exposure
    max_probability: float = 0.75            # requirement 3: never a guaranteed fail
    midpoint: float = 0.062                  # exposure level at which risk is halfway to max
    steepness: float = 70.0                  # how sharply probability rises around the midpoint


class QCOutcomeGenerator:
    def __init__(self, params: QCParameters, rng: random.Random):
        self.params = params
        self.rng = rng

    def compute_probability(self, total_exposure: float) -> float:
        """Logistic-style mapping, monotonically increasing in exposure,
        bounded in (background_probability, max_probability)."""
        p = self.params
        z = p.steepness * (total_exposure - p.midpoint)
        sigmoid = 1.0 / (1.0 + math.exp(-z))
        return p.background_probability + (p.max_probability - p.background_probability) * sigmoid

    def draw_outcome(self, total_exposure: float):
        """Returns (is_defect: bool, probability_used: float). The
        probability is returned for latent-truth logging only — it must
        never be attached to the observable QC_RESULT_RECORDED event."""
        probability = self.compute_probability(total_exposure)
        is_defect = self.rng.random() < probability
        return is_defect, probability
