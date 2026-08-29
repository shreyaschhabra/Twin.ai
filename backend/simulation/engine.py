"""
FactoryEngine: builds a runnable SimPy simulation entirely from a
FactoryConfig. No station-count assumptions, no hardcoded station ids —
everything about topology, routing, and processing times comes from
config. The same engine runs configs/development_line.yaml today and
configs/full_line.yaml later without changes here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import simpy

from backend.config.schemas import FactoryConfig
from backend.simulation.buffer import SimBuffer
from backend.simulation.events import Event, EventLog, EventType
from backend.simulation.genealogy import StationVisitRecord, build_genealogy
from backend.simulation.station import StationRuntime
from backend.simulation.vehicle import Vehicle

# Illustrative simulation assumption: how many vehicles may queue before the
# very first station(s) of the line before the vehicle generator itself
# blocks. Not part of the Step 1 config (which only defines inter-station
# buffers); documented here and in ASSUMPTIONS.md.
DEFAULT_ENTRY_BUFFER_CAPACITY = 20

DEFAULT_VARIANT_MIX = {"ICE_SEDAN": 0.45, "ICE_SUV": 0.35, "EV": 0.20}


@dataclass
class RunResult:
    events: List[Event]
    vehicles: Dict[str, Vehicle]
    genealogy: Dict[str, List[StationVisitRecord]]
    summary: dict = field(default_factory=dict)


class FactoryEngine:
    def __init__(
        self,
        config: FactoryConfig,
        seed: int,
        entry_buffer_capacity: int = DEFAULT_ENTRY_BUFFER_CAPACITY,
    ):
        self.config = config
        self.rng = random.Random(seed)
        self.env = simpy.Environment()
        self.event_log = EventLog()
        self.vehicles: Dict[str, Vehicle] = {}

        self.entry_stations = sorted({v.route[0] for v in config.vehicle_variants.values()})

        self.buffers: Dict[str, SimBuffer] = {
            buffer_id: SimBuffer(self.env, buffer_id, buf_cfg.capacity)
            for buffer_id, buf_cfg in config.buffers.items()
        }
        self.entry_buffers: Dict[str, SimBuffer] = {
            station_id: SimBuffer(self.env, f"ENTRY::{station_id}", entry_buffer_capacity)
            for station_id in self.entry_stations
        }

        # outgoing edge lookup: (station_id, next_station_id) -> buffer
        self.outgoing_buffer: Dict[Tuple[str, str], SimBuffer] = {
            (buf_cfg.upstream_station, buf_cfg.downstream_station): self.buffers[buffer_id]
            for buffer_id, buf_cfg in config.buffers.items()
        }
        # per-station outgoing lookup keyed just by next_station_id, since a
        # given station's outgoing edges always go to distinct next stations
        self.outgoing_by_station: Dict[str, Dict[str, SimBuffer]] = {}
        for (upstream, downstream), buf in self.outgoing_buffer.items():
            self.outgoing_by_station.setdefault(upstream, {})[downstream] = buf

        # incoming buffers per station (regular buffers + entry buffer)
        self.incoming_buffers: Dict[str, List[SimBuffer]] = {sid: [] for sid in config.stations}
        for buffer_id, buf_cfg in config.buffers.items():
            self.incoming_buffers[buf_cfg.downstream_station].append(self.buffers[buffer_id])
        for station_id, entry_buf in self.entry_buffers.items():
            self.incoming_buffers[station_id].append(entry_buf)

        self.station_runtimes: Dict[str, StationRuntime] = {
            station_id: StationRuntime(
                env=self.env,
                station_cfg=station_cfg,
                config=config,
                input_buffers=self.incoming_buffers[station_id],
                outgoing_buffer_lookup=self.outgoing_by_station.get(station_id, {}),
                event_log=self.event_log,
                rng=self.rng,
            )
            for station_id, station_cfg in config.stations.items()
        }

    def run(
        self,
        n_vehicles: int,
        mean_interarrival_seconds: float,
        std_interarrival_seconds: float,
        variant_mix: Optional[Dict[str, float]] = None,
    ) -> RunResult:
        variant_mix = variant_mix or DEFAULT_VARIANT_MIX

        for runtime in self.station_runtimes.values():
            self.env.process(runtime.run())
        self.env.process(
            self._vehicle_generator(
                n_vehicles, mean_interarrival_seconds, std_interarrival_seconds, variant_mix
            )
        )

        self.env.run()

        for runtime in self.station_runtimes.values():
            runtime.finalize_idle()

        genealogy = build_genealogy(self.event_log.events)
        summary = self._build_summary()
        return RunResult(
            events=self.event_log.events,
            vehicles=self.vehicles,
            genealogy=genealogy,
            summary=summary,
        )

    def _vehicle_generator(
        self,
        n_vehicles: int,
        mean_interarrival: float,
        std_interarrival: float,
        variant_mix: Dict[str, float],
    ):
        variant_ids = list(variant_mix.keys())
        weights = list(variant_mix.values())

        for i in range(1, n_vehicles + 1):
            interarrival = max(
                self.rng.gauss(mean_interarrival, std_interarrival),
                mean_interarrival * 0.3,
            )
            yield self.env.timeout(interarrival)

            variant_id = self.rng.choices(variant_ids, weights=weights, k=1)[0]
            vehicle_id = f"V{i:05d}"
            route = list(self.config.vehicle_variants[variant_id].route)
            vehicle = Vehicle(
                vehicle_id=vehicle_id,
                variant_id=variant_id,
                route=route,
                created_at=self.env.now,
            )
            self.vehicles[vehicle_id] = vehicle
            self.event_log.record(
                EventType.VEHICLE_CREATED,
                simulation_time=self.env.now,
                vehicle_id=vehicle_id,
                vehicle_variant=variant_id,
                route_position=0,
            )

            entry_station = route[0]
            entry_buf = self.entry_buffers[entry_station]
            while entry_buf.is_full():
                yield entry_buf.space_available
            entry_buf.put(vehicle, self.env.now)
            self.event_log.record(
                EventType.VEHICLE_ENTERED_BUFFER,
                simulation_time=self.env.now,
                vehicle_id=vehicle_id,
                vehicle_variant=variant_id,
                station_id=entry_station,
                buffer_id=entry_buf.buffer_id,
                route_position=0,
                occupancy=len(entry_buf.items),
            )

    def _build_summary(self) -> dict:
        events = self.event_log.events
        sim_end = events[-1].simulation_time if events else 0.0

        completed = [v for v in self.vehicles.values() if v.completed]
        by_variant: Dict[str, int] = {}
        for v in self.vehicles.values():
            by_variant[v.variant_id] = by_variant.get(v.variant_id, 0) + 1

        total_time_in_system = [
            v.completed_at - v.created_at for v in completed if v.completed_at is not None
        ]

        processing_counts: Dict[str, int] = {sid: rt.processed_count for sid, rt in self.station_runtimes.items()}

        proc_time_sums: Dict[str, float] = {sid: 0.0 for sid in self.config.stations}
        proc_time_counts: Dict[str, int] = {sid: 0 for sid in self.config.stations}
        for e in events:
            if e.event_type == EventType.STATION_PROCESSING_COMPLETED.value:
                proc_time_sums[e.station_id] += e.value
                proc_time_counts[e.station_id] += 1
        avg_processing_time = {
            sid: (proc_time_sums[sid] / proc_time_counts[sid]) if proc_time_counts[sid] else 0.0
            for sid in self.config.stations
        }

        state_time = _integrate_state_durations(events, self.config.stations.keys(), sim_end)

        max_buffer_occupancy = {bid: buf.max_occupancy for bid, buf in self.buffers.items()}

        utilization = {
            sid: (state_time[sid].get("PROCESSING", 0.0) / sim_end) if sim_end else 0.0
            for sid in self.config.stations
        }

        return {
            "vehicles_generated": len(self.vehicles),
            "vehicles_completed": len(completed),
            "vehicles_by_variant": by_variant,
            "simulated_duration_seconds": sim_end,
            "throughput_vehicles_per_hour": (len(completed) / sim_end * 3600) if sim_end else 0.0,
            "avg_time_in_system_seconds": (
                sum(total_time_in_system) / len(total_time_in_system) if total_time_in_system else 0.0
            ),
            "station_utilization": utilization,
            "processing_counts_per_station": processing_counts,
            "avg_processing_time_per_station": avg_processing_time,
            "max_buffer_occupancy": max_buffer_occupancy,
            "blocked_time_per_station": {sid: state_time[sid].get("BLOCKED", 0.0) for sid in self.config.stations},
            "starved_time_per_station": {sid: state_time[sid].get("STARVED", 0.0) for sid in self.config.stations},
        }


def _integrate_state_durations(events: List[Event], station_ids, sim_end: float) -> Dict[str, Dict[str, float]]:
    """Sum time spent in each state per station by integrating between
    consecutive STATION_STATE_CHANGED events, from each station's first
    transition through the end of the simulation."""
    durations: Dict[str, Dict[str, float]] = {sid: {} for sid in station_ids}
    last_state: Dict[str, str] = {}
    last_time: Dict[str, float] = {}

    for e in events:
        if e.event_type != EventType.STATION_STATE_CHANGED.value:
            continue
        sid = e.station_id
        if sid in last_state:
            elapsed = e.simulation_time - last_time[sid]
            durations[sid][last_state[sid]] = durations[sid].get(last_state[sid], 0.0) + elapsed
        last_state[sid] = e.to_state
        last_time[sid] = e.simulation_time

    for sid, state in last_state.items():
        elapsed = sim_end - last_time[sid]
        durations[sid][state] = durations[sid].get(state, 0.0) + elapsed

    return durations


def run_simulation(
    config: FactoryConfig,
    n_vehicles: int,
    seed: int,
    mean_interarrival_seconds: float = 200.0,
    std_interarrival_seconds: float = 20.0,
    variant_mix: Optional[Dict[str, float]] = None,
    entry_buffer_capacity: int = DEFAULT_ENTRY_BUFFER_CAPACITY,
) -> RunResult:
    engine = FactoryEngine(config, seed=seed, entry_buffer_capacity=entry_buffer_capacity)
    return engine.run(
        n_vehicles=n_vehicles,
        mean_interarrival_seconds=mean_interarrival_seconds,
        std_interarrival_seconds=std_interarrival_seconds,
        variant_mix=variant_mix,
    )
