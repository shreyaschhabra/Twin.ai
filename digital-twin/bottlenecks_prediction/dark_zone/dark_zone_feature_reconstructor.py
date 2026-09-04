from __future__ import annotations

"""
Dark Zone -> frozen bottleneck-model feature reconstruction.

This file is a BRIDGE only. It does not own or advance the Dark Zone tracking
engine. The preferred caller is ``dark_zone_ml_bridge.py``, which passes the
current posterior produced by the existing DarkZoneOrchestrator (single
station) or the existing MultiStationParticleFilter (corridor).

The 25 core features intentionally match the user's frozen Light-Zone causal
builder semantics:
  * recent window:  [t-10m, t]
  * previous window:[t-20m, t-10m)
  * queue/cycle std: sample std (ddof=1)
  * current_occupancy: latest causal queue-state estimate
  * arrivals: UNIT_ARRIVED count
  * services: PROCESSING_COMPLETED count
  * flow_pressure_10m: arrival COUNT - service COUNT
  * net_flow_rate_10m: (arrival COUNT - service COUNT) / 10
  * queue_slope_10m: queue units per millisecond, using the same least-squares
    time basis as the Light-Zone builder
  * station_index: numeric station number - 1

The extra three model features come from the Dark Zone posterior instead of
pretending an inferred Dark Zone state is directly observed:
  state_confidence, progress_std, eta_std.
"""

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence
import math
import re

import numpy as np
import pandas as pd

from dark_zone_tracker import DarkZoneParticleFilter
from multi_station_tracker import MultiStationParticleFilter

RECENT_MS = 600_000

BOTTLENECK_25 = [
    "capacity_headroom",
    "station_id",
    "base_cycle_time_ms",
    "station_archetype",
    "configured_cycle_std_ms",
    "station_index",
    "buffer_capacity",
    "line_fraction",
    "queue_max_10m",
    "queue_mean_10m",
    "current_occupancy",
    "queue_std_10m",
    "capacity_utilization",
    "arrival_rate_per_min_prev10m",
    "service_rate_per_min_prev10m",
    "service_rate_per_min_10m",
    "arrival_rate_per_min_10m",
    "utilization_headroom",
    "cycle_max_10m",
    "flow_pressure_10m",
    "queue_delta_10m",
    "cycle_mean_10m",
    "queue_slope_10m",
    "net_flow_rate_10m",
    "cycle_std_10m",
]
UNCERTAINTY_3 = ["state_confidence", "progress_std", "eta_std"]
FEATURES_28 = BOTTLENECK_25 + UNCERTAINTY_3


