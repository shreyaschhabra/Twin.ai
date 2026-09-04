"""
Dark Zone Tracking Engine — Orchestration Layer (Layers 3-6)
===============================================================
Wires the Layer 1/2 particle filter engine (dark_zone_tracker.py) into a
multi-vehicle, event-driven runtime:

  - VehicleTracker registry: one ParticleFilter per in-flight vehicle
  - EventRouter: dispatches async, out-of-order events to the right vehicle
  - Layer 3: RFID/BLE checkpoint updates, with Mahalanobis-style gating
             against false/ghost reads
  - Layer 4: CT clamp power-draw weak-label updates (wide-variance likelihood)
  - Layer 5: Andon/QR human-triggered updates, with a physical-plausibility
             gate (tight variance, never a hard reset)
  - Layer 6: JSON export contract for the UI (mean, std, confidence, entropy,
             multimodality flag)

Swap `InMemoryEventBus` for a real Kafka/MQTT consumer later — everything
downstream of `route_event()` is transport-agnostic.
"""

from __future__ import annotations

import time
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import numpy as np
from scipy import stats

from dark_zone_tracker import (
    DwellDistribution,
    DarkZoneParticleFilter,
    ParticleFilterConfig,
    fit_dwell_distribution,
)
from persistence import SQLitePersistence


# =====================================================================
# EVENT TYPES
# =====================================================================

class EventType(str, Enum):
    TICK = "tick"                      # predict-only heartbeat
    RFID_CHECKPOINT = "rfid_checkpoint"  # Layer 3
    POWER_DRAW = "power_draw"            # Layer 4
    ANDON_SCAN = "andon_scan"            # Layer 5
    STATION_ENTRY = "station_entry"      # spawn a new tracker
    STATION_EXIT = "station_exit"        # tear down a tracker


@dataclass
class DarkZoneEvent:
    event_type: EventType
    vehicle_id: str
    station_id: str
    ts: float                       # unix seconds, edge timestamp (not ingestion time)
    variant: Optional[str] = None            # required for STATION_ENTRY
    checkpoint_progress: Optional[float] = None  # nominal progress fraction (Layer 3)
    payload: dict = field(default_factory=dict)  # free-form extra data


# =====================================================================
# LAYER 3 — RFID/BLE checkpoint likelihood, with gating
# =====================================================================

def rfid_checkpoint_likelihood(
    pf: DarkZoneParticleFilter,
    observed_progress: float,
    sensor_std: float = 0.05,
    gate_sigma: float = 4.0,
) -> Optional[callable]:
    """
    Returns a likelihood_fn for an RFID/BLE boundary read, OR None if the
    read fails a plausibility gate and should be dropped entirely.

    Gating rationale (Noise Analysis, Layer 3): false/ghost reads from
    multipath reflection are low-frequency (~1-3%) but land with full
    confidence if not screened. We reject any read whose observed_progress
    is more than `gate_sigma` particle-standard-deviations away from the
    filter's current belief BEFORE folding it into the update — this is a
    Mahalanobis-style consistency check, cheap and effective.
    """
    current_mean = float(np.average(pf.progress, weights=pf.weights))
    current_std = float(np.sqrt(np.average((pf.progress - current_mean) ** 2, weights=pf.weights)))
    current_std = max(current_std, 1e-3)

    z = abs(observed_progress - current_mean) / current_std
    if z > gate_sigma:
        return None  # gated out — treat as a dropped/ghost read

    # Student-t (df=4) rather than Gaussian: heavier tails absorb residual
    # measurement noise without letting one bad-but-not-gated read fully
    # dominate the posterior.
    def _lik(progress: np.ndarray) -> np.ndarray:
        return stats.t.pdf((progress - observed_progress) / sensor_std, df=4)
    return _lik


# =====================================================================
# LAYER 4 — CT clamp power-draw weak-label likelihood
# =====================================================================

