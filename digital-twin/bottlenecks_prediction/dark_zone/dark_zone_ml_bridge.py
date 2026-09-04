from __future__ import annotations

"""
Passive Dark Zone -> ML bridge.

Important architecture rule:
    DarkZoneOrchestrator / DarkZoneParticleFilter / MultiStationParticleFilter
    remain the state-estimation engines. This module never reimplements the
    single-station Bayesian update logic. It routes real events through the
    existing orchestrator and reads the resulting posterior to construct the
    frozen bottleneck-model feature vector.

The offline runner in this file is only a replay harness. In a live service,
instantiate ``SingleStationMLBridge`` with the already-running orchestrator and
call ``observe_engine_event`` / ``emit`` from the same event-bus path.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
import hashlib
import heapq
import json

import numpy as np
import pandas as pd

from csv_adapter import load_all_dark_zone_events, load_checkpoint_progress_map
from dark_zone_tracker import DwellDistribution, fit_dwell_distribution
from dark_zone_feature_reconstructor import (
    DarkZoneFeatureReconstructor,
    PredictionContext,
    StationFeatureState,
    FEATURES_28,
    validate_feature_frame,
    RECENT_MS,
)
from multi_station_tracker import MultiStationConfig, MultiStationParticleFilter
from orchestrator import DarkZoneEvent, DarkZoneOrchestrator, EventType, power_draw_likelihood


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ts(ms: int | float) -> pd.Timestamp:
    return pd.to_datetime(int(ms), unit="ms", utc=True)


def _ms(seconds: float) -> int:
    return int(round(float(seconds) * 1000.0))


def _config_prior(station_row, scale: float = 1.0) -> DwellDistribution:
    mean = max(float(station_row.base_cycle_time_ms) / 1000.0 * scale, 1e-3)
    std = float(station_row.cycle_time_std_ms) / 1000.0 * scale
    if not np.isfinite(std) or std <= 1e-6:
        std = max(0.10 * mean, 0.5)
    shape = (mean / std) ** 2
    gamma_scale = (std ** 2) / mean
    return DwellDistribution(
        station=str(station_row.station_id),
        variant="__ALL__",
        dist_name="gamma",
        params=(shape, 0.0, gamma_scale),
        n_samples=0,
        fallback=True,
    )


def load_dwell_models(
    historical_dwell_csv: str,
    stations: pd.DataFrame,
    dist_name: str = "gamma",
    config_prior_scale: float = 1.0,
) -> tuple[dict, list[str]]:
    hist = pd.read_csv(historical_dwell_csv)
    req = {"station_id", "variant", "entry_ts", "exit_ts"}
    missing = sorted(req - set(hist.columns))
    if missing:
        raise ValueError(f"historical_dwell.csv missing required columns: {missing}")
    hist["station_id"] = hist["station_id"].astype(str)
    hist["variant"] = hist["variant"].astype(str)
    hist["entry_ts"] = pd.to_datetime(hist["entry_ts"], utc=True, format="mixed")
    hist["exit_ts"] = pd.to_datetime(hist["exit_ts"], utc=True, format="mixed")

    models = fit_dwell_distribution(
        hist,
        dist_name=dist_name,
        min_samples_for_own_fit=30,
    )
    # Explicit station-level entries are useful to both orchestrator and corridor code.
    for station in stations["station_id"].astype(str):
        if (station, "__ALL__") not in models:
            candidates = [v for (sid, _), v in models.items() if sid == station]
            if candidates:
                models[(station, "__ALL__")] = candidates[0]

    # Safe runnability fallback: configured cycle prior, never current-run future data.
    config_fallbacks = []
    for r in stations.itertuples(index=False):
        sid = str(r.station_id)
        if (sid, "__ALL__") not in models:
            models[(sid, "__ALL__")] = _config_prior(r, config_prior_scale)
            config_fallbacks.append(sid)

    # Global fallback for the existing orchestrator's final fallback branch.
    if ("__GLOBAL__", "__ALL__") not in models:
        means = [m.mean() for (sid, var), m in models.items() if var == "__ALL__" and sid != "__GLOBAL__"]
        stds = [m.std() for (sid, var), m in models.items() if var == "__ALL__" and sid != "__GLOBAL__"]
        if means:
            mean = float(np.nanmean(means))
            std = float(np.nanmean(stds)) if stds else max(0.1 * mean, 0.5)
            shape = (mean / max(std, 1e-3)) ** 2
            scale = max(std, 1e-3) ** 2 / mean
            models[("__GLOBAL__", "__ALL__")] = DwellDistribution(
                station="__GLOBAL__", variant="__ALL__", dist_name="gamma",
                params=(shape, 0.0, scale), n_samples=0, fallback=True,
            )
    return models, config_fallbacks




# Corridor residence calibration is deliberately separate from processing-cycle
# calibration. The multi-station PF needs time a unit physically occupies a
# station (including queue/waiting), while the ML cycle_* features represent
# processing cycle time. Mixing those two quantities corrupts one side or the other.
CORRIDOR_LOAD_BINS = (
    (0, 2, "load_0_2"),
    (3, 3, "load_3"),
    (4, 4, "load_4"),
    (5, 5, "load_5"),
    (6, 6, "load_6"),
    (7, 7, "load_7"),
    (8, 8, "load_8"),
    (9, 9, "load_9"),
    (10, 10, "load_10"),
    (11, None, "load_11_plus"),
)


def _corridor_load_bin(active_count: int) -> str:
    n = max(0, int(active_count))
    for lo, hi, label in CORRIDOR_LOAD_BINS:
        if n >= lo and (hi is None or n <= hi):
            return label
    return "load_11_plus"


def _fit_residence_models(
    frame: pd.DataFrame,
    dist_name: str,
    min_samples: int = 20,
    *,
    outlier_trim: bool = True,
) -> dict:
    if frame.empty:
        return {}
    specific = fit_dwell_distribution(
        frame,
        dist_name=dist_name,
        min_samples_for_own_fit=min_samples,
        outlier_trim=outlier_trim,
    )
    pooled_frame = frame.copy()
    pooled_frame["variant"] = "__ALL__"
    pooled = fit_dwell_distribution(
        pooled_frame,
        dist_name=dist_name,
        min_samples_for_own_fit=min_samples,
        outlier_trim=outlier_trim,
    )
    specific.update(pooled)
    return specific


def _fit_corridor_residence_models(
    frame: pd.DataFrame,
    dist_name: str,
    min_samples: int,
) -> dict:
    """Fit corridor residence priors without deleting valid first-station modes.

    The first DARK station can have a real two-regime residence distribution:
    fast pass-through when its buffer is clear and long residence when vehicles
    wait in the entrance queue. MAD trimming can incorrectly classify the fast
    regime as an outlier in congested load bins, biasing the PF toward keeping
    too many vehicles at the first station.

    Calibration rows generated by ``build_corridor_residence_calibration`` carry
    ``corridor_first_station``. For those rows only, retain the full distribution.
    Internal corridor stations keep the original robust outlier trimming. Older
    calibration files without that marker preserve the previous behaviour.
    """
    if frame.empty:
        return {}
    if "corridor_first_station" not in frame.columns:
        return _fit_residence_models(
            frame, dist_name, min_samples=min_samples, outlier_trim=True
        )

    first_marker = frame["corridor_first_station"].astype(str).str.strip()
    is_first = frame["station_id"].astype(str).eq(first_marker)
    fitted: dict = {}

    internal = frame.loc[~is_first].copy()
    if not internal.empty:
        fitted.update(
            _fit_residence_models(
                internal, dist_name, min_samples=min_samples, outlier_trim=True
            )
        )

    first = frame.loc[is_first].copy()
    if not first.empty:
        # Both the short/no-wait and long/queued regimes are physical signal.
        fitted.update(
            _fit_residence_models(
                first, dist_name, min_samples=min_samples, outlier_trim=False
            )
        )
    return fitted


FIRST_STATION_LOCAL_MIN_SAMPLES = 20


def _fit_first_station_local_load_models(
    hist: pd.DataFrame,
    dist_name: str,
    min_samples: int = FIRST_STATION_LOCAL_MIN_SAMPLES,
) -> tuple[dict, dict]:
    """Fit adaptive local-load priors for the first station of each corridor.

    ``corridor_load`` is exactly observable at the upstream boundary (number of
    vehicles already inside the corridor).  For a first DARK station, residence
    changes sharply across high corridor loads, so a single ``load_11_plus``
    bucket can mix physically different queue regimes.

    For each integer load we therefore fit the smallest symmetric neighbourhood
    around that load that has enough historical samples.  Dense loads use their
    own data; sparse loads borrow only nearby loads.  This is generic to the
    first station named by ``corridor_first_station`` -- no station ID is
    hard-coded -- and uses historical/past information only.
    """
    if hist.empty or "corridor_first_station" not in hist.columns:
        return {}, {}

    marker = hist["corridor_first_station"].astype(str).str.strip()
    first = hist.loc[hist["station_id"].astype(str).eq(marker)].copy()
    if first.empty:
        return {}, {}

    models: dict = {}
    meta: dict = {}
    for sid, gsid in first.groupby("station_id", sort=False):
        gsid = gsid.copy()
        gsid["corridor_load"] = pd.to_numeric(gsid["corridor_load"], errors="coerce")
        gsid = gsid[gsid["corridor_load"].notna()].copy()
        if gsid.empty:
            continue
        gsid["corridor_load_int"] = gsid["corridor_load"].round().astype(int).clip(lower=0)
        lo = int(gsid["corridor_load_int"].min())
        hi = int(gsid["corridor_load_int"].max())

        for target_load in range(lo, hi + 1):
            chosen = None
            chosen_radius = None
            max_radius = max(target_load - lo, hi - target_load, 0)
            for radius in range(max_radius + 1):
                local = gsid[
                    (gsid["corridor_load_int"] - target_load).abs() <= radius
                ]
                if len(local) >= min_samples:
                    chosen = local.copy()
                    chosen_radius = radius
                    break

            if chosen is None:
                # Very small historical sets: use the nearest available rows
                # rather than a distant high-load/global pool.
                chosen = (
                    gsid.assign(
                        _load_distance=(gsid["corridor_load_int"] - target_load).abs()
                    )
                    .sort_values(["_load_distance", "corridor_load_int"], kind="stable")
                    .head(min(min_samples, len(gsid)))
                    .drop(columns=["_load_distance"])
                )
                chosen_radius = int(
                    (chosen["corridor_load_int"] - target_load).abs().max()
                ) if not chosen.empty else 0

            fitted = _fit_residence_models(
                chosen,
                dist_name,
                min_samples=max(8, min_samples // 2),
                outlier_trim=False,
            )
            for (fit_sid, variant), model in fitted.items():
                if str(fit_sid) != str(sid):
                    continue
                key = (str(sid), str(variant), int(target_load))
                models[key] = model
                meta["|".join(map(str, key))] = {
                    "n_samples": int(model.n_samples),
                    "radius": int(chosen_radius or 0),
                    "load_min": int(chosen["corridor_load_int"].min()),
                    "load_max": int(chosen["corridor_load_int"].max()),
                }

    return models, meta


def load_corridor_residence_models(corridor_residence_csv: str, dist_name: str = "gamma") -> dict:
    """Load historical *occupancy residence* calibration for corridor inference.

    Required columns are station_id, variant, entry_ts, exit_ts and one causal
    corridor-load column: corridor_load / active_corridor_count / active_count.
    The load value must describe vehicles already inside the corridor when this
    vehicle entered. It is observable from corridor boundary events in live use.
    """
    hist = pd.read_csv(corridor_residence_csv)
    req = {"station_id", "variant", "entry_ts", "exit_ts"}
    missing = sorted(req - set(hist.columns))
    if missing:
        raise ValueError(f"corridor residence calibration missing columns: {missing}")
    load_col = next((c for c in ("corridor_load", "active_corridor_count", "active_count") if c in hist.columns), None)
    if load_col is None:
        raise ValueError(
            "corridor residence calibration needs corridor_load (vehicles already inside at corridor entry)"
        )
    hist = hist.copy()
    hist["station_id"] = hist["station_id"].astype(str)
    hist["variant"] = hist["variant"].astype(str)
    hist["entry_ts"] = pd.to_datetime(hist["entry_ts"], utc=True, format="mixed")
    hist["exit_ts"] = pd.to_datetime(hist["exit_ts"], utc=True, format="mixed")
    hist["corridor_load"] = pd.to_numeric(hist[load_col], errors="coerce")
    hist = hist[hist["corridor_load"].notna()].copy()
    hist["load_bin"] = hist["corridor_load"].astype(int).map(_corridor_load_bin)

    unconditional = _fit_corridor_residence_models(hist, dist_name, min_samples=20)
    first_station_local, first_station_local_meta = _fit_first_station_local_load_models(
        hist, dist_name
    )
    conditional = {}
    counts = {}
    for label, g in hist.groupby("load_bin", sort=False):
        fitted = _fit_corridor_residence_models(g, dist_name, min_samples=15)
        for (sid, variant), model in fitted.items():
            conditional[(sid, variant, str(label))] = model
            counts[f"{sid}|{variant}|{label}"] = int(model.n_samples)
    return {
        "conditional": conditional,
        "unconditional": unconditional,
        "first_station_local": first_station_local,
        "first_station_local_meta": first_station_local_meta,
        "counts": counts,
        "rows": int(len(hist)),
        "load_bins": [x[2] for x in CORRIDOR_LOAD_BINS],
    }


def _corridor_residence_for(
    residence_bundle: Optional[dict],
    station_id: str,
    variant: str,
    active_count: int,
    fallback_models: dict,
    *,
    is_first_station: bool = False,
) -> tuple[Optional[DwellDistribution], float, str]:
    sid, var = str(station_id), str(variant)
    active_count = max(0, int(active_count))
    label = _corridor_load_bin(active_count)
    if residence_bundle:
        if is_first_station:
            local = residence_bundle.get("first_station_local", {})
            local_meta = residence_bundle.get("first_station_local_meta", {})
            for variant_key, base_quality in ((var, 0.97), ("__ALL__", 0.92)):
                available = [
                    key for key in local
                    if key[0] == sid and key[1] == variant_key
                ]
                if available:
                    chosen = min(available, key=lambda key: abs(int(key[2]) - active_count))
                    model = local[chosen]
                    info = local_meta.get("|".join(map(str, chosen)), {})
                    radius = int(info.get("radius", 0))
                    sample_factor = min(1.0, max(0.55, float(model.n_samples) / 80.0))
                    locality_factor = 1.0 / (1.0 + 0.08 * radius)
                    source = (
                        f"first_station_local_load:{active_count}->"
                        f"{int(chosen[2])}:r{radius}"
                    )
                    return model, base_quality * sample_factor * locality_factor, source

        conditional = residence_bundle.get("conditional", {})
        unconditional = residence_bundle.get("unconditional", {})
        candidates = [
            ((sid, var, label), 0.95, f"load_conditioned_variant:{label}"),
            ((sid, "__ALL__", label), 0.88, f"load_conditioned_station:{label}"),
        ]
        for key, base_quality, source in candidates:
            model = conditional.get(key)
            if model is not None:
                sample_factor = min(1.0, max(0.45, float(model.n_samples) / 80.0))
                return model, base_quality * sample_factor, source
        for key, base_quality, source in [
            ((sid, var), 0.68, "unconditional_residence_variant"),
            ((sid, "__ALL__"), 0.60, "unconditional_residence_station"),
        ]:
            model = unconditional.get(key)
            if model is not None:
                sample_factor = min(1.0, max(0.45, float(model.n_samples) / 80.0))
                return model, base_quality * sample_factor, source
    model = _model_for(fallback_models, sid, var)
    return model, 0.42, "processing_dwell_fallback"

def _model_for(models: dict, station_id: str, variant: Optional[str]):
    return (
        models.get((str(station_id), str(variant)))
        or models.get((str(station_id), "__ALL__"))
        or models.get(("__GLOBAL__", "__ALL__"))
    )


def _prune_deque(dq: deque, cutoff_ms: int, key: str = "timestamp_ms") -> None:
    while dq and int(dq[0][key] if isinstance(dq[0], dict) else dq[0]) < cutoff_ms:
        dq.popleft()


@dataclass
class StationRuntime:
    current_queue: float = 0.0
    occupancy_std: float = 0.0
    state_confidence: float = 1.0
    uncertainty_source: str = "causal_queue_ledger"
    has_unit_arrived_signal: bool = False
    queue_history: deque = field(default_factory=deque)
    arrival_times_ms: deque = field(default_factory=deque)
    service_times_ms: deque = field(default_factory=deque)
    cycle_history: deque = field(default_factory=deque)
    queue_source: str = "active_registry_fallback"
    arrival_source: str = "processing_start_proxy"

    def prune(self, now_ms: int):
        cutoff = now_ms - 2 * RECENT_MS - 1
        _prune_deque(self.queue_history, cutoff)
        while self.arrival_times_ms and int(self.arrival_times_ms[0]) < cutoff:
            self.arrival_times_ms.popleft()
        while self.service_times_ms and int(self.service_times_ms[0]) < cutoff:
            self.service_times_ms.popleft()
        _prune_deque(self.cycle_history, cutoff)

    def view(self) -> StationFeatureState:
        return StationFeatureState(
            current_occupancy=float(max(self.current_queue, 0.0)),
            queue_history=list(self.queue_history),
            arrival_times_ms=list(self.arrival_times_ms),
            service_times_ms=list(self.service_times_ms),
            cycle_history=list(self.cycle_history),
            occupancy_std=float(self.occupancy_std),
            state_confidence=float(self.state_confidence),
            uncertainty_source=self.uncertainty_source,
            queue_source=self.queue_source,
            arrival_source=self.arrival_source,
            cycle_source="observed_processing_completed",
        )


class OutputCollector:
    def __init__(self):
        self.ml_rows: list[dict] = []
        self.dashboard_rows: list[dict] = []
        self.provenance_rows: list[dict] = []

    def add(self, result: dict, run_id: str, vehicle_id: str, prediction_time, trigger: str):
        row = {
            "run_id": run_id,
            "vehicle_id": vehicle_id,
            "prediction_time": pd.to_datetime(prediction_time, utc=True),
            "trigger": trigger,
            **result["features_28"],
        }
        self.ml_rows.append(row)
        dash = dict(result["dashboard"])
        dash["trigger"] = trigger
        self.dashboard_rows.append(dash)
        for feature in FEATURES_28:
            self.provenance_rows.append({
                "run_id": run_id,
                "vehicle_id": vehicle_id,
                "prediction_time": pd.to_datetime(prediction_time, utc=True),
                "feature": feature,
                "source": result["provenance"].get(feature, "unknown"),
            })


# ---------------------------------------------------------------------------
# Single-station bridge: FULL reuse of DarkZoneOrchestrator
# ---------------------------------------------------------------------------


class SingleStationMLBridge:
    """Thin observer/feature adapter around an existing DarkZoneOrchestrator."""

    def __init__(
        self,
        orchestrator: DarkZoneOrchestrator,
        stations: pd.DataFrame,
        dwell_models: dict,
        run_id: str,
        unit_arrived_stations: Optional[set[str]] = None,
        cycle_lookup: Optional[dict[tuple[str, str, int], float]] = None,
        collector: Optional[OutputCollector] = None,
    ):
        self.orch = orchestrator
        self.recon = DarkZoneFeatureReconstructor(stations)
        self.models = dwell_models
        self.run_id = run_id
        self.station_state: dict[str, StationRuntime] = defaultdict(StationRuntime)
        self.unit_arrived_stations = set(unit_arrived_stations or set())
        self.cycle_lookup = cycle_lookup or {}
        self.collector = collector or OutputCollector()
        self.routed_counts = defaultdict(int)
        self.evidence_routed = 0

    def observe_unit_arrived(self, station_id: str, ts_ms: int):
        sid = str(station_id)
        st = self.station_state[sid]
        st.has_unit_arrived_signal = True
        st.queue_source = "causal_queue_ledger_from_unit_arrived_and_processing_start"
        st.arrival_source = "observed_UNIT_ARRIVED"
        st.current_queue += 1.0
        st.occupancy_std = 0.0
        st.state_confidence = 1.0
        st.uncertainty_source = "causal_queue_ledger"
        st.arrival_times_ms.append(int(ts_ms))
        st.queue_history.append({"timestamp_ms": int(ts_ms), "queue": float(st.current_queue)})
        st.prune(int(ts_ms))

    def _fallback_queue_from_registry(self, station_id: str) -> float:
        active_here = sum(1 for m in self.orch.meta.values() if str(m.get("station")) == str(station_id))
        return float(max(active_here - 1, 0))

    def _mark_registry_fallback_uncertainty(self, st: StationRuntime):
        # Without UNIT_ARRIVED there is no defensible exact waiting-queue ledger.
        # Keep the engine state untouched, expose the queue estimate as uncertain,
        # and let XGBoost see that uncertainty instead of silently claiming precision.
        st.occupancy_std = max(1.0, float(np.sqrt(max(st.current_queue, 0.0) + 1.0)))
        st.state_confidence = float(np.exp(-st.occupancy_std))
        st.uncertainty_source = "active_registry_queue_fallback"

    def observe_engine_event(self, ev: DarkZoneEvent, emit=True):
        """Route the event THROUGH the existing orchestrator, then update only feature bookkeeping."""
        sid = str(ev.station_id)
        vid = str(ev.vehicle_id)
        ts_ms = _ms(ev.ts)
        st = self.station_state[sid]
        st.has_unit_arrived_signal = sid in self.unit_arrived_stations or st.has_unit_arrived_signal
        if st.has_unit_arrived_signal:
            st.queue_source = "causal_queue_ledger_from_unit_arrived_and_processing_start"
            st.arrival_source = "observed_UNIT_ARRIVED"

        self.routed_counts[ev.event_type.value] += 1
        if ev.event_type in {EventType.RFID_CHECKPOINT, EventType.POWER_DRAW, EventType.ANDON_SCAN}:
            self.evidence_routed += 1

        if ev.event_type == EventType.STATION_ENTRY:
            self.orch.route_event(ev)
            if vid not in self.orch.active:
                return
            if st.has_unit_arrived_signal:
                st.current_queue = max(st.current_queue - 1.0, 0.0)
                st.occupancy_std = 0.0
                st.state_confidence = 1.0
                st.uncertainty_source = "causal_queue_ledger"
            else:
                st.current_queue = self._fallback_queue_from_registry(sid)
                self._mark_registry_fallback_uncertainty(st)
                st.arrival_times_ms.append(ts_ms)  # only if UNIT_ARRIVED is unavailable
            st.queue_history.append({"timestamp_ms": ts_ms, "queue": st.current_queue})
            st.prune(ts_ms)
            if emit:
                self.emit_active(vid, ev.ts, trigger="station_entry")
            return

        if ev.event_type == EventType.STATION_EXIT:
            # Keep references before teardown. route_event advances this same PF object to ev.ts.
            pf = self.orch.active.get(vid)
            meta = dict(self.orch.meta.get(vid, {}))
            self.orch.route_event(ev)
            if pf is None:
                return
            st.service_times_ms.append(ts_ms)
            if st.has_unit_arrived_signal:
                # Queue length does not increase merely because the server completes.
                st.occupancy_std = 0.0
                st.state_confidence = 1.0
                st.uncertainty_source = "causal_queue_ledger"
            else:
                st.current_queue = self._fallback_queue_from_registry(sid)
                self._mark_registry_fallback_uncertainty(st)
            st.queue_history.append({"timestamp_ms": ts_ms, "queue": st.current_queue})

            raw_cycle = self.cycle_lookup.get((vid, sid, ts_ms))
            if raw_cycle is None or not np.isfinite(raw_cycle):
                entry = meta.get("entry_ts")
                raw_cycle = (ev.ts - float(entry)) * 1000.0 if entry is not None else np.nan
            if np.isfinite(raw_cycle):
                st.cycle_history.append({"timestamp_ms": ts_ms, "cycle_time_ms": float(raw_cycle)})
            st.prune(ts_ms)
            if emit:
                self.emit_with_pf(
                    vehicle_id=vid,
                    station_id=sid,
                    variant=meta.get("variant"),
                    pf=pf,
                    ts_seconds=ev.ts,
                    trigger="station_exit",
                )
            return

        # Evidence / tick: state mutation happens only inside the orchestrator.
        self.orch.route_event(ev)
        if emit and vid in self.orch.active and ev.event_type != EventType.TICK:
            self.emit_active(vid, ev.ts, trigger=ev.event_type.value)

    def apply_anonymous_power_draw(
        self, station_id: str, progress: float, ts_s: float, sensor_std: float = 0.12
    ) -> None:
        """Apply one non-identifying power observation to the active population.

        A CT/power sensor observes that *some* unit caused activity but does not
        identify which one.  We use a lightweight JPDA-style association: each
        active track receives only its posterior association probability, not a
        full-strength duplicate observation.
        """
        sid = str(station_id)
        vids = [
            str(vid) for vid, meta in self.orch.meta.items()
            if str(meta.get("station")) == sid and vid in self.orch.active
        ]
        if not vids:
            return

        scores: list[float] = []
        likelihoods: list[np.ndarray] = []
        for vid in vids:
            pf = self.orch.active[vid]
            dt = max(0.0, float(ts_s) - self.orch.last_event_ts.get(vid, float(ts_s)))
            if dt > 0:
                pf.predict(dt)
            self.orch.last_event_ts[vid] = float(ts_s)
            lik = power_draw_likelihood(float(progress), sensor_std=float(sensor_std))(pf.progress)
            likelihoods.append(np.asarray(lik, dtype=float))
            scores.append(float(np.average(lik, weights=pf.weights)))

        total = float(sum(scores))
        if not np.isfinite(total) or total <= 0:
            return
        for vid, lik, score in zip(vids, likelihoods, scores):
            pf = self.orch.active[vid]
            beta = float(score / total)
            norm = max(float(score), 1e-300)
            # Mixture update: with probability beta this track generated the
            # observation; otherwise its state is unchanged. Expected factor=1.
            tempered = (1.0 - beta) + beta * (lik / norm)
            pf.update(lambda _progress, values=tempered: values)
            self.orch._persist(vid)

        self.evidence_routed += 1
        for vid in vids:
            if vid in self.orch.active:
                self.emit_active(vid, float(ts_s), trigger="power_draw_population")

    def emit_active(self, vehicle_id: str, ts_seconds: float, trigger="interval"):
        vid = str(vehicle_id)
        if vid not in self.orch.active:
            return
        m = self.orch.meta[vid]
        self.emit_with_pf(
            vehicle_id=vid,
            station_id=str(m["station"]),
            variant=m.get("variant"),
            pf=self.orch.active[vid],
            ts_seconds=ts_seconds,
            trigger=trigger,
        )

    def emit_with_pf(self, vehicle_id, station_id, variant, pf, ts_seconds, trigger):
        sid = str(station_id)
        now_ms = _ms(ts_seconds)
        st = self.station_state[sid]
        st.prune(now_ms)
        ctx = PredictionContext(
            run_id=self.run_id,
            vehicle_id=str(vehicle_id),
            prediction_time=pd.to_datetime(ts_seconds, unit="s", utc=True),
            station_id=sid,
            variant=variant,
            zone_type="single_station",
        )
        result = self.recon.reconstruct_single(
            ctx=ctx,
            pf=pf,
            station_state=st.view(),
            dwell_model=_model_for(self.models, sid, variant),
            dark_zone_id=sid,
        )
        self.collector.add(result, self.run_id, str(vehicle_id), ctx.prediction_time, trigger)

    def tick_and_emit(self, vehicle_id: str, ts_seconds: float):
        vid = str(vehicle_id)
        if vid not in self.orch.active:
            return
        sid = str(self.orch.meta[vid]["station"])
        self.orch.route_event(DarkZoneEvent(
            event_type=EventType.TICK,
            vehicle_id=vid,
            station_id=sid,
            ts=float(ts_seconds),
            variant=self.orch.meta[vid].get("variant"),
        ))
        if vid in self.orch.active:
            self.emit_active(vid, ts_seconds, trigger="interval")


# ---------------------------------------------------------------------------
# Corridor bridge: reuse existing MultiStationParticleFilter unchanged
# ---------------------------------------------------------------------------


@dataclass
class ZoneSpec:
    zone_id: str
    sequence: list[str]
    entry_station: str
    downstream_exit_station: str


@dataclass
class CorridorState:
    mpf: MultiStationParticleFilter
    zone: ZoneSpec
    variant: str
    entry_ts_s: float
    last_ts_s: float
    entry_load: int = 0
    calibration_quality: float = 0.42
    calibration_source: str = "processing_dwell_fallback"


@dataclass
class CorridorArchive:
    zone_id: str
    entry_ts_s: float
    exit_ts_s: float
    cum_T: np.ndarray
    T: np.ndarray
    weights: np.ndarray


def detect_corridor_zones(stations: pd.DataFrame, station_events: pd.DataFrame) -> dict[str, ZoneSpec]:
    if "dark_zone_id" not in station_events.columns:
        return {}
    markers = station_events[station_events["event_type"].isin(["DARK_ZONE_ENTERED", "DARK_ZONE_EXITED"])].copy()
    if markers.empty or markers["dark_zone_id"].isna().all():
        return {}
    order = list(stations["station_id"].astype(str))
    pos = {sid: i for i, sid in enumerate(order)}
    out = {}
    for zid in markers["dark_zone_id"].dropna().astype(str).unique():
        z = markers[markers["dark_zone_id"].astype(str) == zid]
        ent = z[z["event_type"] == "DARK_ZONE_ENTERED"]
        ext = z[z["event_type"] == "DARK_ZONE_EXITED"]
        if ent.empty or ext.empty:
            continue
        a = str(ent.iloc[0]["station_id"])
        d = str(ext.iloc[0]["station_id"])
        if a not in pos or d not in pos or pos[a] >= pos[d]:
            raise ValueError(f"Invalid dark corridor {zid}: {a} -> {d}")
        out[zid] = ZoneSpec(zid, order[pos[a]:pos[d]], a, d)
    return out


class CorridorMLBridge:
    def __init__(self, stations, models, units, zones, run_id, collector, n_particles=3000, residence_bundle=None, rng_seed=None):
        self.stations = stations
        self.models = models
        self.units = units
        self.zones = zones
        self.run_id = run_id
        self.collector = collector
        self.recon = DarkZoneFeatureReconstructor(stations)
        self.n_particles = n_particles
        self.residence_bundle = residence_bundle
        self.rng_seed = None if rng_seed is None else int(rng_seed)
        self.active: dict[str, CorridorState] = {}
        self.archives: list[CorridorArchive] = []
        self.station_state: dict[str, StationRuntime] = defaultdict(StationRuntime)
        self.evidence_applied = 0
        self.evidence_skipped = 0
        self.boundary_counts = defaultdict(int)
        self.calibration_source_counts = defaultdict(int)

        # Corridor snapshots are queried repeatedly at the same timestamp:
        # record_zone_queue() visits every station, and emit() then asks for the
        # same station moments again for each vehicle tick. Cache only derived
        # read-only quantities; every PF mutation invalidates the cache.
        self._queue_snapshot_cache: dict[str, dict[str, tuple[float, float, float]]] = {}
        self._rate_counts_cache: dict[tuple[str, str, float], dict] = {}

    def _invalidate_zone_cache(self, zone_id: str) -> None:
        self._queue_snapshot_cache.pop(str(zone_id), None)
        zid = str(zone_id)
        if self._rate_counts_cache:
            self._rate_counts_cache = {
                k: v for k, v in self._rate_counts_cache.items() if k[0] != zid
            }

    def _advance(self, state: CorridorState, ts_s: float) -> bool:
        dt = max(0.0, float(ts_s) - float(state.last_ts_s))
        if dt > 0:
            state.mpf.predict(dt)
            state.last_ts_s = float(ts_s)
            return True
        return False

    def _advance_zone(self, zone_id: str, ts_s: float):
        # Queue/rate reconstruction is a line-level snapshot, so every active
        # vehicle belief in this corridor must be at the same causal timestamp.
        changed = False
        for s in self._active_for_zone(zone_id):
            changed = self._advance(s, ts_s) or changed
        if changed:
            self._invalidate_zone_cache(zone_id)

    def enter(self, vehicle_id: str, zone_id: str, ts_s: float):
        zone = self.zones[zone_id]
        self._advance_zone(zone_id, ts_s)
        variant = str(self.units.get(str(vehicle_id), "__UNKNOWN__"))
        # Causal load context: number of not-yet-exited vehicles already inside
        # the corridor at this entry boundary. This is observable without any
        # internal Light-Zone sensor and is strongly predictive of queue residence.
        entry_load = len(self._active_for_zone(zone_id))
        dists = {}
        qualities = []
        sources = []
        for sid in zone.sequence:
            dm, q, src = _corridor_residence_for(
                self.residence_bundle,
                sid,
                variant,
                entry_load,
                self.models,
                is_first_station=(sid == zone.sequence[0]),
            )
            if dm is None:
                raise ValueError(f"No dwell/residence prior available for corridor {zone_id}, station {sid}")
            dists[sid] = dm
            qualities.append(float(q))
            sources.append(src)
        rng = None
        if self.rng_seed is not None:
            payload = f"{self.rng_seed}|{self.run_id}|corridor|{zone_id}|{vehicle_id}|{float(ts_s):.9f}"
            derived = int.from_bytes(
                hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest(), "big"
            )
            rng = np.random.default_rng(derived)
        mpf = MultiStationParticleFilter(
            zone.sequence,
            dists,
            config=MultiStationConfig(n_particles=self.n_particles),
            rng=rng,
        )
        quality = float(min(qualities)) if qualities else 0.42
        source = ";".join(sorted(set(sources)))
        self.calibration_source_counts[source] += 1
        self.active[str(vehicle_id)] = CorridorState(
            mpf, zone, variant, float(ts_s), float(ts_s),
            entry_load=int(entry_load), calibration_quality=quality, calibration_source=source,
        )
        self._invalidate_zone_cache(zone_id)
        self.boundary_counts["entered"] += 1
        self.record_zone_queue(zone_id, ts_s)
        self.emit(str(vehicle_id), ts_s, trigger="corridor_entry")

    def exit(self, vehicle_id: str, zone_id: str, ts_s: float):
        vid = str(vehicle_id)
        state = self.active.get(vid)
        if state is None:
            return
        self._advance_zone(state.zone.zone_id, ts_s)
        # Emit while the vehicle is still active; archive only afterwards so
        # current-window rate counts cannot double-count this vehicle.
        self.emit(vid, ts_s, trigger="corridor_exit")
        self.archives.append(CorridorArchive(
            zone_id=state.zone.zone_id,
            entry_ts_s=state.entry_ts_s,
            exit_ts_s=float(ts_s),
            cum_T=state.mpf.cum_T.copy(),
            T=state.mpf.T.copy(),
            weights=state.mpf.weights.copy(),
        ))
        del self.active[vid]
        self._invalidate_zone_cache(zone_id)
        self.boundary_counts["exited"] += 1
        self.record_zone_queue(zone_id, ts_s)
        self._prune_archives(ts_s)

    def apply_checkpoint(self, vehicle_id: str, station_id: str, progress: float, ts_s: float, sensor_std: float):
        vid = str(vehicle_id)
        state = self.active.get(vid)
        if state is None or str(station_id) not in state.zone.sequence:
            self.evidence_skipped += 1
            return
        self._advance_zone(state.zone.zone_id, ts_s)
        state.mpf.update_checkpoint(str(station_id), float(progress), sensor_std=float(sensor_std))
        self._invalidate_zone_cache(state.zone.zone_id)
        self.evidence_applied += 1
        self.record_zone_queue(state.zone.zone_id, ts_s)
        self.emit(vid, ts_s, trigger="corridor_checkpoint")

    def apply_anonymous_checkpoint(
        self, station_id: str, progress: float, ts_s: float, sensor_std: float = 0.12
    ) -> None:
        """Softly associate a non-identifying checkpoint with active corridor tracks.

        The event means activity occurred near a physical station/progress, but
        not which unit caused it.  Association probabilities are derived from
        each track's current evidence likelihood, avoiding the incorrect choice
        of applying the same full-strength observation independently to every unit.
        """
        sid = str(station_id)
        zone_ids = [zid for zid, zone in self.zones.items() if sid in zone.sequence]
        if not zone_ids:
            self.evidence_skipped += 1
            return
        zid = zone_ids[0]
        states = self._active_for_zone(zid)
        if not states:
            self.evidence_skipped += 1
            return
        self._advance_zone(zid, float(ts_s))

        likelihoods: list[np.ndarray] = []
        scores: list[float] = []
        for state in states:
            lik = state.mpf.checkpoint_likelihood_values(
                sid, float(progress), sensor_std=float(sensor_std)
            )
            likelihoods.append(lik)
            scores.append(float(np.average(lik, weights=state.mpf.weights)))

        total = float(sum(scores))
        if not np.isfinite(total) or total <= 0:
            self.evidence_skipped += 1
            return
        for state, lik, score in zip(states, likelihoods, scores):
            beta = float(score / total)
            norm = max(float(score), 1e-300)
            tempered = (1.0 - beta) + beta * (lik / norm)
            state.mpf.update_likelihood_values(tempered)

        self._invalidate_zone_cache(zid)
        self.evidence_applied += 1
        self.record_zone_queue(zid, float(ts_s))
        for vid, state in list(self.active.items()):
            if state.zone.zone_id == zid:
                self.emit(vid, float(ts_s), trigger="corridor_power_draw_population")

    def apply_anonymous_station_evidence(
        self,
        station_id: str,
        ts_s: float,
        wrong_station_floor: float = 0.05,
    ) -> dict[str, float]:
        """Condition corridor tracks on anonymous station-local activity.

        SENSOR telemetry reveals the physical station at which activity was
        observed, but not the unit identity or progress.  We therefore perform
        the same JPDA-style population association used for anonymous power
        evidence, using only station identity likelihood.  The returned mapping
        is the posterior association probability for each active vehicle and is
        intended for other causal consumers (for example defect telemetry
        attribution).
        """
        sid = str(station_id)
        zone_ids = [zid for zid, zone in self.zones.items() if sid in zone.sequence]
        if not zone_ids:
            self.evidence_skipped += 1
            return {}
        zid = zone_ids[0]
        states = self._active_for_zone(zid)
        if not states:
            self.evidence_skipped += 1
            return {}
        self._advance_zone(zid, float(ts_s))

        likelihoods: list[np.ndarray] = []
        scores: list[float] = []
        vids: list[str] = []
        for vid, state in self.active.items():
            if state.zone.zone_id != zid:
                continue
            particle_station, _ = state.mpf._current_station_and_progress()
            target_idx = state.mpf.station_sequence.index(sid)
            lik = np.where(
                particle_station == target_idx,
                1.0,
                float(wrong_station_floor),
            )
            likelihoods.append(lik)
            scores.append(float(np.average(lik, weights=state.mpf.weights)))
            vids.append(str(vid))

        total = float(sum(scores))
        if not np.isfinite(total) or total <= 0:
            self.evidence_skipped += 1
            return {}

        association = {vid: float(score / total) for vid, score in zip(vids, scores)}
        for vid, lik, score in zip(vids, likelihoods, scores):
            state = self.active[vid]
            beta = association[vid]
            norm = max(float(score), 1e-300)
            tempered = (1.0 - beta) + beta * (lik / norm)
            state.mpf.update_likelihood_values(tempered)

        self._invalidate_zone_cache(zid)
        self.evidence_applied += 1
        self.record_zone_queue(zid, float(ts_s))
        for vid in vids:
            if vid in self.active:
                self.emit(vid, float(ts_s), trigger="corridor_sensor_population")
        return association

    def tick(self, vehicle_id: str, ts_s: float):
        vid = str(vehicle_id)
        state = self.active.get(vid)
        if state is None:
            return
        self._advance_zone(state.zone.zone_id, ts_s)
        self.record_zone_queue(state.zone.zone_id, ts_s)
        self.emit(vid, ts_s, trigger="interval")

    def _active_for_zone(self, zone_id: str) -> list[CorridorState]:
        return [s for s in self.active.values() if s.zone.zone_id == zone_id]

    def _zone_queue_snapshot(self, zone_id: str) -> dict[str, tuple[float, float, float]]:
        """Compute all station queue moments once for the current corridor state.

        This preserves the original Poisson-binomial queue mathematics exactly,
        but avoids recomputing each vehicle's particle->station assignment once
        per station and again during emit().
        """
        zid = str(zone_id)
        cached = self._queue_snapshot_cache.get(zid)
        if cached is not None:
            return cached

        states = self._active_for_zone(zid)
        zone = self.zones[zid]
        if not states:
            snapshot = {sid: (0.0, 0.0, 1.0) for sid in zone.sequence}
            self._queue_snapshot_cache[zid] = snapshot
            return snapshot

        # Compute each vehicle's particle station assignment once. The MPF itself
        # also caches this projection for repeated estimate/render calls.
        per_station_probs = [[] for _ in zone.sequence]
        for s in states:
            k, _ = s.mpf._current_station_and_progress()
            for idx in range(len(zone.sequence)):
                p = float(np.clip(s.mpf.weights[k == idx].sum(), 0.0, 1.0))
                per_station_probs[idx].append(p)

        calibration_quality = min(float(s.calibration_quality) for s in states)
        snapshot = {}
        for idx, sid in enumerate(zone.sequence):
            # Keep the same Bernoulli convolution and the same vehicle order as
            # the original implementation so queue semantics remain unchanged.
            dist = np.array([1.0])
            for p in per_station_probs[idx]:
                dist = np.convolve(dist, np.array([1.0 - p, p]))
            n = np.arange(len(dist), dtype=float)
            q = np.maximum(n - 1.0, 0.0)
            mean = float(np.sum(dist * q))
            var = float(np.sum(dist * (q - mean) ** 2))
            std = float(np.sqrt(max(var, 0.0)))
            confidence = float(np.exp(-std) * calibration_quality)
            snapshot[str(sid)] = (mean, std, confidence)

        self._queue_snapshot_cache[zid] = snapshot
        return snapshot

    def _queue_moments_for_station(self, zone_id: str, station_id: str) -> tuple[float, float, float]:
        return self._zone_queue_snapshot(zone_id)[str(station_id)]

    def _queue_for_station(self, zone_id: str, station_id: str) -> float:
        return self._queue_moments_for_station(zone_id, station_id)[0]

    def record_zone_queue(self, zone_id: str, ts_s: float):
        zone = self.zones[zone_id]
        ts_ms = _ms(ts_s)
        snapshot = self._zone_queue_snapshot(zone_id)
        for sid in zone.sequence:
            st = self.station_state[sid]
            mean, std, confidence = snapshot[str(sid)]
            st.current_queue = mean
            st.occupancy_std = std
            st.state_confidence = confidence
            st.uncertainty_source = "corridor_queue_poisson_binomial_posterior"
            st.queue_source = "corridor_posterior_expected_queue"
            # One reconstructed line-state observation per station/timestamp. If
            # evidence at the same timestamp sharpens the posterior, replace it.
            if st.queue_history and int(st.queue_history[-1]["timestamp_ms"]) == ts_ms:
                st.queue_history[-1] = {"timestamp_ms": ts_ms, "queue": st.current_queue}
            else:
                st.queue_history.append({"timestamp_ms": ts_ms, "queue": st.current_queue})
            st.prune(ts_ms)

    def _records_for_zone(self, zone_id: str):
        for s in self._active_for_zone(zone_id):
            yield (s.entry_ts_s, s.mpf.cum_T, s.mpf.T, s.mpf.weights)
        for a in self.archives:
            if a.zone_id == zone_id:
                yield (a.entry_ts_s, a.cum_T, a.T, a.weights)

    def expected_rate_counts(self, zone_id: str, station_id: str, as_of_s: float) -> dict:
        zid = str(zone_id)
        sid = str(station_id)
        t = float(as_of_s)
        cache_key = (zid, sid, t)
        cached = self._rate_counts_cache.get(cache_key)
        if cached is not None:
            return cached

        zone = self.zones[zid]
        idx = zone.sequence.index(sid)
        lo10, lo20 = t - 600.0, t - 1200.0
        a10 = ap = s10 = sp = 0.0
        for entry_s, cum_T, _T, weights in self._records_for_zone(zone_id):
            w = np.asarray(weights, dtype=float)
            if idx == 0:
                ent = np.full(len(w), float(entry_s))
            else:
                ent = float(entry_s) + np.asarray(cum_T[:, idx - 1], dtype=float)
            ext = float(entry_s) + np.asarray(cum_T[:, idx], dtype=float)
            a10 += float(w[(ent >= lo10) & (ent <= t)].sum())
            ap += float(w[(ent >= lo20) & (ent < lo10)].sum())
            s10 += float(w[(ext >= lo10) & (ext <= t)].sum())
            sp += float(w[(ext >= lo20) & (ext < lo10)].sum())
        result = {"arrivals10": a10, "arrivals_prev": ap, "services10": s10, "services_prev": sp}
        self._rate_counts_cache[cache_key] = result
        return result

    def emit(self, vehicle_id: str, ts_s: float, trigger: str):
        vid = str(vehicle_id)
        state = self.active.get(vid)
        if state is None:
            return
        est = state.mpf.estimate()
        sid = str(est["most_likely_station"])
        st = self.station_state[sid]
        mean, std, confidence = self._queue_moments_for_station(state.zone.zone_id, sid)
        st.current_queue = mean
        st.occupancy_std = std
        st.state_confidence = confidence
        st.uncertainty_source = "corridor_queue_poisson_binomial_posterior"
        st.queue_source = "corridor_posterior_expected_queue"
        st.arrival_source = "corridor_posterior_station_crossings"
        ctx = PredictionContext(
            run_id=self.run_id,
            vehicle_id=vid,
            prediction_time=pd.to_datetime(ts_s, unit="s", utc=True),
            station_id=sid,
            variant=state.variant,
            zone_type="corridor",
        )
        result = self.recon.reconstruct_corridor(
            ctx=ctx,
            mpf=state.mpf,
            station_state=st.view(),
            rate_counts=self.expected_rate_counts(state.zone.zone_id, sid, ts_s),
            dwell_model=_model_for(self.models, sid, state.variant),
            dark_zone_id=state.zone.zone_id,
        )
        result["dashboard"].update({
            "corridor_entry_load": int(state.entry_load),
            "corridor_calibration_quality": float(state.calibration_quality),
            "corridor_calibration_source": state.calibration_source,
        })
        self.collector.add(result, self.run_id, vid, ctx.prediction_time, trigger)

    def _prune_archives(self, now_s: float):
        # A completed vehicle older than 20m cannot contribute to any current/previous rate window.
        cutoff = float(now_s) - 1200.0
        self.archives = [a for a in self.archives if a.exit_ts_s >= cutoff]


# ---------------------------------------------------------------------------
# Offline replay harness
# ---------------------------------------------------------------------------


def _build_cycle_lookup(raw_events: pd.DataFrame) -> dict[tuple[str, str, int], float]:
    if "cycle_time_ms" not in raw_events.columns:
        return {}
    x = raw_events[raw_events["event_type"].astype(str).eq("PROCESSING_COMPLETED")].copy()
    x["cycle_time_ms"] = pd.to_numeric(x["cycle_time_ms"], errors="coerce")
    out = {}
    for r in x.itertuples(index=False):
        if pd.notna(r.cycle_time_ms):
            out[(str(r.unit_id), str(r.station_id), int(r.timestamp_ms))] = float(r.cycle_time_ms)
    return out


def _single_dark_station_ids(stations: pd.DataFrame, raw_events: pd.DataFrame) -> set[str]:
    if "sensor_coverage" in stations.columns:
        nominal = set(stations.loc[stations["sensor_coverage"].astype(str).eq("NONE"), "station_id"].astype(str))
    else:
        nominal = set(stations["station_id"].astype(str))
    proc = raw_events[raw_events["event_type"].isin(["PROCESSING_STARTED", "PROCESSING_COMPLETED"])]
    has_proc = set(proc["station_id"].astype(str))
    return nominal & has_proc


def _corridor_evidence_events(
    checkpoint_events_csv: Optional[str],
    station_checkpoints_csv: Optional[str],
    manual_checks_csv: Optional[str],
    zones: dict[str, ZoneSpec],
) -> list[dict]:
    if not zones:
        return []
    station_to_zone = {}
    for zid, z in zones.items():
        for sid in z.sequence:
            station_to_zone[sid] = zid
    out = []
    if checkpoint_events_csv and station_checkpoints_csv:
        ce = pd.read_csv(checkpoint_events_csv)
        progress = load_checkpoint_progress_map(station_checkpoints_csv)
        for r in ce.itertuples(index=False):
            sid = str(r.station_id)
            if sid not in station_to_zone:
                continue
            p = progress.get((sid, r.checkpoint_id))
            if p is None:
                continue
            typ = str(r.event_type).upper()
            std = 0.12 if typ == "POWER_DRAW" else 0.05
            out.append({
                "ts_s": float(r.timestamp_ms) / 1000.0,
                "vehicle_id": str(r.unit_id),
                "station_id": sid,
                "zone_id": station_to_zone[sid],
                "progress": float(p),
                "sensor_std": std,
                "kind": typ,
            })
    if manual_checks_csv:
        mc = pd.read_csv(manual_checks_csv)
        for r in mc.itertuples(index=False):
            sid = str(r.station_id)
            if sid not in station_to_zone:
                continue
            out.append({
                "ts_s": float(r.timestamp_ms) / 1000.0,
                "vehicle_id": str(r.unit_id),
                "station_id": sid,
                "zone_id": station_to_zone[sid],
                "progress": 1.0,
                "sensor_std": 0.03,
                "kind": "ANDON_SCAN",
            })
    return sorted(out, key=lambda x: x["ts_s"])


def _run_single_replay(
    bridge: SingleStationMLBridge,
    raw_events: pd.DataFrame,
    engine_events: list[DarkZoneEvent],
    single_ids: set[str],
    prediction_interval_s: float,
):
    # Feature-only UNIT_ARRIVED events are not routed into the engine, by design.
    arrivals = raw_events[
        raw_events["event_type"].astype(str).eq("UNIT_ARRIVED")
        & raw_events["station_id"].astype(str).isin(single_ids)
    ]
    timeline = []
    seq = 0
    for r in arrivals.itertuples(index=False):
        timeline.append((float(r.timestamp_ms) / 1000.0, 0, seq, "arrival", r)); seq += 1
    priority = {
        EventType.STATION_ENTRY: 1,
        EventType.RFID_CHECKPOINT: 2,
        EventType.POWER_DRAW: 2,
        EventType.ANDON_SCAN: 2,
        EventType.TICK: 3,
        EventType.STATION_EXIT: 4,
    }
    for ev in engine_events:
        timeline.append((float(ev.ts), priority.get(ev.event_type, 2), seq, "engine", ev)); seq += 1
    timeline.sort(key=lambda z: (z[0], z[1], z[2]))

    next_tick: dict[str, float] = {}
    tick_heap = []

    def push_tick(vid, t):
        next_tick[vid] = float(t)
        heapq.heappush(tick_heap, (float(t), vid))

    def process_ticks_before(limit_s: float, strict=True):
        cmp = (lambda t: t < limit_s) if strict else (lambda t: t <= limit_s)
        while tick_heap and cmp(tick_heap[0][0]):
            t, vid = heapq.heappop(tick_heap)
            if next_tick.get(vid) != t:
                continue
            if vid not in bridge.orch.active:
                next_tick.pop(vid, None)
                continue
            bridge.tick_and_emit(vid, t)
            nt = t + prediction_interval_s
            push_tick(vid, nt)

    i = 0
    while i < len(timeline):
        t = timeline[i][0]
        process_ticks_before(t, strict=True)
        same = []
        while i < len(timeline) and timeline[i][0] == t:
            same.append(timeline[i]); i += 1

        # arrivals -> entries/evidence -> exact-time ticks -> exits
        for _, pr, _, kind, obj in same:
            if kind == "arrival":
                bridge.observe_unit_arrived(str(obj.station_id), int(obj.timestamp_ms))
            elif kind == "engine" and obj.event_type != EventType.STATION_EXIT:
                was_entry = obj.event_type == EventType.STATION_ENTRY
                bridge.observe_engine_event(obj, emit=True)
                if was_entry and str(obj.vehicle_id) in bridge.orch.active:
                    push_tick(str(obj.vehicle_id), float(t) + prediction_interval_s)

        process_ticks_before(t, strict=False)

        for _, _, _, kind, obj in same:
            if kind == "engine" and obj.event_type == EventType.STATION_EXIT:
                bridge.observe_engine_event(obj, emit=True)
                next_tick.pop(str(obj.vehicle_id), None)

    # No synthetic predictions past the last observed input event; avoids fabricating future time.


def _run_corridor_replay(
    bridge: CorridorMLBridge,
    raw_events: pd.DataFrame,
    evidence: list[dict],
    prediction_interval_s: float,
):
    timeline = []
    seq = 0
    markers = raw_events[raw_events["event_type"].isin(["DARK_ZONE_ENTERED", "DARK_ZONE_EXITED"])].copy()
    for r in markers.itertuples(index=False):
        if pd.isna(getattr(r, "dark_zone_id", np.nan)):
            continue
        kind = "enter" if r.event_type == "DARK_ZONE_ENTERED" else "exit"
        pr = 0 if kind == "enter" else 4
        timeline.append((float(r.timestamp_ms) / 1000.0, pr, seq, kind, r)); seq += 1
    for e in evidence:
        timeline.append((e["ts_s"], 1, seq, "evidence", e)); seq += 1
    timeline.sort(key=lambda z: (z[0], z[1], z[2]))

    next_tick = {}
    tick_heap = []

    def push(vid, t):
        next_tick[vid] = float(t)
        heapq.heappush(tick_heap, (float(t), vid))

    def ticks_before(limit_s, strict=True):
        cmp = (lambda t: t < limit_s) if strict else (lambda t: t <= limit_s)
        while tick_heap and cmp(tick_heap[0][0]):
            t, vid = heapq.heappop(tick_heap)
            if next_tick.get(vid) != t:
                continue
            if vid not in bridge.active:
                next_tick.pop(vid, None); continue
            bridge.tick(vid, t)
            push(vid, t + prediction_interval_s)

    i = 0
    while i < len(timeline):
        t = timeline[i][0]
        ticks_before(t, True)
        same = []
        while i < len(timeline) and timeline[i][0] == t:
            same.append(timeline[i]); i += 1
        for _, _, _, kind, obj in same:
            if kind == "enter":
                zid = str(obj.dark_zone_id); vid = str(obj.unit_id)
                if zid in bridge.zones:
                    bridge.enter(vid, zid, t)
                    push(vid, t + prediction_interval_s)
            elif kind == "evidence":
                bridge.apply_checkpoint(
                    obj["vehicle_id"], obj["station_id"], obj["progress"], t, obj["sensor_std"]
                )
        ticks_before(t, False)
        for _, _, _, kind, obj in same:
            if kind == "exit":
                zid = str(obj.dark_zone_id); vid = str(obj.unit_id)
                if zid in bridge.zones:
                    bridge.exit(vid, zid, t)
                    next_tick.pop(vid, None)


def run_feature_bridge(
    stations_csv: str,
    station_events_csv: str,
    units_csv: str,
    historical_dwell_csv: str,
    output_dir: str,
    manual_checks_csv: Optional[str] = None,
    checkpoint_events_csv: Optional[str] = None,
    station_checkpoints_csv: Optional[str] = None,
    prediction_interval_s: float = 60.0,
    dwell_dist: str = "gamma",
    run_id: str = "UNKNOWN",
    config_prior_scale: float = 1.0,
    corridor_particles: int = 3000,
    corridor_residence_csv: Optional[str] = None,
):
    if prediction_interval_s <= 0:
        raise ValueError("prediction_interval_s must be > 0")
    if bool(checkpoint_events_csv) != bool(station_checkpoints_csv):
        raise ValueError("checkpoint_events_csv and station_checkpoints_csv must be supplied together")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stations = pd.read_csv(stations_csv)
    stations["station_id"] = stations["station_id"].astype(str)
    raw = pd.read_csv(station_events_csv)
    raw["station_id"] = raw["station_id"].astype(str)
    raw["timestamp_ms"] = pd.to_numeric(raw["timestamp_ms"], errors="raise").astype(np.int64)
    units_df = pd.read_csv(units_csv)
    units = dict(zip(units_df["unit_id"].astype(str), units_df["vehicle_model"].astype(str)))

    models, config_fallbacks = load_dwell_models(
        historical_dwell_csv, stations, dwell_dist, config_prior_scale
    )
    residence_bundle = (
        load_corridor_residence_models(corridor_residence_csv, dwell_dist)
        if corridor_residence_csv else None
    )
    collector = OutputCollector()

    # ---- Single-station path: always use the existing orchestrator. ----
    single_ids = _single_dark_station_ids(stations, raw)
    has_arrival = set(
        raw.loc[raw["event_type"].astype(str).eq("UNIT_ARRIVED"), "station_id"].astype(str)
    ) & single_ids
    engine_events = load_all_dark_zone_events(
        station_events_csv,
        units_csv,
        manual_checks_csv=manual_checks_csv,
        checkpoint_events_csv=checkpoint_events_csv,
        station_checkpoints_csv=station_checkpoints_csv,
        dark_zone_station_ids=single_ids,
    )
    # Canonicalize identifiers once at the adapter boundary so active-registry
    # keys cannot diverge because pandas inferred numeric vs string unit IDs.
    for ev in engine_events:
        ev.vehicle_id = str(ev.vehicle_id)
        ev.station_id = str(ev.station_id)
    orch = DarkZoneOrchestrator(models, persistence=None, auto_recover=False)
    single_bridge = SingleStationMLBridge(
        orch, stations, models, run_id,
        unit_arrived_stations=has_arrival,
        cycle_lookup=_build_cycle_lookup(raw),
        collector=collector,
    )
    _run_single_replay(single_bridge, raw, engine_events, single_ids, prediction_interval_s)

    # ---- Corridor path: existing MultiStationParticleFilter, unchanged. ----
    zones = detect_corridor_zones(stations, raw)
    corridor_bridge = CorridorMLBridge(
        stations, models, units, zones, run_id, collector,
        n_particles=corridor_particles, residence_bundle=residence_bundle
    )
    corridor_evidence = _corridor_evidence_events(
        checkpoint_events_csv, station_checkpoints_csv, manual_checks_csv, zones
    )
    _run_corridor_replay(corridor_bridge, raw, corridor_evidence, prediction_interval_s)

    event_frame = pd.DataFrame(collector.ml_rows)
    event_cols = ["run_id", "vehicle_id", "prediction_time", "trigger"] + FEATURES_28
    for c in event_cols:
        if c not in event_frame.columns:
            event_frame[c] = np.nan
    event_frame = event_frame[event_cols].sort_values(
        ["prediction_time", "vehicle_id"], kind="stable"
    ).reset_index(drop=True)
    # Canonical model stream is station-level, like the Light-Zone bottleneck
    # training rows. Several vehicle/evidence triggers can produce the same
    # station snapshot at the exact same timestamp; retain the final causal
    # snapshot once and keep every trigger only in the debug file.
    ml = event_frame.drop_duplicates(
        subset=["run_id", "prediction_time", "station_id"], keep="last"
    ).drop(columns=["trigger"]).reset_index(drop=True)
    dash = pd.DataFrame(collector.dashboard_rows)
    prov = pd.DataFrame(collector.provenance_rows)

    # Model-facing canonical file + compatibility alias used by the previous package.
    canonical = out / "dark_zone_bottleneck_features_28.csv"
    alias = out / "dark_zone_bottleneck_features.csv"
    ml.to_csv(canonical, index=False)
    ml.to_csv(alias, index=False)
    event_frame.to_csv(out / "dark_zone_feature_events_debug.csv", index=False)
    dash.to_csv(out / "dark_zone_dashboard_state.csv", index=False)
    prov.to_csv(out / "dark_zone_feature_provenance.csv", index=False)

    quality = validate_feature_frame(ml)
    quality.update({
        "rows": int(len(ml)),
        "single_station_ids": sorted(single_ids),
        "corridor_ids": sorted(zones),
        "config_prior_fallback_stations": sorted(config_fallbacks),
        "corridor_residence_calibration_enabled": bool(residence_bundle),
        "corridor_residence_calibration_rows": int(residence_bundle.get("rows", 0)) if residence_bundle else 0,
    })
    (out / "dark_zone_feature_quality.json").write_text(json.dumps(quality, indent=2, default=str))

    engine_root = Path(__file__).resolve().parent
    core_files = ["orchestrator.py", "dark_zone_tracker.py", "multi_station_tracker.py", "persistence.py"]
    hashes = {}
    for name in core_files:
        p = engine_root / name
        hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()

    audit = {
        "architecture": "existing_dark_zone_engine_plus_passive_ml_bridge",
        "single_station_engine": "DarkZoneOrchestrator",
        "single_station_direct_pf_predict_calls_in_bridge": 0,
        "single_station_direct_pf_update_calls_in_bridge": 0,
        "orchestrator_routed_event_counts": dict(single_bridge.routed_counts),
        "orchestrator_evidence_events_routed": int(single_bridge.evidence_routed),
        "orchestrator_rejections": len(orch.rejected_log),
        "orchestrator_rejection_reasons": dict(pd.Series([r["reason"] for r in orch.rejected_log]).value_counts()) if orch.rejected_log else {},
        "corridor_engine": "MultiStationParticleFilter",
        "corridor_evidence_applied": int(corridor_bridge.evidence_applied),
        "corridor_evidence_skipped": int(corridor_bridge.evidence_skipped),
        "corridor_boundary_counts": dict(corridor_bridge.boundary_counts),
        "corridor_residence_calibration_enabled": bool(residence_bundle),
        "corridor_calibration_source_counts": dict(corridor_bridge.calibration_source_counts),
        "core_engine_sha256": hashes,
        "note": "Core estimator files are not modified by the bridge. Offline replay uses no persistence database; live integration should attach this bridge to the already-running persisted orchestrator instance.",
    }
    (out / "dark_zone_bridge_audit.json").write_text(json.dumps(audit, indent=2, default=str))
    return ml, dash, prov, audit, quality