def _f(x: Any, default=np.nan) -> float:
    try:
        y = float(x)
        return y if math.isfinite(y) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _weighted_std(x: np.ndarray, w: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(w) & (w >= 0)
    x, w = x[m], w[m]
    if len(x) == 0 or w.sum() <= 0:
        return np.nan
    w = w / w.sum()
    mu = float(np.sum(w * x))
    return float(np.sqrt(np.sum(w * (x - mu) ** 2)))


def _weighted_quantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(w) & (w >= 0)
    x, w = x[m], w[m]
    if len(x) == 0 or w.sum() <= 0:
        return np.nan
    order = np.argsort(x)
    x, w = x[order], w[order]
    cw = np.cumsum(w) / w.sum()
    return float(x[min(np.searchsorted(cw, q, side="left"), len(x) - 1)])


def _sample_stats(values: Sequence[float]) -> tuple[float, float, float]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return np.nan, np.nan, np.nan
    return (
        float(np.mean(x)),
        float(np.std(x, ddof=1)) if len(x) > 1 else np.nan,
        float(np.max(x)),
    )


def _station_num(station_id: str, fallback_index: int) -> int:
    """Match station_num(x)-1 when the id has a numeric component; safe fallback otherwise."""
    m = re.search(r"(\d+)$", str(station_id))
    return int(m.group(1)) - 1 if m else int(fallback_index)


@dataclass(frozen=True)
class PredictionContext:
    run_id: str
    vehicle_id: str
    prediction_time: pd.Timestamp
    station_id: str
    variant: Optional[str]
    zone_type: str


@dataclass
class StationFeatureState:
    """Causal, station-level inputs maintained by the bridge.

    queue_history rows: {timestamp_ms, queue}
    arrival_times_ms: UNIT_ARRIVED timestamps (or explicitly marked proxy starts)
    service_times_ms: PROCESSING_COMPLETED timestamps
    cycle_history rows: {timestamp_ms, cycle_time_ms}
    """

    current_occupancy: float
    queue_history: Sequence[Mapping[str, Any]]
    arrival_times_ms: Sequence[int]
    service_times_ms: Sequence[int]
    cycle_history: Sequence[Mapping[str, Any]]
    # Model-facing uncertainty must stay in the Light-Zone feature domain:
    # occupancy_std is queue units (NOT vehicle-progress fraction).
    occupancy_std: float = 0.0
    state_confidence: float = 1.0
    uncertainty_source: str = "causal_queue_ledger"
    queue_source: str = "dark_zone_reconstructed"
    arrival_source: str = "unit_arrived"
    cycle_source: str = "processing_completed"


class DarkZoneFeatureReconstructor:
    def __init__(self, stations: pd.DataFrame):
        required = {
            "station_id",
            "archetype",
            "base_cycle_time_ms",
            "cycle_time_std_ms",
            "buffer_capacity",
        }
        missing = sorted(required - set(stations.columns))
        if missing:
            raise ValueError(f"stations.csv missing required columns: {missing}")

        s = stations.copy().drop_duplicates("station_id", keep="first").reset_index(drop=True)
        s["station_id"] = s["station_id"].astype(str)
        s["station_index"] = [
            _station_num(sid, i) for i, sid in enumerate(s["station_id"])
        ]
        # Frozen Light-Zone builder formula is idx / (number_of_stations - 1).
        s["line_fraction"] = s["station_index"] / max(len(s) - 1, 1)
        self.stations = s.set_index("station_id", drop=False)
        self.order = list(s["station_id"])

    def static(self, station_id: str) -> dict:
        sid = str(station_id)
        if sid not in self.stations.index:
            raise KeyError(f"Unknown station_id={sid}")
        r = self.stations.loc[sid]
        return {
            "station_id": sid,
            "base_cycle_time_ms": _f(r["base_cycle_time_ms"]),
            "station_archetype": str(r["archetype"]),
            "configured_cycle_std_ms": _f(r["cycle_time_std_ms"]),
            "station_index": int(r["station_index"]),
            "buffer_capacity": _f(r["buffer_capacity"]),
            "line_fraction": _f(r["line_fraction"]),
        }

    @staticmethod
    def _pf_snapshot(pf: DarkZoneParticleFilter) -> dict:
        est = pf.estimate()
        return {
            "progress_mean": _f(est.get("progress_mean")),
            "progress_std": _f(est.get("progress_std")),
            "eta_seconds": _f(est.get("eta_s")),
            "eta_std": _f(est.get("eta_std")),
            "state_confidence": _f(est.get("render_confidence")),
        }

    @staticmethod
    def _mpf_snapshot(mpf: MultiStationParticleFilter) -> dict:
        est = mpf.estimate()
        remaining = np.maximum(mpf.total_T - mpf.elapsed_s, 0.0)
        return {
            "progress_mean": _f(est.get("progress_in_station_mean")),
            "progress_std": _f(est.get("progress_in_station_std")),
            "eta_seconds": _f(est.get("eta_block_exit_s")),
            "eta_std": _weighted_std(remaining, mpf.weights),
            "state_confidence": _f(est.get("confidence")),
            "station_probs": est.get("station_probs", {}),
            "most_likely_station": est.get("most_likely_station"),
            "entropy": _f(est.get("entropy")),
            "entropy_normalized": _f(est.get("entropy_normalized")),
        }

    @staticmethod
    def queue_stats(
        queue_history: Sequence[Mapping[str, Any]], as_of_ms: int, current_occupancy: float
    ) -> dict:
        """Exact Light-Zone window/statistical semantics on reconstructed queue observations."""
        rows = []
        for r in queue_history:
            try:
                ts = int(r["timestamp_ms"])
                q = float(r["queue"])
            except (KeyError, TypeError, ValueError):
                continue
            if np.isfinite(q) and ts <= as_of_ms:
                rows.append((ts, q))
        # Do not add a duplicate prediction-time observation when the station
        # ledger already has state-change events. The Light-Zone builder aggregates
        # event observations, not repeated inference calls. If absolutely no queue
        # history exists yet, seed one causal estimate so the model can still run.
        if not rows and np.isfinite(current_occupancy):
            rows.append((int(as_of_ms), float(current_occupancy)))
        if not rows:
            return {
                "recent_mean": np.nan, "recent_std": np.nan, "recent_max": np.nan,
                "previous_mean": np.nan, "delta": np.nan,
                "slope": np.nan, "slope_std": np.nan,
            }

        rows.sort(key=lambda z: z[0])
        recent = [(t, q) for t, q in rows if as_of_ms - RECENT_MS <= t <= as_of_ms]
        previous = [
            (t, q) for t, q in rows
            if as_of_ms - 2 * RECENT_MS <= t < as_of_ms - RECENT_MS
        ]
        rmean, rstd, rmax = _sample_stats([q for _, q in recent])
        pmean, _, _ = _sample_stats([q for _, q in previous])
        delta = rmean - pmean if np.isfinite(rmean) and np.isfinite(pmean) else np.nan

        slope = np.nan
        slope_std = np.nan
        if len(recent) > 1:
            t = np.asarray([x[0] for x in recent], dtype=float)
            q = np.asarray([x[1] for x in recent], dtype=float)
            if np.unique(t).size > 1:
                x = t - t[0]
                fit = np.polyfit(x, q, 1)
                slope = float(fit[0])
                if len(x) > 2:
                    residual = q - (fit[0] * x + fit[1])
                    dof = len(x) - 2
                    sxx = float(np.sum((x - x.mean()) ** 2))
                    if dof > 0 and sxx > 0:
                        s_err = float(np.sqrt(np.sum(residual ** 2) / dof))
                        slope_std = float(s_err / np.sqrt(sxx))

        return {
            "recent_mean": rmean,
            "recent_std": rstd,
            "recent_max": rmax,
            "previous_mean": pmean,
            "delta": delta,
            "slope": slope,
            "slope_std": slope_std,
        }

    @staticmethod
    def _count_window(times_ms: Sequence[int], lo: int, hi: int, include_hi=True) -> int:
        if include_hi:
            return sum(lo <= int(x) <= hi for x in times_ms)
        return sum(lo <= int(x) < hi for x in times_ms)

    @classmethod
    def rate_counts(cls, state: StationFeatureState, as_of_ms: int) -> dict:
        lo10 = as_of_ms - RECENT_MS
        lo20 = as_of_ms - 2 * RECENT_MS
        arrivals10 = cls._count_window(state.arrival_times_ms, lo10, as_of_ms)
        arrivals_prev = cls._count_window(
            state.arrival_times_ms, lo20, lo10, include_hi=False
        )
        services10 = cls._count_window(state.service_times_ms, lo10, as_of_ms)
        services_prev = cls._count_window(
            state.service_times_ms, lo20, lo10, include_hi=False
        )
        return {
            "arrivals10": int(arrivals10),
            "arrivals_prev": int(arrivals_prev),
            "services10": int(services10),
            "services_prev": int(services_prev),
        }

    @staticmethod
    def cycle_stats(
        state: StationFeatureState,
        as_of_ms: int,
        dwell_model=None,
        pf: Optional[DarkZoneParticleFilter] = None,
        mpf: Optional[MultiStationParticleFilter] = None,
        corridor_station_index: Optional[int] = None,
    ) -> tuple[float, float, float, str]:
        recent = []
        for r in state.cycle_history:
            try:
                ts = int(r["timestamp_ms"])
                value = float(r["cycle_time_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            if as_of_ms - RECENT_MS <= ts <= as_of_ms and np.isfinite(value):
                recent.append(value)
        if recent:
            mean, std, maximum = _sample_stats(recent)
            return mean, std, maximum, state.cycle_source

        # Causal fallback when the dark station has no completed cycle in the
        # recent window. Values remain in milliseconds to match the builder.
        # Station cycle features in the training data summarize recent completed
        # station cycles, not the current vehicle. When no completed dark-zone
        # cycle is observable, prefer the station/variant dwell prior so these
        # features stay station-level. Vehicle PF posterior is only a last fallback.
        if dwell_model is not None:
            x = np.asarray(dwell_model.rvs(size=2000, random_state=0), dtype=float)
            w = np.ones(len(x), dtype=float)
        elif mpf is not None and corridor_station_index is not None:
            x = np.asarray(mpf.T[:, corridor_station_index], dtype=float)
            w = np.asarray(mpf.weights, dtype=float)
        elif pf is not None:
            x, w = np.asarray(pf.T, dtype=float), np.asarray(pf.weights, dtype=float)
        else:
            return np.nan, np.nan, np.nan, "unavailable"

        mean_s = float(np.average(x, weights=w))
        std_s = _weighted_std(x, w)
        max_s = _weighted_quantile(x, w, 0.99)
        return mean_s * 1000.0, std_s * 1000.0, max_s * 1000.0, "posterior_prior_fallback"

    @staticmethod
    def _model_uncertainty(
        q: Mapping[str, float],
        headroom: float,
        state: StationFeatureState,
    ) -> tuple[float, float, float]:
        """Map Dark-Zone queue uncertainty into the SAME units/meaning as training.

        Light Zone:
          state_confidence -> confidence in current queue state [0,1]
          progress_std     -> uncertainty of current occupancy, queue units
          eta_std          -> propagated uncertainty of time-to-capacity, milliseconds

        A tiny positive queue slope can mathematically produce an enormous eta_std.
        If the implied time-to-capacity is beyond a meaningful prediction horizon,
        eta_std is left as NaN instead of emitting a numerically huge value.
        """
        conf = float(np.clip(_f(state.state_confidence, 0.0), 0.0, 1.0))
        occ_std = _f(state.occupancy_std)
        if np.isfinite(occ_std):
            occ_std = max(0.0, occ_std)

        slope = _f(q.get("slope"))
        slope_std = _f(q.get("slope_std"))
        eta_std = np.nan

        # queue_slope_10m is in queue-units / millisecond, so
        # headroom / slope is time-to-capacity in milliseconds.
        MAX_ETA_HORIZON_MS = 60 * 60 * 1000  # 1 hour

        if (
            np.isfinite(slope)
            and slope > 0
            and np.isfinite(headroom)
            and headroom >= 0
        ):
            eta_to_capacity_ms = headroom / slope

            # Near-zero positive slopes imply an effectively unbounded ETA.
            # Use a legitimate missing value rather than an artificial/clipped number.
            if np.isfinite(eta_to_capacity_ms) and eta_to_capacity_ms <= MAX_ETA_HORIZON_MS:
                var_terms = []

                if np.isfinite(slope_std):
                    slope_term = (
                        (headroom / (slope ** 2)) ** 2
                        * (slope_std ** 2)
                    )
                    if np.isfinite(slope_term):
                        var_terms.append(slope_term)

                if np.isfinite(occ_std):
                    occupancy_term = (
                        (1.0 / slope) ** 2
                        * (occ_std ** 2)
                    )
                    if np.isfinite(occupancy_term):
                        var_terms.append(occupancy_term)

                if var_terms:
                    variance = float(sum(var_terms))
                    if np.isfinite(variance) and variance >= 0:
                        eta_std = float(np.sqrt(variance))

        return conf, occ_std, eta_std

    def reconstruct_single(
        self,
        ctx: PredictionContext,
        pf: DarkZoneParticleFilter,
        station_state: StationFeatureState,
        dwell_model=None,
        dark_zone_id: Optional[str] = None,
    ) -> dict:
        as_of = pd.to_datetime(ctx.prediction_time, utc=True)
        as_of_ms = int(as_of.timestamp() * 1000)
        st = self.static(ctx.station_id)
        post = self._pf_snapshot(pf)
        q = self.queue_stats(station_state.queue_history, as_of_ms, station_state.current_occupancy)
        rc = self.rate_counts(station_state, as_of_ms)
        cmean, cstd, cmax, cycle_source = self.cycle_stats(
            station_state, as_of_ms, dwell_model=dwell_model, pf=pf
        )

        occ = max(0.0, _f(station_state.current_occupancy, 0.0))
        cap = st["buffer_capacity"]
        util = occ / cap if np.isfinite(cap) and cap else np.nan
        headroom = cap - occ if np.isfinite(cap) else np.nan
        util_headroom = 1.0 - util if np.isfinite(util) else np.nan

        values = {
            "capacity_headroom": headroom,
            **st,
            "queue_max_10m": q["recent_max"],
            "queue_mean_10m": q["recent_mean"],
            "current_occupancy": occ,
            "queue_std_10m": q["recent_std"],
            "capacity_utilization": util,
            "arrival_rate_per_min_prev10m": rc["arrivals_prev"] / 10.0,
            "service_rate_per_min_prev10m": rc["services_prev"] / 10.0,
            "service_rate_per_min_10m": rc["services10"] / 10.0,
            "arrival_rate_per_min_10m": rc["arrivals10"] / 10.0,
            "utilization_headroom": util_headroom,
            "cycle_max_10m": cmax,
            "flow_pressure_10m": float(rc["arrivals10"] - rc["services10"]),
            "queue_delta_10m": q["delta"],
            "cycle_mean_10m": cmean,
            "queue_slope_10m": q["slope"],
            "net_flow_rate_10m": (rc["arrivals10"] - rc["services10"]) / 10.0,
            "cycle_std_10m": cstd,
            "state_confidence": self._model_uncertainty(q, headroom, station_state)[0],
            "progress_std": self._model_uncertainty(q, headroom, station_state)[1],
            "eta_std": self._model_uncertainty(q, headroom, station_state)[2],
        }
        provenance = self._single_provenance(station_state, cycle_source)
        return self._finalize(ctx, values, post, provenance, "single_station", dark_zone_id)

    def reconstruct_corridor(
        self,
        ctx: PredictionContext,
        mpf: MultiStationParticleFilter,
        station_state: StationFeatureState,
        rate_counts: Mapping[str, float],
        dwell_model=None,
        dark_zone_id: Optional[str] = None,
    ) -> dict:
        as_of = pd.to_datetime(ctx.prediction_time, utc=True)
        as_of_ms = int(as_of.timestamp() * 1000)
        post = self._mpf_snapshot(mpf)
        station_id = post["most_likely_station"]
        if station_id is None:
            raise ValueError("Corridor posterior has no most_likely_station")
        idx = mpf.station_sequence.index(station_id)
        st = self.static(station_id)
        q = self.queue_stats(station_state.queue_history, as_of_ms, station_state.current_occupancy)
        cmean, cstd, cmax, cycle_source = self.cycle_stats(
            station_state, as_of_ms, dwell_model=dwell_model, mpf=mpf,
            corridor_station_index=idx,
        )

        occ = max(0.0, _f(station_state.current_occupancy, 0.0))
        cap = st["buffer_capacity"]
        util = occ / cap if np.isfinite(cap) and cap else np.nan
        headroom = cap - occ if np.isfinite(cap) else np.nan
        util_headroom = 1.0 - util if np.isfinite(util) else np.nan
        a10 = float(rate_counts.get("arrivals10", 0.0))
        ap = float(rate_counts.get("arrivals_prev", 0.0))
        s10 = float(rate_counts.get("services10", 0.0))
        sp = float(rate_counts.get("services_prev", 0.0))

        values = {
            "capacity_headroom": headroom,
            **st,
            "queue_max_10m": q["recent_max"],
            "queue_mean_10m": q["recent_mean"],
            "current_occupancy": occ,
            "queue_std_10m": q["recent_std"],
            "capacity_utilization": util,
            "arrival_rate_per_min_prev10m": ap / 10.0,
            "service_rate_per_min_prev10m": sp / 10.0,
            "service_rate_per_min_10m": s10 / 10.0,
            "arrival_rate_per_min_10m": a10 / 10.0,
            "utilization_headroom": util_headroom,
            "cycle_max_10m": cmax,
            "flow_pressure_10m": a10 - s10,
            "queue_delta_10m": q["delta"],
            "cycle_mean_10m": cmean,
            "queue_slope_10m": q["slope"],
            "net_flow_rate_10m": (a10 - s10) / 10.0,
            "cycle_std_10m": cstd,
            "state_confidence": self._model_uncertainty(q, headroom, station_state)[0],
            "progress_std": self._model_uncertainty(q, headroom, station_state)[1],
            "eta_std": self._model_uncertainty(q, headroom, station_state)[2],
        }
        provenance = self._corridor_provenance(cycle_source)
        result = self._finalize(ctx, values, post, provenance, "corridor", dark_zone_id)
        result["dashboard"].update({
            "station_probs": post["station_probs"],
            "most_likely_station": post["most_likely_station"],
            "entropy": post["entropy"],
            "entropy_normalized": post["entropy_normalized"],
        })
        return result

    @staticmethod
    def _single_provenance(state: StationFeatureState, cycle_source: str) -> dict:
        static = {
            "station_id", "base_cycle_time_ms", "station_archetype",
            "configured_cycle_std_ms", "station_index", "buffer_capacity", "line_fraction",
        }
        queue = {
            "capacity_headroom", "queue_max_10m", "queue_mean_10m", "current_occupancy",
            "queue_std_10m", "capacity_utilization", "utilization_headroom",
            "queue_delta_10m", "queue_slope_10m",
        }
        arrivals = {"arrival_rate_per_min_prev10m", "arrival_rate_per_min_10m"}
        services = {"service_rate_per_min_prev10m", "service_rate_per_min_10m"}
        cycles = {"cycle_max_10m", "cycle_mean_10m", "cycle_std_10m"}
        derived_flow = {"flow_pressure_10m", "net_flow_rate_10m"}
        p = {}
        for f in BOTTLENECK_25:
            if f in static:
                p[f] = "static_config"
            elif f in queue:
                p[f] = state.queue_source
            elif f in arrivals:
                p[f] = state.arrival_source
            elif f in services:
                p[f] = "observed_processing_completed"
            elif f in cycles:
                p[f] = cycle_source
            elif f in derived_flow:
                p[f] = "derived_from_causal_arrival_service_counts"
            else:
                p[f] = "dark_zone_reconstructed"
        for f in UNCERTAINTY_3:
            p[f] = state.uncertainty_source + "_mapped_to_light_zone_uncertainty_semantics"
        return p

    @staticmethod
    def _corridor_provenance(cycle_source: str) -> dict:
        static = {
            "station_id", "base_cycle_time_ms", "station_archetype",
            "configured_cycle_std_ms", "station_index", "buffer_capacity", "line_fraction",
        }
        p = {}
        for f in BOTTLENECK_25:
            if f in static:
                p[f] = "static_config"
            elif f.startswith("cycle_"):
                p[f] = cycle_source
            else:
                p[f] = "corridor_posterior_reconstruction"
        for f in UNCERTAINTY_3:
            p[f] = "corridor_queue_posterior_mapped_to_light_zone_uncertainty_semantics"
        return p

    @staticmethod
    def _finalize(
        ctx: PredictionContext,
        values: Mapping[str, Any],
        posterior: Mapping[str, Any],
        provenance: Mapping[str, str],
        zone_type: str,
        dark_zone_id: Optional[str],
    ) -> dict:
        f28 = {k: values.get(k, np.nan) for k in FEATURES_28}
        if list(f28.keys()) != FEATURES_28:
            raise AssertionError("Frozen 28-feature order/contract changed")
        dashboard = {
            "run_id": ctx.run_id,
            "vehicle_id": ctx.vehicle_id,
            "prediction_time": pd.to_datetime(ctx.prediction_time, utc=True),
            "station_id": f28["station_id"],
            "dark_zone_id": dark_zone_id,
            "zone_type": zone_type,
            "dark_zone": True,
            "is_inferred": True,
            "data_source": "existing_dark_zone_engine_to_ml_bridge",
            # Dashboard uncertainty is vehicle-local PF uncertainty. It is deliberately
            # separated from the three model-facing queue uncertainty columns.
            "progress_mean": posterior.get("progress_mean"),
            "progress_std": posterior.get("progress_std"),
            "eta_seconds": posterior.get("eta_seconds"),
            "eta_std": posterior.get("eta_std"),
            "state_confidence": posterior.get("state_confidence"),
            "model_state_confidence": f28["state_confidence"],
            "model_progress_std_queue_units": f28["progress_std"],
            "model_eta_std_capacity_ms": f28["eta_std"],
        }
        return {"features_28": f28, "dashboard": dashboard, "provenance": dict(provenance)}


def validate_feature_frame(df: pd.DataFrame) -> dict:
    missing = [c for c in FEATURES_28 if c not in df.columns]
    extra_model_cols = [c for c in df.columns if c in set(FEATURES_28) and c not in FEATURES_28]
    numeric = [c for c in FEATURES_28 if c not in {"station_id", "station_archetype"}]
    inf_counts = {}
    nan_rates = {}
    for c in numeric:
        x = pd.to_numeric(df[c], errors="coerce") if c in df.columns else pd.Series(dtype=float)
        inf_counts[c] = int(np.isinf(x.to_numpy(dtype=float)).sum()) if len(x) else 0
        nan_rates[c] = float(x.isna().mean()) if len(x) else np.nan
    return {
        "feature_count": len(FEATURES_28),
        "missing_features": missing,
        "extra_model_columns": extra_model_cols,
        "infinite_counts": inf_counts,
        "nan_rates": nan_rates,
        "ready": not missing and not any(inf_counts.values()),
    }