def power_draw_likelihood(
    inferred_progress: float,
    sensor_std: float = 0.12,   # deliberately wide vs RFID's 0.05 — weak label
):
    """
    A current-spike is a soft, low-confidence signal that *some* operation
    fired near `inferred_progress`. Wide variance means this update nudges
    the posterior modestly rather than snapping it — matching its lower
    trustworthiness (10-20% false positive/negative rate per the noise
    analysis).
    """
    def _lik(progress: np.ndarray) -> np.ndarray:
        return stats.norm.pdf(progress, loc=inferred_progress, scale=sensor_std)
    return _lik


# =====================================================================
# LAYER 5 — Andon/QR human-triggered likelihood, with plausibility gate
# =====================================================================

def andon_likelihood(
    pf: DarkZoneParticleFilter,
    claimed_progress: float,
    sensor_std: float = 0.03,   # tight, but NEVER zero — see noise analysis
) -> Optional[callable]:
    """
    High-confidence but NOT infallible. Two protections:
      1. Tight-but-nonzero variance (never a hard delta-function reset) —
         guards against scan latency ("batch scanning at end of task").
      2. Physical plausibility gate: reject claims that are impossible given
         elapsed time so far (e.g. "done" scanned 5s after station entry on
         a 4-minute-mean station).
    """
    elapsed_frac_of_mean_T = pf.elapsed_s / max(float(np.average(pf.T, weights=pf.weights)), 1e-3)
    # If claimed progress is wildly inconsistent with elapsed time (more than
    # ~3x faster than the fastest plausible particle would allow), reject.
    if claimed_progress > 0.0 and elapsed_frac_of_mean_T < claimed_progress * 0.15:
        return None  # implausible — flag for QA review rather than trusting

    def _lik(progress: np.ndarray) -> np.ndarray:
        return stats.norm.pdf(progress, loc=claimed_progress, scale=sensor_std)
    return _lik


# =====================================================================
# VEHICLE TRACKER REGISTRY + ROUTER
# =====================================================================

