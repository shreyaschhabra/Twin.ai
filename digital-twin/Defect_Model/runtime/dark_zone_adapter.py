"""Causal DARK-zone state adapter for the defect runtime.

This module deliberately reuses the validated bottleneck particle-filter engine as
an *observation/state-estimation service*.  It does not score bottlenecks and it
never reads hidden simulator processing truth.  Its inputs are only:

* public station/boundary events,
* public RFID/POWER checkpoint evidence,
* public station-local SENSOR observations,
* immutable station topology / dz.csv, and
* calibration built from PRIOR completed runs only.

The adapter exposes inferred DARK station transitions and probabilistic sensor
identity associations to the V5 defect feature builder.
"""
from __future__ import annotations

import hashlib

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from bottlenecks_prediction.config.configure_stations import configure_from_dz
from bottlenecks_prediction.factory_models import build_dark_calibration_files
from bottlenecks_prediction.runtime.runtime_controller import DigitalTwinRuntimeController


@dataclass(frozen=True)
class DarkInferredArrival:
    unit_id: str
    station_id: str
    # Causal emission/confirmation time. This is never earlier than the public
    # observation that made the transition knowable to the runtime.
    timestamp_ms: int
    # PF's retrospective estimate of when the physical transition most likely
    # occurred. Kept as diagnostics/metadata only; it is never used to move the
    # feature-builder clock backward.
    estimated_transition_time_ms: int | None
    queue_estimate: float | None
    state_confidence: float
    route: str
    trigger: str


