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
    # Calibrated empirically against the ACTUAL 24-shift, 10,800-vehicle
    # full-line historical generation run — see ASSUMPTIONS.md for the
    # full multi-round history across Step 4 and its post-review patch.
    # The Step-4 values (bg=0.015, mid=0.062) realized 3.889% overall but
    # put ~51% of all defects in the zero-exposure/background bucket —
    # too large a share for a Quality use case that should mostly explain
    # its defects. These post-patch values shrink background risk (p(0)
    # now ~1.47%, vs. ~2.3% before) while RAISING exposed-vehicle risk
    # (steepness 70->110, midpoint 0.062->0.0445) so the ~4% overall total
    # comes predominantly from modeled exposure instead — found by a joint
    # grid search over (background, midpoint, steepness, max) against the
    # real exposure distribution, not by lowering background alone (which
    # would have just dropped the overall rate out of band).
    background_probability: float = 0.0088  # requirement 2: non-zero even at zero exposure
    max_probability: float = 0.8             # requirement 3: never a guaranteed fail
    midpoint: float = 0.0445                 # exposure level at which risk is halfway to max
    steepness: float = 110.0                 # how sharply probability rises around the midpoint


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