class DarkZoneOrchestrator:
    """
    Owns one DarkZoneParticleFilter per in-flight vehicle and routes
    incoming events to the correct filter with the correct likelihood.
    """

    def __init__(
        self,
        dwell_models: dict[tuple[str, str], DwellDistribution],
        persistence: Optional[SQLitePersistence] = None,
        auto_recover: bool = True,
        persist_mode: str = "immediate",   # "immediate" or "batched"
        batch_size: int = 50,
        flush_interval_s: float = 2.0,
    ):
        self.dwell_models = dwell_models
        self.active: dict[str, DarkZoneParticleFilter] = {}
        self.meta: dict[str, dict] = {}          # vehicle_id -> {station, variant, entry_ts}
        self.last_event_ts: dict[str, float] = {}  # for computing dt on TICK
        self.rejected_log: list[dict] = []        # gated-out events, for QA review
        self.confirmed_exits: list[dict] = []     # real, confirmed exit records — the ONLY
                                                     # non-inferred output this system produces
        self.persistence = persistence

        # persist_mode trade-off:
        #   "immediate" — one transaction per event. Zero data loss window on
        #                 crash, but transaction overhead caps throughput
        #                 (roughly hundreds to low-thousands of events/sec on
        #                 typical disks with WAL+NORMAL).
        #   "batched"   — buffers dirty vehicles, flushes every `batch_size`
        #                 updates OR every `flush_interval_s` seconds,
        #                 whichever comes first. Throughput scales ~linearly
        #                 with batch_size; crash-loss window is bounded by
        #                 flush_interval_s of the most recent updates to
        #                 vehicles that haven't hit batch_size yet.
        # For CSV backtesting/replay (no real-time durability requirement),
        # "batched" is the right default. For a live production feed where
        # a lost update = a wrong-looking vehicle on the floor for a few
        # seconds, "immediate" is safer.
        self.persist_mode = persist_mode
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self._dirty: set[str] = set()
        self._last_flush_ts = time.time()

        if self.persistence and auto_recover:
            self.recover()

    # ---------------- CRASH RECOVERY ----------------
    def recover(self) -> int:
        """
        Rehydrate every in-flight vehicle from the last persisted snapshot.
        Call this once at process startup, BEFORE consuming any new events
        off the event bus. Returns the number of vehicles recovered.
        """
        if not self.persistence:
            return 0

        rows = self.persistence.load_all_vehicle_states()
        for row in rows:
            key = (row["station_id"], row["variant"])
            dist = self.dwell_models.get(key) or self.dwell_models.get(
                (row["station_id"], "__ALL__")
            )
            if dist is None:
                # Can't recover without a matching dwell model — log and skip
                # rather than crash the whole recovery pass.
                self.rejected_log.append({
                    "reason": "recovery_missing_dwell_model",
                    "event": {"vehicle_id": row["vehicle_id"], "station_id": row["station_id"]},
                })
                continue

            pf = DarkZoneParticleFilter.from_state(dist, row["pf_state"])
            self.active[row["vehicle_id"]] = pf
            self.meta[row["vehicle_id"]] = {
                "station": row["station_id"], "variant": row["variant"],
                "entry_ts": row["entry_ts"],
            }
            self.last_event_ts[row["vehicle_id"]] = row["last_event_ts"]

        return len(self.active)

    def _persist(self, vehicle_id: str) -> None:
        """Called after every state-changing event. Behavior depends on
        persist_mode (see __init__ docstring)."""
        if not self.persistence or vehicle_id not in self.active:
            return

        if self.persist_mode == "immediate":
            m = self.meta[vehicle_id]
            self.persistence.save_vehicle_state(
                vehicle_id=vehicle_id,
                station_id=m["station"],
                variant=m["variant"],
                entry_ts=m["entry_ts"],
                last_event_ts=self.last_event_ts[vehicle_id],
                pf=self.active[vehicle_id],
            )
        else:  # "batched"
            self._dirty.add(vehicle_id)
            should_flush = (
                len(self._dirty) >= self.batch_size
                or (time.time() - self._last_flush_ts) >= self.flush_interval_s
            )
            if should_flush:
                self.flush()

    def flush(self) -> int:
        """
        Force-write all pending ("dirty") vehicle states in one transaction.
        Call this explicitly at the end of a batch/replay run, or on a
        periodic timer in a long-running process using batched mode, to
        bound the crash-loss window. Returns the number of vehicles flushed.
        """
        if not self.persistence or not self._dirty:
            self._last_flush_ts = time.time()
            return 0

        states = []
        for vid in list(self._dirty):
            if vid not in self.active:
                continue  # torn down since being marked dirty; already deleted from DB
            m = self.meta[vid]
            states.append((
                vid, m["station"], m["variant"], m["entry_ts"],
                self.last_event_ts[vid], self.active[vid],
            ))

        self.persistence.save_vehicle_states_batch(states)
        n = len(states)
        self._dirty.clear()
        self._last_flush_ts = time.time()
        return n

    def route_event(self, ev: DarkZoneEvent) -> None:
        if ev.event_type == EventType.STATION_ENTRY:
            self._spawn(ev)
            return

        if ev.vehicle_id not in self.active:
            # Event for a vehicle we haven't seen enter — log and skip.
            self.rejected_log.append({"reason": "unknown_vehicle", "event": ev.__dict__})
            return

        pf = self.active[ev.vehicle_id]

        # Always predict up to this event's timestamp first (async, event-driven —
        # not a fixed tick loop).
        dt = max(0.0, ev.ts - self.last_event_ts.get(ev.vehicle_id, ev.ts))
        if dt > 0:
            pf.predict(dt)
        self.last_event_ts[ev.vehicle_id] = ev.ts

        if ev.event_type == EventType.TICK:
            pass  # predict-only, already done above

        elif ev.event_type == EventType.RFID_CHECKPOINT:
            lik = rfid_checkpoint_likelihood(pf, ev.checkpoint_progress)
            if lik is None:
                self._log_rejected(ev.vehicle_id, "rfid_gated", ev)
            else:
                pf.update(lik)

        elif ev.event_type == EventType.POWER_DRAW:
            lik = power_draw_likelihood(ev.checkpoint_progress)
            pf.update(lik)  # no gate — Layer 4 is inherently soft, gating would over-reject

        elif ev.event_type == EventType.ANDON_SCAN:
            lik = andon_likelihood(pf, ev.checkpoint_progress)
            if lik is None:
                self._log_rejected(ev.vehicle_id, "andon_implausible", ev)
            else:
                pf.update(lik)

        elif ev.event_type == EventType.STATION_EXIT:
            # Emit the confirmed-exit record BEFORE teardown discards the
            # state — this is the fix for the second gap: previously the
            # real, true exit timestamp was used only internally to stop
            # tracking, then thrown away. Downstream consumers never
            # received a clean "this genuinely happened" record at all,
            # only the continuous in-progress ESTIMATES beforehand.
            self.confirmed_exits.append(self._build_confirmed_exit(ev))
            self._teardown(ev.vehicle_id)
            return  # nothing left to persist for this vehicle

        # Write-ahead: persist AFTER mutating in-memory state, before this
        # route_event() call returns control to the caller's event-bus ack.
        self._persist(ev.vehicle_id)

    def _build_confirmed_exit(self, ev: "DarkZoneEvent") -> dict:
        """
        The ONE record type this whole system produces that is NOT an
        estimate. Matches the same field shape a real light-zone sensor
        event would have (VIN, station, exit timestamp) — this is what
        makes dark-zone output structurally compatible with the shared
        Feast/stream pipeline real telemetry feeds, per the architecture
        doc's integration requirement. entry_ts included for computing the
        real, ground-truth-accurate total dwell time, now that it's known.
        """
        m = self.meta.get(ev.vehicle_id, {})
        return {
            "vehicle_id": ev.vehicle_id,
            "station_id": ev.station_id,
            "variant": m.get("variant"),
            "entry_ts": m.get("entry_ts"),
            "exit_ts": ev.ts,
            "actual_dwell_s": (ev.ts - m["entry_ts"]) if "entry_ts" in m else None,
            "is_inferred": False,
            "data_source": "confirmed_boundary_event",
        }

    def export_confirmed_exits(self, clear: bool = True) -> list[dict]:
        """Call periodically (e.g. every batch flush) to drain confirmed-exit
        records for downstream delivery. clear=True empties the buffer so
        records aren't re-delivered on the next call."""
        records = list(self.confirmed_exits)
        if clear:
            self.confirmed_exits.clear()
        return records

    def _log_rejected(self, vehicle_id: str, reason: str, ev: DarkZoneEvent) -> None:
        self.rejected_log.append({"reason": reason, "event": ev.__dict__})
        if self.persistence:
            self.persistence.log_rejected_event(vehicle_id, reason, ev.__dict__)

    def _spawn(self, ev: DarkZoneEvent) -> None:
        # Physical-consistency guard: a real vehicle cannot be at two
        # stations simultaneously. A STATION_ENTRY for a vehicle that's
        # already active elsewhere means either (a) a rework/revisit loop
        # sent it back through a dark-zone station, or (b) an out-of-order/
        # data-quality problem — the same class of issue already found
        # twice in this project's real data. Previously this silently
        # overwrote the old tracker (self.active keyed by vehicle_id alone)
        # with no warning; the corruption only surfaced later as a
        # confusing, disconnected "unknown_vehicle" rejection when the
        # orphaned station's exit event arrived. Now it's caught and
        # logged loudly at the moment it actually happens, matching how
        # every other data anomaly in this pipeline is handled.
        if ev.vehicle_id in self.active:
            prior_station = self.meta[ev.vehicle_id]["station"]
            if prior_station != ev.station_id:
                self._log_rejected(
                    ev.vehicle_id, "vehicle_already_active_at_another_station", ev
                )
                print(f"⚠ DATA ANOMALY: {ev.vehicle_id} entered {ev.station_id} while still "
                      f"active at {prior_station} (never received a STATION_EXIT there). "
                      f"Tearing down the stale {prior_station} tracker and proceeding with "
                      f"the new entry — but this points at a real ordering issue upstream, "
                      f"not sensor noise.")
                self._teardown(ev.vehicle_id)

        key = (ev.station_id, ev.variant)
        dist = self.dwell_models.get(key)
        if dist is None:
            # No specific fit available — try the station-level fallback
            # ("__ALL__" variant), registered by fit_dwell_distribution or
            # by the caller when historical data was too sparse for a
            # station-level fit too.
            dist = self.dwell_models.get((ev.station_id, "__ALL__"))
        if dist is None:
            # Still nothing (e.g. a station with almost zero historical
            # data — common in small test/demo datasets). Fall back to a
            # single cross-station global distribution if the caller
            # registered one, rather than crashing the whole replay for
            # one under-sampled station.
            dist = self.dwell_models.get(("__GLOBAL__", "__ALL__"))
        if dist is None:
            # Truly nothing usable anywhere — log and skip this vehicle
            # rather than raising. One bad/unmapped station should never
            # kill an otherwise-healthy replay of thousands of events.
            self._log_rejected(
                ev.vehicle_id, "no_dwell_model_available", ev
            )
            return

        self.active[ev.vehicle_id] = DarkZoneParticleFilter(dist)
        self.meta[ev.vehicle_id] = {
            "station": ev.station_id, "variant": ev.variant, "entry_ts": ev.ts,
        }
        self.last_event_ts[ev.vehicle_id] = ev.ts
        self._persist(ev.vehicle_id)

    def _teardown(self, vehicle_id: str) -> None:
        self.active.pop(vehicle_id, None)
        self.meta.pop(vehicle_id, None)
        self.last_event_ts.pop(vehicle_id, None)
        self._dirty.discard(vehicle_id)
        if self.persistence:
            self.persistence.delete_vehicle_state(vehicle_id)

    # ---------------- LAYER 6 — UI export contract ----------------
    def export_snapshot(self, vehicle_id: str) -> dict:
        """
        JSON-serializable snapshot for the UI. Includes an explicit
        multimodality flag so the frontend can render "ambiguous" state
        instead of a falsely confident single position (Layer 6 noise note).
        """
        pf = self.active[vehicle_id]
        est = pf.estimate()

        # Cheap multimodality check: split particles at the median and see if
        # the two halves' means are further apart than their pooled std would
        # suggest for a unimodal cloud.
        sorted_p = np.sort(pf.progress)
        lo, hi = sorted_p[: len(sorted_p) // 2], sorted_p[len(sorted_p) // 2 :]
        gap = abs(np.mean(hi) - np.mean(lo)) if len(lo) and len(hi) else 0.0
        multimodal = bool(gap > 3 * est["progress_std"] and est["progress_std"] > 0.02)

        return {
            "vehicle_id": vehicle_id,
            "station_id": self.meta[vehicle_id]["station"],
            "variant": self.meta[vehicle_id]["variant"],
            "progress_mean": round(est["progress_mean"], 4),
            "progress_std": round(est["progress_std"], 4),
            "eta_std": round(est["eta_std"], 2),
            "render_confidence": round(est["render_confidence"], 3),
            "eta_seconds": round(est["eta_s"], 1),
            # EXPLICIT provenance marker — this is the fix for a real gap:
            # nothing previously told a downstream consumer this row came
            # from a particle filter estimate rather than a real sensor.
            # Never omit this field; a consumer merging dark-zone output
            # with real light-zone telemetry MUST be able to tell them
            # apart without cross-referencing a separate station list.
            "is_inferred": True,
            "data_source": "particle_filter_estimate",
            "elapsed_seconds": round(est["elapsed_s"], 1),
            "multimodal_warning": multimodal,
            "snapshot_ts": time.time(),
        }

    def export_all_snapshots(self) -> list[dict]:
        return [self.export_snapshot(vid) for vid in self.active]


# =====================================================================
# DEMO — crash + recovery simulation
# =====================================================================
if __name__ == "__main__":
    import os
    import pandas as pd

    DB_PATH = "demo_dark_zone_state.db"
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)  # clean slate for repeatable demo runs

    rng = np.random.default_rng(7)
    n_hist = 400
    dwell_samples = stats.gamma.rvs(6.0, scale=45.0, size=n_hist, random_state=rng)
    entry = pd.date_range("2026-01-01", periods=n_hist, freq="5min")
    hist_df = pd.DataFrame({
        "station_id": "ST-14_WIRING",
        "variant": rng.choice(["SEDAN_BASE", "SEDAN_SPORT"], size=n_hist),
        "entry_ts": entry,
        "exit_ts": entry + pd.to_timedelta(dwell_samples, unit="s"),
    })
    dwell_models = fit_dwell_distribution(hist_df, dist_name="gamma")
    dwell_models[("ST-14_WIRING", "__ALL__")] = dwell_models[("ST-14_WIRING", "SEDAN_BASE")]

    # ---- "Process A": runs for a while, then dies ----
    persistence = SQLitePersistence(DB_PATH)
    orch_a = DarkZoneOrchestrator(dwell_models, persistence=persistence)

    pre_crash_events = [
        DarkZoneEvent(EventType.STATION_ENTRY, "VIN-001", "ST-14_WIRING", ts=0, variant="SEDAN_BASE"),
        DarkZoneEvent(EventType.STATION_ENTRY, "VIN-002", "ST-14_WIRING", ts=20, variant="SEDAN_SPORT"),
        DarkZoneEvent(EventType.RFID_CHECKPOINT, "VIN-001", "ST-14_WIRING", ts=140, checkpoint_progress=0.55),
        DarkZoneEvent(EventType.POWER_DRAW, "VIN-002", "ST-14_WIRING", ts=160, checkpoint_progress=0.30),
    ]
    for ev in pre_crash_events:
        orch_a.route_event(ev)

    print("=== Before crash ===")
    for vid in orch_a.active:
        print(json.dumps(orch_a.export_snapshot(vid)))

    print(f"\nVehicles in flight before crash: {list(orch_a.active.keys())}")
    print("--- process A dies here (simulated) ---\n")
    del orch_a  # orchestrator object gone; SQLite file on disk is the only survivor

    # ---- "Process B": fresh orchestrator, same DB file, must recover ----
    persistence_b = SQLitePersistence(DB_PATH)
    orch_b = DarkZoneOrchestrator(dwell_models, persistence=persistence_b)  # auto_recover=True by default

    n_recovered = len(orch_b.active)
    print(f"=== After restart: recovered {n_recovered} in-flight vehicle(s) ===")
    for vid in orch_b.active:
        print(json.dumps(orch_b.export_snapshot(vid)))

    # Prove tracking continues seamlessly post-recovery — no reset to t=0
    post_crash_events = [
        DarkZoneEvent(EventType.RFID_CHECKPOINT, "VIN-001", "ST-14_WIRING", ts=200, checkpoint_progress=0.80),
        DarkZoneEvent(EventType.ANDON_SCAN, "VIN-001", "ST-14_WIRING", ts=260, checkpoint_progress=1.0),
        DarkZoneEvent(EventType.STATION_EXIT, "VIN-001", "ST-14_WIRING", ts=261),
    ]
    for ev in post_crash_events:
        orch_b.route_event(ev)
        if ev.vehicle_id in orch_b.active:
            print(json.dumps(orch_b.export_snapshot(ev.vehicle_id)))

    print(f"\nVIN-001 present in DB after exit? "
          f"{'VIN-001' in [r['vehicle_id'] for r in persistence_b.load_all_vehicle_states()]}")
    print(f"VIN-002 still recoverable? "
          f"{'VIN-002' in [r['vehicle_id'] for r in persistence_b.load_all_vehicle_states()]}")
