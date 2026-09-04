"""
Dark Zone Tracking Engine — Multi-Station Block Tracker
=============================================================
Extends the single-station particle filter (dark_zone_tracker.py) to a
CONTIGUOUS BLOCK of dark stations (e.g. S07 through S13) where the vehicle
is only seen at block entry and block exit — nothing in between. The filter
must infer BOTH which station the vehicle currently occupies AND its
progress within that station, from elapsed time alone.

KEY DESIGN DECISION (read this before touching the particle math):
Each particle commits, at block-entry time, to a FULL per-station duration
hypothesis — one sampled value from EVERY station's own historical Gamma
fit, drawn once, not resampled or diffused step-by-step. Current station
and progress are then pure arithmetic from (elapsed_time, hypothesis) —
NOT an integrated random walk like the single-station filter used. This
avoids compounding drift error and means all genuine uncertainty comes
from the right place: not knowing each station's true duration in advance.

RIGHT-CENSORING (the piece that makes this work with ZERO intermediate
checkpoints): a particle whose total hypothesized duration is LESS than
the real elapsed time is claiming "the vehicle should already have exited"
— which is false, since we know it hasn't. That hypothesis is falsified by
the mere passage of time without an exit event, exactly like censored-data
survival analysis. Down-weighting these particles every predict() step
means the filter keeps sharpening even with total sensor silence.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Callable
from scipy import stats

from dark_zone_tracker import DwellDistribution


@dataclass
class MultiStationConfig:
    n_particles: int = 3000
    resample_threshold: float = 0.5     # ESS fraction below which we resample
    censoring_floor: float = 1e-6       # weight floor for time-inconsistent particles, not exact 0 (numerical safety / recoverability)


class MultiStationParticleFilter:
    """
    Tracks a vehicle through a CONTIGUOUS block of dark stations, inferring
    both current station identity and progress within it, from block-entry
    timestamp alone (plus optional intermediate checkpoints, if any exist).
    """

    def __init__(
        self,
        station_sequence: list[str],
        dwell_distributions: dict[str, DwellDistribution],
        config: MultiStationConfig = MultiStationConfig(),
        rng: Optional[np.random.Generator] = None,
    ):
        self.station_sequence = list(station_sequence)
        self.n_stations = len(station_sequence)
        self.cfg = config
        self.rng = rng or np.random.default_rng()

        n = self.cfg.n_particles
        # Each particle samples ONE full per-station duration hypothesis,
        # once, at spawn — this is the entire source of uncertainty.
        self.T = np.column_stack([
            np.clip(dwell_distributions[s].rvs(size=n, random_state=self.rng), 1e-3, None)
            for s in station_sequence
        ])  # shape (n_particles, n_stations)
        self.cum_T = np.cumsum(self.T, axis=1)          # cumulative station-boundary times per particle
        self.total_T = self.cum_T[:, -1]                 # total believed block duration per particle

        self.weights = np.full(n, 1.0 / n)
        self.elapsed_s = 0.0

        # Cache the pure arithmetic station/progress projection for the current
        # particle layout + elapsed time. The bridge may ask for the same
        # projection many times at one timestamp (queue reconstruction, render,
        # evidence export). Recomputing it is unnecessary.
        self._state_cache_elapsed_s = None
        self._state_cache_k = None
        self._state_cache_progress = None

    # ---------------- current station & progress (pure arithmetic, no simulation) ----------------
    def _invalidate_state_cache(self) -> None:
        self._state_cache_elapsed_s = None
        self._state_cache_k = None
        self._state_cache_progress = None

    def _current_station_and_progress(self):
        e = self.elapsed_s

        # The same MPF state is queried repeatedly by the corridor bridge at a
        # single timestamp. Return the already-computed projection when valid.
        if (
            self._state_cache_elapsed_s == e
            and self._state_cache_k is not None
            and self._state_cache_progress is not None
        ):
            return self._state_cache_k, self._state_cache_progress

        n = self.cfg.n_particles

        # For each row, searchsorted(..., side="right") is exactly the number of
        # cumulative boundaries <= elapsed time. Doing that comparison for the
        # whole matrix in NumPy removes the Python loop over all particles while
        # preserving the original station-index semantics exactly.
        k = np.sum(self.cum_T <= e, axis=1, dtype=np.intp)
        k = np.clip(k, 0, self.n_stations - 1)

        rows = np.arange(n)
        prev_idx = np.maximum(k - 1, 0)
        prev_cum = np.where(k == 0, 0.0, self.cum_T[rows, prev_idx])
        station_T = self.T[rows, k]
        progress = np.clip((e - prev_cum) / station_T, 0.0, 1.0)

        self._state_cache_elapsed_s = e
        self._state_cache_k = k
        self._state_cache_progress = progress
        return k, progress

    # ---------------- PREDICT (advance time + right-censoring reweight) ----------------
    def predict(self, dt_s: float) -> None:
        if dt_s != 0:
            self.elapsed_s += dt_s
            self._invalidate_state_cache()

        # Right-censoring: particles claiming the vehicle should already be
        # out (total_T < elapsed) are falsified by the absence of an exit
        # event. Down-weight heavily, not to exact zero (keeps the filter
        # numerically recoverable if this turns out to be wrong, e.g. a
        # missed exit event upstream).
        expired = self.total_T < self.elapsed_s
        if expired.any():
            self.weights[expired] *= self.cfg.censoring_floor
            self.weights += 1e-300
            self.weights /= self.weights.sum()

        if self._effective_sample_size() < self.cfg.resample_threshold * self.cfg.n_particles:
            self._systematic_resample()

    # ---------------- UPDATE (optional intermediate checkpoint, if any exists) ----------------
    def checkpoint_likelihood_values(
        self,
        observed_station: str,
        observed_progress: float,
        sensor_std: float = 0.05,
        wrong_station_floor: float = 0.02,
    ) -> np.ndarray:
        """Per-particle likelihood for a station/progress checkpoint."""
        k, progress = self._current_station_and_progress()
        target_idx = self.station_sequence.index(observed_station)
        station_match = (k == target_idx)
        return np.where(
            station_match,
            stats.norm.pdf(progress, loc=observed_progress, scale=sensor_std),
            wrong_station_floor,
        )

    def update_likelihood_values(self, likelihood: np.ndarray) -> None:
        """Apply already-computed non-negative particle likelihood values."""
        lik = np.asarray(likelihood, dtype=float)
        if lik.shape != self.weights.shape:
            raise ValueError("checkpoint likelihood shape does not match particle weights")
        lik = np.clip(lik, 0.0, None)
        self.weights *= lik
        self.weights += 1e-300
        self.weights /= self.weights.sum()
        if self._effective_sample_size() < self.cfg.resample_threshold * self.cfg.n_particles:
            self._systematic_resample()

    def update_checkpoint(
        self,
        observed_station: str,
        observed_progress: float,
        sensor_std: float = 0.05,
        wrong_station_floor: float = 0.02,
    ) -> None:
        """
        Optional evidence hook for a checkpoint INSIDE the block (e.g. a
        future RFID gate at S09). Not required — the filter works from
        elapsed time and censoring alone — but wired in for generality and
        consistency with the rest of this pipeline's Layer 3/5 pattern.
        A checkpoint is strong evidence about STATION IDENTITY (not just
        progress) — particles believing they're at the wrong station get a
        low floor likelihood rather than exact zero, for numerical safety.
        """
        lik = self.checkpoint_likelihood_values(
            observed_station, observed_progress, sensor_std, wrong_station_floor
        )
        self.update_likelihood_values(lik)

    # ---------------- ESTIMATE / RENDER EXPORT ----------------
    def estimate(self) -> dict:
        k, progress = self._current_station_and_progress()

        station_probs = {}
        for idx, station in enumerate(self.station_sequence):
            station_probs[station] = float(self.weights[k == idx].sum())

        best_station = max(station_probs, key=station_probs.get)
        best_idx = self.station_sequence.index(best_station)
        confidence = station_probs[best_station]

        mask = (k == best_idx)
        if mask.sum() > 0:
            w = self.weights[mask]
            w = w / w.sum()
            prog_mean = float(np.average(progress[mask], weights=w))
            prog_std = float(np.sqrt(np.average((progress[mask] - prog_mean) ** 2, weights=w)))
        else:
            prog_mean, prog_std = float("nan"), float("nan")

        probs = np.array(list(station_probs.values()))
        probs = probs[probs > 0]
        entropy = float(-np.sum(probs * np.log(probs))) if len(probs) else 0.0
        max_entropy = float(np.log(self.n_stations))  # uniform-belief upper bound, for normalizing

        remaining = np.maximum(self.total_T - self.elapsed_s, 0.0)
        eta_block_exit_s = float(np.average(remaining, weights=self.weights))

        return {
            "station_probs": station_probs,
            "most_likely_station": best_station,
            "confidence": confidence,
            "entropy": entropy,
            "entropy_normalized": entropy / max_entropy if max_entropy > 0 else 0.0,
            "progress_in_station_mean": prog_mean,
            "progress_in_station_std": prog_std,
            "eta_block_exit_s": eta_block_exit_s,
            "elapsed_s": self.elapsed_s,
        }

    # ---------------- internals ----------------
    def _effective_sample_size(self) -> float:
        return 1.0 / np.sum(self.weights ** 2)

    def _systematic_resample(self) -> None:
        n = self.cfg.n_particles
        positions = (self.rng.random() + np.arange(n)) / n
        cumsum = np.cumsum(self.weights)
        cumsum[-1] = 1.0
        idx = np.searchsorted(cumsum, positions)

        self.T = self.T[idx]
        self.cum_T = self.cum_T[idx]
        self.total_T = self.total_T[idx]
        self.weights = np.full(n, 1.0 / n)
        self._invalidate_state_cache()