class DefectDarkZoneAdapter:
    """Independent PF mirror used by the parallel defect consumer."""

    def __init__(
        self,
        *,
        stations_csv: str | Path,
        dz_csv: str | Path,
        units_csv: str | Path,
        history_runs: list[str | Path],
        runtime_dir: str | Path,
        dark_zone_dir: str | Path,
        historical_dwell_csv: str | Path | None = None,
        corridor_residence_csv: str | Path | None = None,
        run_id: str = "LIVE",
        corridor_particles: int = 3000,
        random_seed: int | None = None,
        transition_confidence: float = 0.55,
        sensor_assignment_confidence: float = 0.55,
    ):
        self.run_id = str(run_id)
        if random_seed is None:
            digest = hashlib.sha256(self.run_id.encode("utf-8")).digest()
            random_seed = int.from_bytes(digest[:4], "big", signed=False)
        self.random_seed = int(random_seed)
        self.transition_confidence = float(transition_confidence)
        self.sensor_assignment_confidence = float(sensor_assignment_confidence)
        if not (0.0 <= self.transition_confidence <= 1.0):
            raise ValueError("transition_confidence must be within [0,1]")
        if not (0.0 <= self.sensor_assignment_confidence <= 1.0):
            raise ValueError("sensor_assignment_confidence must be within [0,1]")

        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        configured, dark_ids = configure_from_dz(stations_csv, dz_csv)
        self.dark_station_ids = set(map(str, dark_ids))
        self._station_index = {
            str(sid): int(i) for i, sid in enumerate(configured["station_id"].astype(str).tolist())
        }
        self.sensor_observable_dark_stations: set[str] = set()
        self.manual_observable_dark_stations: set[str] = set()
        self.checkpoint_observable_dark_stations: set[str] = set()
        dz = pd.read_csv(dz_csv)
        def _truthy(value: Any) -> bool:
            return str(value).strip().lower() in {"1", "true", "yes", "y"}
        for row in dz.to_dict(orient="records"):
            start = str(row.get("start_station_id", "")).strip()
            end = str(row.get("end_station_id", "")).strip()
            if start not in self._station_index or end not in self._station_index:
                continue
            lo, hi = self._station_index[start], self._station_index[end]
            if lo > hi:
                lo, hi = hi, lo
            members = {
                sid for sid, idx in self._station_index.items() if lo <= idx <= hi
            }
            if _truthy(row.get("sensor_telemetry", False)):
                self.sensor_observable_dark_stations.update(members)
            if _truthy(row.get("manual_checks", False)):
                self.manual_observable_dark_stations.update(members)
            if _truthy(row.get("checkpoints", False)):
                self.checkpoint_observable_dark_stations.update(members)
        self.configured_stations = self.runtime_dir / "configured_stations.csv"
        configured.to_csv(self.configured_stations, index=False)

        self.historical_dwell: Path | None = None
        self.corridor_residence: Path | None = None
        self.calibration_manifest: dict[str, Any] = {
            "history_runs": [],
            "current_run_excluded": True,
        }

        if self.dark_station_ids:
            supplied_dwell = (
                Path(historical_dwell_csv).expanduser().resolve()
                if historical_dwell_csv is not None else None
            )
            supplied_residence = (
                Path(corridor_residence_csv).expanduser().resolve()
                if corridor_residence_csv is not None else None
            )
            if supplied_dwell is not None:
                if not supplied_dwell.is_file():
                    raise FileNotFoundError(f"DARK historical dwell calibration not found: {supplied_dwell}")
                if supplied_residence is not None and not supplied_residence.is_file():
                    raise FileNotFoundError(f"DARK corridor calibration not found: {supplied_residence}")
                self.historical_dwell = supplied_dwell
                self.corridor_residence = supplied_residence
                self.calibration_manifest = {
                    "source": "selected_factory_artifact",
                    "history_runs": [],
                    "current_run_excluded": True,
                    "historical_dwell": str(supplied_dwell),
                    "corridor_residence": str(supplied_residence) if supplied_residence else None,
                }
            else:
                runs = [Path(p).expanduser().resolve() for p in history_runs]
                if not runs:
                    raise FileNotFoundError(
                        "DARK defect inference requires prior completed calibration history. "
                        "Current-run data is never used for PF calibration."
                    )
                cal_dir = self.runtime_dir / "calibration"
                dwell, residence, meta = build_dark_calibration_files(
                    runs,
                    self.configured_stations,
                    cal_dir,
                    dark_station_ids=self.dark_station_ids,
                )
                if dwell is None:
                    raise RuntimeError(
                        "Prior history did not produce DARK dwell calibration for the current topology"
                    )
                self.historical_dwell = dwell
                self.corridor_residence = residence
                self.calibration_manifest = {
                    **meta,
                    "history_runs": [p.name for p in runs],
                    "current_run_excluded": True,
                }

        self.controller = DigitalTwinRuntimeController(
            configured_stations_csv=self.configured_stations,
            units_csv=units_csv,
            dark_zone_dir=dark_zone_dir,
            historical_dwell_csv=self.historical_dwell,
            corridor_residence_csv=self.corridor_residence,
            run_id=self.run_id,
            corridor_particles=int(corridor_particles),
            random_seed=self.random_seed,
        )

        self._last_inferred_station: dict[str, str] = {}
        self._last_confidence: dict[str, float] = {}
        self._diagnostics = {
            "station_events": 0,
            "evidence_events": 0,
            "sensor_station_observations": 0,
            "inferred_arrivals": 0,
            "low_confidence_transitions_skipped": 0,
            "backward_transitions_suppressed": 0,
            # Compatibility counter retained for dashboards/tests created for the
            # stale-drop prototype. The recovered-history policy below no longer
            # drops a valid forward transition merely because the PF estimated its
            # physical time in the already-processed past.
            "stale_retrospective_transitions_dropped": 0,
            "stale_retrospective_transitions_recovered": 0,
            "max_stale_transition_lag_ms": 0,
            "sensor_associations": 0,
            "sensor_association_low_confidence": 0,
        }

    def refresh_units(self, units_csv: str | Path) -> int:
        return self.controller.refresh_units(units_csv)

    def _packet_arrivals(
        self,
        packets,
        *,
        observed_at_ms: int | None = None,
    ) -> list[DarkInferredArrival]:
        """Convert PF packets into online-safe DARK transitions.

        Online-recovery rule: public evidence may make the PF discover a physical
        transition after that transition actually happened.  The defect runtime
        must not move its feature clock backward, but dropping that transition also
        destroys the reconstructed completed-cycle history used by the V5 model.

        Therefore a valid forward retrospective transition is emitted at the
        *current causal observation time* while its PF-estimated physical transition
        time is retained separately as metadata.  The feature builder can use the
        physical estimate to reconstruct dwell duration, while all feature/output
        timestamps remain monotonic.  A packet dated in the future relative to the
        observation is still a hard error because that violates causality.
        """
        out: list[DarkInferredArrival] = []
        observed = int(observed_at_ms) if observed_at_ms is not None else None
        for p in packets:
            if not str(p.route).startswith("DARK") or p.vehicle_id is None:
                continue
            estimate = int(p.prediction_time_ms)
            if observed is not None and estimate > observed:
                raise RuntimeError(
                    "DARK PF emitted a future-dated transition: "
                    f"estimate={estimate} > causal observation={observed}"
                )
            # Recover late history without rewinding runtime time.  The arrival is
            # made knowable *now* (causal_time=observed), while ``estimate`` remains
            # the best physical transition-time estimate.  This lets the defect
            # feature builder recover completed DARK dwell/cycle history instead of
            # silently turning those features into NaNs.
            if observed is not None and estimate < observed:
                lag = observed - estimate
                self._diagnostics["stale_retrospective_transitions_recovered"] += 1
                self._diagnostics["max_stale_transition_lag_ms"] = max(
                    int(self._diagnostics["max_stale_transition_lag_ms"]), lag
                )

            causal_time = estimate if observed is None else observed

            state = p.dashboard_state or {}
            raw_conf = state.get("state_confidence", p.features_28.get("state_confidence", 0.0))
            try:
                conf = float(raw_conf)
            except (TypeError, ValueError):
                conf = 0.0
            q = p.features_28.get("current_occupancy")
            try:
                qf = float(q)
                queue = qf if np.isfinite(qf) else None
            except (TypeError, ValueError):
                queue = None
            out.append(
                DarkInferredArrival(
                    unit_id=str(p.vehicle_id),
                    station_id=str(p.station_id),
                    timestamp_ms=causal_time,
                    estimated_transition_time_ms=estimate,
                    queue_estimate=queue,
                    state_confidence=float(np.clip(conf, 0.0, 1.0)),
                    route=str(p.route),
                    trigger=str(p.trigger),
                )
            )

        # One observation can reveal more than one previously-hidden transition.
        # Apply them upstream -> downstream for each unit.  This never changes the
        # causal emission timestamp; it only prevents packet ordering from erasing
        # an intermediate station's reconstructed dwell.
        out.sort(
            key=lambda item: (
                int(item.timestamp_ms),
                str(item.unit_id),
                self._station_index.get(str(item.station_id), 10**9),
                int(item.estimated_transition_time_ms or item.timestamp_ms),
            )
        )
        return out

    def _accept_transition(self, item: DarkInferredArrival, *, force_confident: bool = False) -> bool:
        uid = item.unit_id
        previous = self._last_inferred_station.get(uid)
        if previous == item.station_id:
            self._last_confidence[uid] = item.state_confidence
            return False

        if previous is not None:
            prev_idx = self._station_index.get(previous, -1)
            new_idx = self._station_index.get(item.station_id, -1)
            if new_idx <= prev_idx:
                # Posterior mode may wobble under evidence, but physical line
                # progression cannot move to an earlier station. Never convert
                # that uncertainty wobble into fake processing intervals.
                self._diagnostics["backward_transitions_suppressed"] += 1
                return False
            if not force_confident and item.state_confidence < self.transition_confidence:
                self._diagnostics["low_confidence_transitions_skipped"] += 1
                return False

        self._last_inferred_station[uid] = item.station_id
        self._last_confidence[uid] = item.state_confidence
        self._diagnostics["inferred_arrivals"] += 1
        return True

    def _transitions_from_packets(
        self, packets, *, observed_at_ms: int | None = None
    ) -> list[DarkInferredArrival]:
        emitted: list[DarkInferredArrival] = []
        for item in self._packet_arrivals(packets, observed_at_ms=observed_at_ms):
            if self._accept_transition(item):
                emitted.append(item)
        return emitted

    def process_station_event(self, event: Mapping[str, Any]) -> list[DarkInferredArrival]:
        self._diagnostics["station_events"] += 1
        packets = self.controller.process_event(event)
        arrivals = self._transitions_from_packets(
            packets, observed_at_ms=int(event["timestamp_ms"])
        )
        typ = str(event.get("event_type", "")).strip().upper()
        uid = event.get("unit_id")
        if typ == "DARK_ZONE_EXITED" and uid is not None:
            # Controller emitted the final causal state before teardown. The feature
            # builder will close its inferred processing interval separately.
            self._last_inferred_station.pop(str(uid), None)
            self._last_confidence.pop(str(uid), None)
        return arrivals

    def process_evidence_event(self, event: Mapping[str, Any]) -> list[DarkInferredArrival]:
        self._diagnostics["evidence_events"] += 1
        packets = self.controller.process_evidence_event(event)
        return self._transitions_from_packets(
            packets, observed_at_ms=int(event["timestamp_ms"])
        )

    def observe_sensor_station(
        self,
        *,
        station_id: str,
        timestamp_ms: int,
    ) -> tuple[dict[str, float], list[DarkInferredArrival]]:
        """Use one public SENSOR location as anonymous DARK station evidence.

        Returns normalized unit-association probabilities and any newly inferred
        station transitions caused by the observation. The sensor *value* never
        enters the particle filter.
        """
        sid = str(station_id).strip()
        if sid not in self.dark_station_ids:
            return {}, []
        self._diagnostics["sensor_station_observations"] += 1

        before_mark = self.controller._dark_output_mark()
        assoc = self.controller.observe_anonymous_dark_station(sid, int(timestamp_ms))
        packets = self.controller._new_dark_packets(before_mark)
        arrivals = self._transitions_from_packets(
            packets, observed_at_ms=int(timestamp_ms)
        )

        # Defensive normalization. The controller already returns normalized JPDA
        # probabilities, but consumers should not depend on floating accumulation.
        observed_idx = self._station_index.get(sid, -1)
        clean = {}
        for uid, value in assoc.items():
            value = float(value)
            if not np.isfinite(value) or value <= 0:
                continue
            previous = self._last_inferred_station.get(str(uid))
            if previous is not None and self._station_index.get(previous, -1) > observed_idx:
                # Once a unit has causally crossed into a later station, an older
                # station's anonymous telemetry cannot be assigned back to it.
                continue
            clean[str(uid)] = value
        total = float(sum(clean.values()))
        if total > 0:
            clean = {uid: value / total for uid, value in clean.items()}
        if clean:
            self._diagnostics["sensor_associations"] += 1
            best_uid, best_conf = max(clean.items(), key=lambda kv: (kv[1], kv[0]))
            if best_conf < self.sensor_assignment_confidence:
                self._diagnostics["sensor_association_low_confidence"] += 1
            else:
                # A sensor firing at a known physical station is direct evidence
                # that its associated unit is there. When JPDA identity confidence
                # is strong enough, use that station location as a causal forward
                # transition cue even if the corridor posterior mode remains broad.
                direct = DarkInferredArrival(
                    unit_id=str(best_uid),
                    station_id=sid,
                    timestamp_ms=int(timestamp_ms),
                    estimated_transition_time_ms=int(timestamp_ms),
                    queue_estimate=None,
                    state_confidence=float(best_conf),
                    route="DARK_CORRIDOR",
                    trigger="dark_sensor_attributed_station",
                )
                if self._accept_transition(direct, force_confident=True):
                    arrivals.append(direct)
        return clean, arrivals

    def best_sensor_unit(self, association: Mapping[str, float]) -> tuple[str | None, float]:
        if not association:
            return None, 0.0
        uid, confidence = max(association.items(), key=lambda kv: (float(kv[1]), str(kv[0])))
        confidence = float(confidence)
        if confidence < self.sensor_assignment_confidence:
            return None, confidence
        return str(uid), confidence

    def is_dark_station(self, station_id: str) -> bool:
        return str(station_id).strip() in self.dark_station_ids

    def allows_dark_sensor(self, station_id: str) -> bool:
        return str(station_id).strip() in self.sensor_observable_dark_stations

    def allows_dark_manual(self, station_id: str) -> bool:
        return str(station_id).strip() in self.manual_observable_dark_stations

    def allows_dark_checkpoint(self, station_id: str) -> bool:
        return str(station_id).strip() in self.checkpoint_observable_dark_stations

    def diagnostics(self) -> dict[str, Any]:
        return {
            **self._diagnostics,
            "dark_stations": sorted(self.dark_station_ids),
            "transition_confidence": self.transition_confidence,
            "sensor_assignment_confidence": self.sensor_assignment_confidence,
            "sensor_observable_dark_stations": sorted(self.sensor_observable_dark_stations),
            "manual_observable_dark_stations": sorted(self.manual_observable_dark_stations),
            "checkpoint_observable_dark_stations": sorted(self.checkpoint_observable_dark_stations),
            "calibration": dict(self.calibration_manifest),
            "active_tracks": self.controller.dark_state_snapshot(
                self.controller._last_input_timestamp_ms or 0
            ) if self.dark_station_ids else [],
        }
