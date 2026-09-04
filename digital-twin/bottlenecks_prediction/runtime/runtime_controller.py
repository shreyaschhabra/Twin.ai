"""Runtime router for the bottleneck Digital Twin pipeline.

Pipeline role
-------------
    configured stations + incoming station event
                    |
                    v
            DigitalTwinRuntimeController
               |                    |
          LIGHT                      DARK
            |                  /              \
 LightZoneRuntimeFeatureBuilder   single PF    corridor PF
            |                  |              |
            |                   Dark feature bridge
            |_______________________  __________________|
                                    |
                         exact frozen 28-feature packets

This controller intentionally DOES NOT load or call XGBoost.  Model inference is
kept as the next pipeline step so Light and Dark can share one model adapter.

Incoming station-event contract
-------------------------------
The upstream simulator currently emits rows shaped like station_events.csv:
    event_id, timestamp_ms, event_type, station_id, unit_id,
    queue_length_after, previous_state, new_state, cycle_time_ms

Only timestamp_ms, station_id, and event_type are mandatory for Light. Dark
boundary tracking also requires unit_id.  The controller assigns a causal
``event_sequence`` in arrival order when the upstream event does not provide one.

Dark-zone causality rules
-------------------------
* A single isolated DARK station reuses the existing SingleStationMLBridge.
  UNIT_ARRIVED updates its causal queue ledger; PROCESSING_STARTED/COMPLETED are
  mapped to the existing DarkZoneOrchestrator entry/exit boundary events.
* Two or more consecutive DARK stations are treated as ONE corridor.  The
  corridor is inferred from configured station order; no synthetic
  DARK_ZONE_ENTERED/DARK_ZONE_EXITED rows are required from the upstream engineer.
  The observable runtime boundaries are:
      PROCESSING_COMPLETED at the upstream LIGHT station -> corridor enter
      PROCESSING_COMPLETED at the last dark station -> corridor exit
  This makes the first DARK station's waiting buffer part of the inferred
  corridor state. If a corridor starts at the physical line boundary and has no
  upstream station, PROCESSING_STARTED at the first DARK station is retained as
  a runnability fallback.
  Internal station_events inside the corridor are deliberately ignored, even if
  a simulator CSV contains them as hidden ground truth. This prevents accidental
  leakage of dark-station queue/cycle truth into the particle filter.
* Dark PFs stay alive between events. ``advance_time(timestamp_ms)`` emits the
  configured periodic prediction ticks; ``process_event`` automatically advances
  strictly-earlier ticks before routing the new event.

The 28 feature calculations themselves are NOT reimplemented here.  Light uses
``light_zone_runtime.py``; Dark reuses the frozen Dark Zone bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

# Allow both canonical ``bottlenecks_prediction.runtime`` imports and the
# repository's legacy ``runtime.runtime_controller`` test/CLI import style.
if __package__ and __package__.startswith("bottlenecks_prediction."):
    from ..light_zone.light_zone_runtime import BOTTLENECK_FEATURES, LightZoneRuntimeFeatureBuilder
else:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from light_zone.light_zone_runtime import BOTTLENECK_FEATURES, LightZoneRuntimeFeatureBuilder


# ---------------------------------------------------------------------------
# Public packet shape
# ---------------------------------------------------------------------------


@dataclass
class FeaturePacket:
    """One model-ready 28-feature prediction request produced by the router."""

    run_id: str
    route: str
    trigger: str
    station_id: str
    prediction_time_ms: int
    features_28: dict[str, Any]
    vehicle_id: Optional[str] = None
    event_id: Optional[str] = None
    event_sequence: Optional[int] = None
    dashboard_state: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "route": self.route,
            "trigger": self.trigger,
            "station_id": self.station_id,
            "prediction_time_ms": self.prediction_time_ms,
            "vehicle_id": self.vehicle_id,
            "event_id": self.event_id,
            "event_sequence": self.event_sequence,
            "features_28": dict(self.features_28),
            "dashboard_state": self.dashboard_state,
        }


@dataclass(frozen=True)
class CorridorDefinition:
    zone_id: str
    sequence: tuple[str, ...]
    first_station: str
    last_station: str
    upstream_light_station: Optional[str]
    downstream_light_station: Optional[str]


# ---------------------------------------------------------------------------
# Dark Zone import adapter
# ---------------------------------------------------------------------------


def _install_dark_zone_path(dark_zone_dir: str | Path) -> Path:
    """Make the existing flat Dark Zone module directory importable unchanged."""
    path = Path(dark_zone_dir).expanduser().resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Dark Zone directory not found: {path}")

    required = {
        "orchestrator.py",
        "dark_zone_ml_bridge.py",
        "dark_zone_feature_reconstructor.py",
        "dark_zone_tracker.py",
        "multi_station_tracker.py",
    }
    missing = sorted(name for name in required if not (path / name).is_file())
    if missing:
        raise FileNotFoundError(
            f"Dark Zone directory {path} is missing: {', '.join(missing)}"
        )

    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
    return path


def _dark_api(dark_zone_dir: str | Path):
    _install_dark_zone_path(dark_zone_dir)

    # Import only after the flat Dark Zone directory has been put on sys.path.
    from orchestrator import DarkZoneEvent, DarkZoneOrchestrator, EventType
    from dark_zone_feature_reconstructor import FEATURES_28
    from dark_zone_ml_bridge import (
        CorridorMLBridge,
        OutputCollector,
        SingleStationMLBridge,
        ZoneSpec,
        load_corridor_residence_models,
        load_dwell_models,
    )

    if list(FEATURES_28) != list(BOTTLENECK_FEATURES):
        raise RuntimeError(
            "Light and Dark feature contracts differ. Refusing to route to XGBoost.\n"
            f"Light: {BOTTLENECK_FEATURES}\nDark: {list(FEATURES_28)}"
        )

    return {
        "DarkZoneEvent": DarkZoneEvent,
        "DarkZoneOrchestrator": DarkZoneOrchestrator,
        "EventType": EventType,
        "CorridorMLBridge": CorridorMLBridge,
        "OutputCollector": OutputCollector,
        "SingleStationMLBridge": SingleStationMLBridge,
        "ZoneSpec": ZoneSpec,
        "load_corridor_residence_models": load_corridor_residence_models,
        "load_dwell_models": load_dwell_models,
    }


# ---------------------------------------------------------------------------
# Topology derivation
# ---------------------------------------------------------------------------


def _normalize_coverage(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip().upper()


def derive_dark_topology(stations: pd.DataFrame) -> tuple[set[str], dict[str, CorridorDefinition]]:
    """Split configured DARK stations into isolated singles and contiguous corridors.

    Station ROW ORDER is authoritative for adjacency, matching the rest of this
    project. A run such as S04,S05,S06 => one corridor; S09 alone => single PF.
    """
    if "station_id" not in stations.columns or "sensor_coverage" not in stations.columns:
        raise ValueError("Configured stations must contain station_id and sensor_coverage")

    order = stations["station_id"].astype(str).str.strip().tolist()
    if len(order) != len(set(order)):
        raise ValueError("Duplicate station_id values are not allowed")

    dark_mask = [
        _normalize_coverage(v) == "NONE"
        for v in stations["sensor_coverage"].tolist()
    ]

    groups: list[list[str]] = []
    current: list[str] = []
    for sid, is_dark in zip(order, dark_mask):
        if is_dark:
            current.append(sid)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    singles: set[str] = set()
    corridors: dict[str, CorridorDefinition] = {}
    pos = {sid: i for i, sid in enumerate(order)}

    for group in groups:
        if len(group) == 1:
            singles.add(group[0])
            continue

        first, last = group[0], group[-1]
        before = pos[first] - 1
        after = pos[last] + 1
        upstream = order[before] if before >= 0 else None
        downstream = order[after] if after < len(order) else None
        zone_id = f"DZ_{first}_{last}"
        corridors[zone_id] = CorridorDefinition(
            zone_id=zone_id,
            sequence=tuple(group),
            first_station=first,
            last_station=last,
            upstream_light_station=upstream,
            downstream_light_station=downstream,
        )

    return singles, corridors


# ---------------------------------------------------------------------------
# Runtime controller
# ---------------------------------------------------------------------------


class DigitalTwinRuntimeController:
    """Persistent event router for Light + Dark bottleneck feature generation."""

    def __init__(
        self,
        configured_stations_csv: str | Path,
        units_csv: str | Path,
        dark_zone_dir: str | Path,
        historical_dwell_csv: Optional[str | Path] = None,
        corridor_residence_csv: Optional[str | Path] = None,
        run_id: str = "LIVE",
        prediction_interval_s: float = 60.0,
        corridor_particles: int = 3000,
        dwell_dist: str = "gamma",
        config_prior_scale: float = 1.0,
        random_seed: Optional[int] = None,
    ):
        if prediction_interval_s <= 0:
            raise ValueError("prediction_interval_s must be > 0")
        if corridor_particles <= 0:
            raise ValueError("corridor_particles must be > 0")

        self.run_id = str(run_id)
        self.prediction_interval_s = float(prediction_interval_s)
        self.corridor_particles = int(corridor_particles)
        self.random_seed = None if random_seed is None else int(random_seed)

        self.stations = pd.read_csv(configured_stations_csv)
        self.stations["station_id"] = self.stations["station_id"].astype(str).str.strip()
        if "sensor_coverage" not in self.stations.columns:
            raise ValueError(
                "configured stations CSV must contain sensor_coverage. "
                "Run configure_stations.py first."
            )

        self.light = LightZoneRuntimeFeatureBuilder(self.stations)

        # The frozen bottleneck target is defined only for stations with a
        # positive waiting-buffer capacity.  Zero-buffer source stations (S01 in
        # the reference line) never had eligible labels during training, so they
        # are intentionally excluded from this model rather than forced through
        # an unknown categorical level.  Supporting them would require a target
        # redesign + retraining, not a runtime workaround.
        buffer_capacity = pd.to_numeric(self.stations["buffer_capacity"], errors="coerce")
        self.model_eligible_station_ids = set(
            self.stations.loc[buffer_capacity > 0, "station_id"].astype(str)
        )

        self.single_dark_ids, self.corridor_defs = derive_dark_topology(self.stations)
        self.dark_station_ids = set(self.single_dark_ids)
        for c in self.corridor_defs.values():
            self.dark_station_ids.update(c.sequence)

        self.station_to_corridor: dict[str, CorridorDefinition] = {}
        self.upstream_to_corridor: dict[str, CorridorDefinition] = {}
        self.downstream_to_corridor: dict[str, CorridorDefinition] = {}
        for c in self.corridor_defs.values():
            for sid in c.sequence:
                self.station_to_corridor[sid] = c
            if c.upstream_light_station is not None:
                self.upstream_to_corridor[c.upstream_light_station] = c
            if c.downstream_light_station is not None:
                self.downstream_to_corridor[c.downstream_light_station] = c

        units_df = pd.read_csv(units_csv)
        required_units = {"unit_id", "vehicle_model"}
        missing_units = required_units - set(units_df.columns)
        if missing_units:
            raise ValueError(
                "units.csv is missing required column(s): "
                + ", ".join(sorted(missing_units))
            )
        self.units = dict(
            zip(units_df["unit_id"].astype(str), units_df["vehicle_model"].astype(str))
        )

        self._api = None
        self.collector = None
        self.single_bridge = None
        self.corridor_bridge = None

        # Dark engine is only needed when at least one station is configured DARK.
        if self.dark_station_ids:
            if historical_dwell_csv is None:
                raise ValueError(
                    "At least one DARK station is configured, so historical_dwell_csv is required. "
                    "Use the existing Dark Zone historical-dwell generator on prior completed data."
                )
            hist_path = Path(historical_dwell_csv)
            if not hist_path.is_file():
                raise FileNotFoundError(f"historical_dwell.csv not found: {hist_path}")

            self._api = _dark_api(dark_zone_dir)
            models, self.config_prior_fallback_stations = self._api["load_dwell_models"](
                str(hist_path), self.stations, dwell_dist, config_prior_scale
            )
            self.collector = self._api["OutputCollector"]()

            if self.single_dark_ids:
                orchestrator = self._api["DarkZoneOrchestrator"](
                    models,
                    persistence=None,
                    auto_recover=False,
                    persist_mode="batched",
                )
                if self.random_seed is not None:
                    # Re-seed the newly spawned single-station PF *after* the
                    # unchanged orchestrator performs all of its normal guards/
                    # bookkeeping.  This hook changes only reproducibility when
                    # explicitly requested; the frozen PF/orchestrator source and
                    # default bottleneck behavior remain untouched.
                    original_spawn = orchestrator._spawn
                    base_seed = int(self.random_seed)
                    run_key = self.run_id

                    def _seeded_spawn(ev, _orig=original_spawn, _orch=orchestrator):
                        _orig(ev)
                        pf = _orch.active.get(ev.vehicle_id)
                        if pf is None:
                            return
                        payload = (
                            f"{base_seed}|{run_key}|single|{ev.station_id}|"
                            f"{ev.vehicle_id}|{float(ev.ts):.9f}"
                        )
                        seed_value = int.from_bytes(
                            hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest(), "big"
                        )
                        _orch.active[ev.vehicle_id] = type(pf)(
                            pf.dwell_dist, config=pf.cfg, rng=np.random.default_rng(seed_value)
                        )

                    orchestrator._spawn = _seeded_spawn
                self.single_bridge = self._api["SingleStationMLBridge"](
                    orchestrator=orchestrator,
                    stations=self.stations,
                    dwell_models=models,
                    run_id=self.run_id,
                    # We intentionally route UNIT_ARRIVED for isolated dark stations.
                    unit_arrived_stations=set(self.single_dark_ids),
                    # Runtime does not trust hidden raw cycle_time_ms from a dark station.
                    # On confirmed exit the bridge derives cycle time from boundary timestamps.
                    cycle_lookup={},
                    collector=self.collector,
                )

            if self.corridor_defs:
                zones = {
                    zid: self._api["ZoneSpec"](
                        zid,
                        list(c.sequence),
                        c.first_station,
                        c.downstream_light_station or "__LINE_END__",
                    )
                    for zid, c in self.corridor_defs.items()
                }
                residence_bundle = None
                if corridor_residence_csv is not None:
                    cr = Path(corridor_residence_csv)
                    if not cr.is_file():
                        raise FileNotFoundError(f"corridor_residence_csv not found: {cr}")
                    residence_bundle = self._api["load_corridor_residence_models"](
                        str(cr), dwell_dist
                    )

                self.corridor_bridge = self._api["CorridorMLBridge"](
                    self.stations,
                    models,
                    self.units,
                    zones,
                    self.run_id,
                    self.collector,
                    n_particles=self.corridor_particles,
                    residence_bundle=residence_bundle,
                    rng_seed=self.random_seed,
                )
        else:
            self.config_prior_fallback_stations = []

        self._next_event_sequence = 0
        self._last_input_timestamp_ms: Optional[int] = None

        # One shared periodic tick heap. Stale heap entries are ignored using
        # the next-tick dictionary, matching the Dark Zone offline harness.
        self._tick_heap: list[tuple[float, str, str]] = []  # (ts_s, path, vehicle_id)
        self._next_tick: dict[tuple[str, str], float] = {}

    # -------------------------- public introspection -----------------------

    @property
    def feature_names(self) -> list[str]:
        return list(BOTTLENECK_FEATURES)

    def topology_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "station_count": int(len(self.stations)),
            "light_stations": [
                sid for sid in self.stations["station_id"].astype(str)
                if sid not in self.dark_station_ids
            ],
            "single_dark_stations": sorted(self.single_dark_ids),
            "corridors": {
                zid: {
                    "sequence": list(c.sequence),
                    "first_station": c.first_station,
                    "last_station": c.last_station,
                    "upstream_light_station": c.upstream_light_station,
                    "downstream_light_station": c.downstream_light_station,
                }
                for zid, c in self.corridor_defs.items()
            },
            "feature_count": len(BOTTLENECK_FEATURES),
            "model_ineligible_stations": sorted(
                set(self.stations["station_id"].astype(str)) - self.model_eligible_station_ids
            ),
            "prediction_interval_s": self.prediction_interval_s,
            "corridor_particles": self.corridor_particles,
            "config_prior_fallback_stations": list(self.config_prior_fallback_stations),
        }

    def refresh_units(self, units_csv: str | Path) -> int:
        """Refresh unit->variant metadata during a concurrently running simulation."""
        frame = pd.read_csv(units_csv)
        required = {"unit_id", "vehicle_model"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError("units.csv missing required columns: " + ", ".join(sorted(missing)))
        before = len(self.units)
        self.units.update(
            dict(zip(frame["unit_id"].astype(str), frame["vehicle_model"].astype(str)))
        )
        return len(self.units) - before

    # -------------------------- event normalization -----------------------

    def _canonical_event(self, event: Mapping[str, Any] | pd.Series) -> dict[str, Any]:
        if isinstance(event, pd.Series):
            event = event.to_dict()
        else:
            event = dict(event)

        required = {"timestamp_ms", "station_id", "event_type"}
        missing = required - set(event)
        if missing:
            raise ValueError(
                "incoming station event is missing required field(s): "
                + ", ".join(sorted(missing))
            )

        try:
            t_ms = int(pd.to_numeric(event["timestamp_ms"], errors="raise"))
        except Exception as exc:
            raise ValueError(f"Invalid timestamp_ms: {event.get('timestamp_ms')!r}") from exc

        sid = str(event["station_id"]).strip()
        if sid not in set(self.stations["station_id"]):
            raise ValueError(f"Unknown station_id: {sid}")

        if self._last_input_timestamp_ms is not None and t_ms < self._last_input_timestamp_ms:
            raise ValueError(
                f"Out-of-order runtime event: {t_ms} < {self._last_input_timestamp_ms}. "
                "Events must reach the controller in nondecreasing timestamp order."
            )
        self._last_input_timestamp_ms = t_ms

        raw_seq = event.get("event_sequence")
        if raw_seq is None or (isinstance(raw_seq, float) and np.isnan(raw_seq)):
            seq = self._next_event_sequence
        else:
            seq = int(raw_seq)
        self._next_event_sequence = max(self._next_event_sequence, seq + 1)

        event["timestamp_ms"] = t_ms
        event["station_id"] = sid
        event["event_type"] = str(event["event_type"]).strip().upper()
        event["event_sequence"] = seq
        if event.get("unit_id") is not None and not pd.isna(event.get("unit_id")):
            event["unit_id"] = str(event["unit_id"])
        return event

    # -------------------------- output conversion -------------------------

    @staticmethod
    def _timestamp_to_ms(value: Any) -> int:
        ts = pd.to_datetime(value, utc=True)
        return int(ts.value // 1_000_000)

    def _dark_output_mark(self) -> tuple[int, int]:
        if self.collector is None:
            return 0, 0
        return len(self.collector.ml_rows), len(self.collector.dashboard_rows)

    def _new_dark_packets(self, mark: tuple[int, int]) -> list[FeaturePacket]:
        if self.collector is None:
            return []
        ml_start, dash_start = mark
        ml = self.collector.ml_rows[ml_start:]
        dash = self.collector.dashboard_rows[dash_start:]
        if len(ml) != len(dash):
            raise RuntimeError("Dark OutputCollector ML/dashboard row counts diverged")

        packets: list[FeaturePacket] = []
        for row, dashboard in zip(ml, dash):
            features = {name: row[name] for name in BOTTLENECK_FEATURES}
            station_id = str(features["station_id"])
            if station_id not in self.model_eligible_station_ids:
                continue
            zone_type = str(dashboard.get("zone_type", "dark"))
            route = "DARK_CORRIDOR" if zone_type == "corridor" else "DARK_SINGLE"
            packets.append(
                FeaturePacket(
                    run_id=self.run_id,
                    route=route,
                    trigger=str(row.get("trigger", dashboard.get("trigger", "dark"))),
                    station_id=station_id,
                    prediction_time_ms=self._timestamp_to_ms(row["prediction_time"]),
                    vehicle_id=str(row["vehicle_id"]) if row.get("vehicle_id") is not None else None,
                    features_28=features,
                    dashboard_state=dict(dashboard),
                )
            )
        return packets

    # -------------------------- tick scheduler ----------------------------

    def _schedule_tick(self, path: str, vehicle_id: str, ts_s: float) -> None:
        key = (path, str(vehicle_id))
        t = float(ts_s)
        self._next_tick[key] = t
        heapq.heappush(self._tick_heap, (t, path, str(vehicle_id)))

    def _cancel_tick(self, path: str, vehicle_id: str) -> None:
        self._next_tick.pop((path, str(vehicle_id)), None)

    def _is_active(self, path: str, vehicle_id: str) -> bool:
        vid = str(vehicle_id)
        if path == "single":
            return bool(self.single_bridge and vid in self.single_bridge.orch.active)
        if path == "corridor":
            return bool(self.corridor_bridge and vid in self.corridor_bridge.active)
        return False

    def _fire_tick(self, path: str, vehicle_id: str, ts_s: float) -> None:
        vid = str(vehicle_id)
        if path == "single":
            if self.single_bridge and vid in self.single_bridge.orch.active:
                self.single_bridge.tick_and_emit(vid, float(ts_s))
        elif path == "corridor":
            if self.corridor_bridge and vid in self.corridor_bridge.active:
                self.corridor_bridge.tick(vid, float(ts_s))
        else:
            raise ValueError(f"Unknown tick path: {path}")

    def advance_time(self, timestamp_ms: int, include_equal: bool = True) -> list[FeaturePacket]:
        """Advance periodic Dark predictions up to a causal wall-clock timestamp.

        A live event loop should call this on its heartbeat even if no station event
        arrives. ``process_event`` calls it automatically for ticks STRICTLY before
        the incoming event timestamp.
        """
        limit_s = int(timestamp_ms) / 1000.0
        mark = self._dark_output_mark()

        while self._tick_heap:
            tick_s, path, vid = self._tick_heap[0]
            due = tick_s <= limit_s if include_equal else tick_s < limit_s
            if not due:
                break
            heapq.heappop(self._tick_heap)
            key = (path, vid)
            if self._next_tick.get(key) != tick_s:
                continue  # stale rescheduled/cancelled heap entry
            if not self._is_active(path, vid):
                self._next_tick.pop(key, None)
                continue

            self._fire_tick(path, vid, tick_s)
            if self._is_active(path, vid):
                self._schedule_tick(path, vid, tick_s + self.prediction_interval_s)
            else:
                self._next_tick.pop(key, None)

        return self._new_dark_packets(mark)

    def _fire_exact_tick_for_vehicle(self, path: str, vehicle_id: str, ts_s: float) -> list[FeaturePacket]:
        """Ensure a tick due exactly at a confirmed exit is emitted before teardown."""
        key = (path, str(vehicle_id))
        due = self._next_tick.get(key)
        if due is None or abs(float(due) - float(ts_s)) > 1e-9:
            return []
        mark = self._dark_output_mark()
        self._fire_tick(path, str(vehicle_id), float(ts_s))
        # Invalidate the old heap entry; exit will cancel permanently just after this.
        self._next_tick.pop(key, None)
        return self._new_dark_packets(mark)

    # -------------------------- route handlers ----------------------------

    def _light_packet(self, event: dict[str, Any]) -> FeaturePacket:
        X, meta = self.light.process_event_with_metadata(event)
        features = X.iloc[0].to_dict()
        return FeaturePacket(
            run_id=self.run_id,
            route="LIGHT",
            trigger=str(event["event_type"]),
            station_id=str(event["station_id"]),
            prediction_time_ms=int(meta["prediction_time"]),
            vehicle_id=str(event["unit_id"]) if event.get("unit_id") is not None else None,
            event_id=str(event["event_id"]) if event.get("event_id") is not None else None,
            event_sequence=int(meta["prediction_event_sequence"]),
            features_28={name: features[name] for name in BOTTLENECK_FEATURES},
            dashboard_state=None,
        )

    @staticmethod
    def _has_dark_vehicle(event: Mapping[str, Any]) -> bool:
        vid = event.get("unit_id")
        if vid is None:
            return False
        try:
            if pd.isna(vid):
                return False
        except Exception:
            pass
        return bool(str(vid).strip())

    def _require_dark_vehicle(self, event: Mapping[str, Any]) -> str:
        vid = event.get("unit_id")
        if vid is None or (isinstance(vid, float) and np.isnan(vid)):
            raise ValueError(
                f"Dark boundary event {event.get('event_type')} at {event.get('station_id')} "
                "requires unit_id"
            )
        return str(vid)

    def _route_single(self, event: dict[str, Any]) -> list[FeaturePacket]:
        assert self.single_bridge is not None and self._api is not None
        sid = str(event["station_id"])
        typ = str(event["event_type"])
        t_ms = int(event["timestamp_ms"])
        t_s = t_ms / 1000.0
        mark = self._dark_output_mark()

        if typ == "UNIT_ARRIVED":
            self.single_bridge.observe_unit_arrived(sid, t_ms)
            return []

        if typ not in {"PROCESSING_STARTED", "PROCESSING_COMPLETED", "RFID_CHECKPOINT", "POWER_DRAW", "ANDON_SCAN"}:
            return []

        has_vehicle = self._has_dark_vehicle(event)
        if typ != "POWER_DRAW" or has_vehicle:
            vid = self._require_dark_vehicle(event)
        else:
            vid = ""
        EventType = self._api["EventType"]
        DarkZoneEvent = self._api["DarkZoneEvent"]

        if typ == "PROCESSING_STARTED":
            ev = DarkZoneEvent(
                event_type=EventType.STATION_ENTRY,
                vehicle_id=vid,
                station_id=sid,
                ts=t_s,
                variant=self.units.get(vid),
            )
            self.single_bridge.observe_engine_event(ev, emit=True)
            if vid in self.single_bridge.orch.active:
                self._schedule_tick("single", vid, t_s + self.prediction_interval_s)

        elif typ == "PROCESSING_COMPLETED":
            # If heartbeat and exit share the exact timestamp, preserve the offline
            # bridge's tick-before-exit semantics for this vehicle.
            exact = self._fire_exact_tick_for_vehicle("single", vid, t_s)
            # Reset the collector mark so the exact-time tick is not returned twice.
            mark = self._dark_output_mark()
            self.single_bridge.observe_engine_event(
                DarkZoneEvent(
                    event_type=EventType.STATION_EXIT,
                    vehicle_id=vid,
                    station_id=sid,
                    ts=t_s,
                    variant=self.units.get(vid),
                ),
                emit=True,
            )
            self._cancel_tick("single", vid)
            return exact + self._new_dark_packets(mark)

        else:
            progress = event.get("checkpoint_progress")
            if progress is None or (isinstance(progress, float) and np.isnan(progress)):
                # Explicit evidence without a physical progress mapping is unsafe.
                return []
            if typ == "POWER_DRAW" and not has_vehicle:
                self.single_bridge.apply_anonymous_power_draw(
                    sid, float(progress), t_s, sensor_std=0.12
                )
                return self._new_dark_packets(mark)
            mapped = {
                "RFID_CHECKPOINT": EventType.RFID_CHECKPOINT,
                "POWER_DRAW": EventType.POWER_DRAW,
                "ANDON_SCAN": EventType.ANDON_SCAN,
            }[typ]
            self.single_bridge.observe_engine_event(
                DarkZoneEvent(
                    event_type=mapped,
                    vehicle_id=vid,
                    station_id=sid,
                    ts=t_s,
                    variant=self.units.get(vid),
                    checkpoint_progress=float(progress),
                ),
                emit=True,
            )

        return self._new_dark_packets(mark)

    def _route_corridor(self, event: dict[str, Any], corridor: CorridorDefinition) -> list[FeaturePacket]:
        assert self.corridor_bridge is not None
        sid = str(event["station_id"])
        typ = str(event["event_type"])
        t_s = int(event["timestamp_ms"]) / 1000.0
        mark = self._dark_output_mark()

        # IMPORTANT: only observable boundary/evidence events are admitted.
        # For a normal corridor, the upstream LIGHT completion is the entry
        # boundary. That timestamp is also the arrival to the first DARK buffer,
        # so vehicles waiting there are part of the PF state before processing
        # starts. Internal raw queue/cycle/process events remain ignored.
        is_upstream_entry = (
            corridor.upstream_light_station is not None
            and sid == corridor.upstream_light_station
            and typ == "PROCESSING_COMPLETED"
        )
        is_line_start_fallback = (
            corridor.upstream_light_station is None
            and sid == corridor.first_station
            and typ == "PROCESSING_STARTED"
        )
        is_simulator_boundary_entry = (
            sid == corridor.first_station and typ == "DARK_ZONE_ENTERED"
        )
        if is_upstream_entry or is_line_start_fallback or is_simulator_boundary_entry:
            vid = self._require_dark_vehicle(event)
            if vid not in self.corridor_bridge.active:
                self.corridor_bridge.enter(vid, corridor.zone_id, t_s)
                if vid in self.corridor_bridge.active:
                    self._schedule_tick("corridor", vid, t_s + self.prediction_interval_s)
            return self._new_dark_packets(mark)

        is_simulator_boundary_exit = (
            corridor.downstream_light_station is not None
            and sid == corridor.downstream_light_station
            and typ == "DARK_ZONE_EXITED"
        )
        if (sid == corridor.last_station and typ == "PROCESSING_COMPLETED") or is_simulator_boundary_exit:
            vid = self._require_dark_vehicle(event)
            exact = self._fire_exact_tick_for_vehicle("corridor", vid, t_s)
            # Reset the collector mark so the exact-time tick is not returned twice.
            mark = self._dark_output_mark()
            self.corridor_bridge.exit(vid, corridor.zone_id, t_s)
            self._cancel_tick("corridor", vid)
            return exact + self._new_dark_packets(mark)

        # Optional explicit checkpoint evidence may be routed when the upstream
        # event actually carries a trusted physical progress mapping.
        if typ in {"RFID_CHECKPOINT", "POWER_DRAW", "ANDON_SCAN"}:
            progress = event.get("checkpoint_progress")
            if progress is not None and not (isinstance(progress, float) and np.isnan(progress)):
                sensor_std = {
                    "RFID_CHECKPOINT": 0.05,
                    "POWER_DRAW": 0.12,
                    "ANDON_SCAN": 0.03,
                }[typ]
                if typ == "POWER_DRAW" and not self._has_dark_vehicle(event):
                    self.corridor_bridge.apply_anonymous_checkpoint(
                        sid, float(progress), t_s, sensor_std=sensor_std
                    )
                else:
                    vid = self._require_dark_vehicle(event)
                    self.corridor_bridge.apply_checkpoint(
                        vid, sid, float(progress), t_s, sensor_std=sensor_std
                    )
                return self._new_dark_packets(mark)

        return []

    # -------------------------- main public route -------------------------

    def process_event(self, event: Mapping[str, Any] | pd.Series) -> list[FeaturePacket]:
        """Consume one incoming station event and return zero or more model packets.

        Why a LIST? A station event can arrive after one or more periodic Dark PF
        ticks became due, so those causal predictions are returned first, followed
        by the prediction produced directly by this event (if any).
        """
        e = self._canonical_event(event)
        t_ms = int(e["timestamp_ms"])

        packets = self.advance_time(t_ms, include_equal=False)
        sid = str(e["station_id"])
        typ = str(e["event_type"])

        # The C++ simulator represents a hidden corridor with its public
        # DARK_ZONE_ENTERED/DARK_ZONE_EXITED boundary records. They are control
        # boundaries, not ordinary LIGHT station observations.
        if typ == "DARK_ZONE_EXITED":
            corridor = self.downstream_to_corridor.get(sid)
            if corridor is not None:
                packets.extend(self._route_corridor(e, corridor))
                return packets

        if sid not in self.dark_station_ids:
            # Only stations eligible under the frozen target/model contract are
            # emitted. Zero-buffer source stations (for example S01) never had
            # eligible training labels and are intentionally excluded.
            if sid in self.model_eligible_station_ids:
                packets.append(self._light_packet(e))

            # A LIGHT station immediately upstream of a DARK corridor is also
            # the observable corridor-entry boundary on PROCESSING_COMPLETED.
            corridor = self.upstream_to_corridor.get(sid)
            if corridor is not None:
                packets.extend(self._route_corridor(e, corridor))
            return packets

        if sid in self.single_dark_ids:
            packets.extend(self._route_single(e))
            return packets

        corridor = self.station_to_corridor[sid]
        packets.extend(self._route_corridor(e, corridor))
        return packets

    def process_evidence_event(self, event: Mapping[str, Any]) -> list[FeaturePacket]:
        """Route an explicit Dark checkpoint event not carried in station_events.csv.

        Expected fields: timestamp_ms, station_id, event_type and
        checkpoint_progress. RFID_CHECKPOINT/ANDON_SCAN require unit_id;
        POWER_DRAW may omit it and is then treated as population-level evidence.
        This keeps optional checkpoint/manual streams separate from the core
        station-event contract.
        """
        e = dict(event)
        typ = str(e.get("event_type", "")).strip().upper()
        if typ not in {"RFID_CHECKPOINT", "POWER_DRAW", "ANDON_SCAN"}:
            raise ValueError("process_evidence_event only accepts checkpoint evidence")
        if "checkpoint_progress" not in e:
            raise ValueError("Checkpoint evidence event requires checkpoint_progress")

        # Checkpoints outside DARK topology are legitimate simulator evidence
        # (for example the default factory's final RFID gate), but they are not
        # model training/prediction events.  Advance the causal DARK heartbeat
        # clock without sending the evidence through the LIGHT feature builder.
        sid = str(e.get("station_id", "")).strip()
        if sid not in self.dark_station_ids:
            canonical = self._canonical_event(e)
            return self.advance_time(int(canonical["timestamp_ms"]), include_equal=False)

        return self.process_event(e)

    def dark_state_snapshot(self, timestamp_ms: int) -> list[dict[str, Any]]:
        """Return causal active DARK-track beliefs at ``timestamp_ms``.

        This is an observation-only integration surface for parallel consumers.
        It exposes PF posterior summaries, never simulator hidden truth.
        """
        t_ms = int(timestamp_ms)
        self.advance_time(t_ms, include_equal=False)
        t_s = t_ms / 1000.0
        rows: list[dict[str, Any]] = []

        if self.single_bridge is not None:
            for vid in sorted(self.single_bridge.orch.active):
                pf = self.single_bridge.orch.active[vid]
                last = float(self.single_bridge.orch.last_event_ts.get(vid, t_s))
                dt = max(0.0, t_s - last)
                if dt > 0:
                    pf.predict(dt)
                    self.single_bridge.orch.last_event_ts[vid] = t_s
                meta = self.single_bridge.orch.meta.get(vid, {})
                sid = str(meta.get("station", ""))
                est = pf.estimate()
                rows.append({
                    "vehicle_id": str(vid),
                    "route": "DARK_SINGLE",
                    "zone_id": f"DZ_{sid}",
                    "station_probs": {sid: 1.0},
                    "most_likely_station": sid,
                    "state_confidence": float(est.get("render_confidence", 0.0)),
                    "progress_mean": float(est.get("progress_mean", float("nan"))),
                })

        if self.corridor_bridge is not None:
            for zid in self.corridor_bridge.zones:
                self.corridor_bridge._advance_zone(zid, t_s)
            for vid, state in sorted(self.corridor_bridge.active.items()):
                est = state.mpf.estimate()
                rows.append({
                    "vehicle_id": str(vid),
                    "route": "DARK_CORRIDOR",
                    "zone_id": str(state.zone.zone_id),
                    "station_probs": dict(est["station_probs"]),
                    "most_likely_station": str(est["most_likely_station"]),
                    "state_confidence": float(est["confidence"]),
                    "progress_mean": float(est["progress_in_station_mean"]),
                })
        return rows

    def observe_anonymous_dark_station(
        self, station_id: str, timestamp_ms: int, *, wrong_station_floor: float = 0.05
    ) -> dict[str, float]:
        """Apply anonymous station-only evidence and return unit associations.

        Used by the parallel defect consumer for observable sensor telemetry in
        DARK corridors.  It never consumes sensor value or hidden processing
        state; only the public station location is used as PF evidence.
        """
        sid = str(station_id).strip()
        t_ms = int(timestamp_ms)
        self.advance_time(t_ms, include_equal=False)
        if sid not in self.dark_station_ids:
            return {}

        if sid in self.single_dark_ids:
            snapshots = [r for r in self.dark_state_snapshot(t_ms) if r["most_likely_station"] == sid]
            if not snapshots:
                return {}
            weight = 1.0 / len(snapshots)
            return {str(r["vehicle_id"]): weight for r in snapshots}

        corridor = self.station_to_corridor[sid]
        if self.corridor_bridge is None:
            return {}
        return self.corridor_bridge.apply_anonymous_station_evidence(
            sid, t_ms / 1000.0, wrong_station_floor=float(wrong_station_floor)
        )

    def flush_dark_state(self) -> None:
        """Flush Dark persistence if a persistence backend is later enabled."""
        if self.single_bridge is not None:
            self.single_bridge.orch.flush()

    # -------------------------- replay/validation helper ------------------

    def replay_station_events(self, events: pd.DataFrame) -> list[FeaturePacket]:
        """Replay a completed station_events DataFrame through the LIVE router.

        This is a validation helper only; live use should call process_event as rows
        arrive and call advance_time from the process heartbeat.
        """
        required = {"timestamp_ms", "station_id", "event_type"}
        missing = required - set(events.columns)
        if missing:
            raise ValueError(
                "station_events data is missing: " + ", ".join(sorted(missing))
            )
        out: list[FeaturePacket] = []
        for _, row in events.iterrows():
            out.extend(self.process_event(row))
        return out


# ---------------------------------------------------------------------------
# CLI replay utility (validation, not the production event bus)
# ---------------------------------------------------------------------------


def _packets_to_frame(packets: list[FeaturePacket]) -> pd.DataFrame:
    rows = []
    for p in packets:
        rows.append({
            "run_id": p.run_id,
            "route": p.route,
            "trigger": p.trigger,
            "station_id_buffer_id": p.station_id,
            "prediction_time": p.prediction_time_ms,
            "vehicle_id": p.vehicle_id,
            "event_id": p.event_id,
            "prediction_event_sequence": p.event_sequence,
            **p.features_28,
        })
    columns = [
        "run_id", "route", "trigger", "station_id_buffer_id", "prediction_time",
        "vehicle_id", "event_id", "prediction_event_sequence",
    ] + BOTTLENECK_FEATURES
    return pd.DataFrame(rows, columns=columns)


def main() -> int:
    ap = argparse.ArgumentParser(description="Digital Twin Light/Dark runtime event router")
    ap.add_argument("--stations", required=True, type=Path, help="Configured stations CSV")
    ap.add_argument("--events", required=True, type=Path, help="station_events.csv for replay validation")
    ap.add_argument("--units", required=True, type=Path)
    ap.add_argument("--dark-zone-dir", required=True, type=Path,
                    help="Directory containing dark_zone_ml_bridge.py, orchestrator.py, etc.")
    ap.add_argument("--historical-dwell", type=Path, default=None)
    ap.add_argument("--corridor-residence", type=Path, default=None)
    ap.add_argument("--run-id", default="REPLAY")
    ap.add_argument("--prediction-interval-s", type=float, default=60.0)
    ap.add_argument("--corridor-particles", type=int, default=3000)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--dashboard-output", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    args = ap.parse_args()

    controller = DigitalTwinRuntimeController(
        configured_stations_csv=args.stations,
        units_csv=args.units,
        dark_zone_dir=args.dark_zone_dir,
        historical_dwell_csv=args.historical_dwell,
        corridor_residence_csv=args.corridor_residence,
        run_id=args.run_id,
        prediction_interval_s=args.prediction_interval_s,
        corridor_particles=args.corridor_particles,
    )

    events = pd.read_csv(args.events)
    packets = controller.replay_station_events(events)
    out = _packets_to_frame(packets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)

    if args.dashboard_output is not None:
        dashboard_rows = [
            p.dashboard_state for p in packets if p.dashboard_state is not None
        ]
        args.dashboard_output.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(dashboard_rows).to_csv(args.dashboard_output, index=False)

    summary = {
        **controller.topology_summary(),
        "input_events": int(len(events)),
        "feature_packets": int(len(packets)),
        "packets_by_route": {
            str(k): int(v) for k, v in out["route"].value_counts().items()
        } if len(out) else {},
        "output": str(args.output),
        "xgboost_called": False,
    }
    summary_path = args.summary or args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"Wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
