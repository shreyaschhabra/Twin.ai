"""
Station runtime: the SimPy process loop for one physical station.

STATE SEMANTICS (as approved for Step 2, DOWN now used starting Step 3):

  IDLE       Before the station has ever received a vehicle, and again once
             the shift has genuinely ended (no more vehicles will ever
             arrive). Never used as a mid-shift "nothing to do right now"
             state — that is STARVED.
  STARVED    Station is ready to process but has no vehicle currently
             available from any of its input buffers. Ends the instant a
             vehicle becomes available.
  PROCESSING Station is actively running a vehicle through its cycle time.
  BLOCKED    Station finished processing a vehicle but the required
             downstream buffer is at capacity, so the vehicle cannot be
             released. The station holds that exact vehicle and does NOT
             begin processing a new one until the downstream buffer frees
             a slot — this is enforced structurally by the loop below
             (there is no code path that acquires a new vehicle while a
             previous one is still being held pending release).
  DOWN       A micro-stop scenario interrupting an in-progress vehicle
             (Step 3). The station holds the vehicle it already acquired;
             no new vehicle can be acquired until DOWN resolves back to
             PROCESSING, for the same structural reason as BLOCKED.

State transitions are only logged when the state actually changes — no
repeated identical-state logging on every simulated tick.

Scenario integration (Step 3): station code never branches on station_id
or scenario family. It asks `scenario_manager` (a no-op `empty_manager()`
when no scenarios are configured, so there's never a None-check needed)
for an effect bundle, a possible batch assignment, and possible micro-stop
parameters, and applies whatever comes back generically.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

import simpy

from backend.config.schemas import FactoryConfig, StationInstance
from backend.simulation.buffer import SimBuffer
from backend.simulation.events import EventLog, EventType
from backend.simulation.material_batches import MaterialBatchScheduler
from backend.simulation.rng import RNGStreamFactory
from backend.simulation.scenarios.effects import StationEffectBundle
from backend.simulation.scenarios.manager import ScenarioManager
from backend.simulation.sensors import SensorModelRegistry, generate_sensor_readings
from backend.simulation.vehicle import Vehicle


class StationState(str, Enum):
    IDLE = "IDLE"
    STARVED = "STARVED"
    PROCESSING = "PROCESSING"
    BLOCKED = "BLOCKED"
    DOWN = "DOWN"


class StationRuntime:
    """Holds a station's live state plus the SimPy process generator that
    drives it. All routing/buffer decisions come from FactoryConfig — no
    station-count or station-id assumptions live here."""

    def __init__(
        self,
        env: simpy.Environment,
        station_cfg: StationInstance,
        config: FactoryConfig,
        input_buffers: List[SimBuffer],
        outgoing_buffer_lookup: Dict[str, SimBuffer],
        event_log: EventLog,
        rng_factory: RNGStreamFactory,
        scenario_manager: ScenarioManager,
        sensor_models: SensorModelRegistry,
        material_batches: MaterialBatchScheduler,
    ):
        if station_cfg.capacity != 1:
            raise NotImplementedError(
                f"station '{station_cfg.station_id}' has capacity="
                f"{station_cfg.capacity}; this engine only implements "
                f"single-slot (capacity=1) stations. Multi-slot concurrent "
                f"stations are a documented future extension (state "
                f"semantics like BLOCKED become per-slot, not per-station), "
                f"not built now since no current config needs it."
            )
        self.env = env
        self.station_cfg = station_cfg
        self.config = config
        self.input_buffers = input_buffers
        self.outgoing_buffer_lookup = outgoing_buffer_lookup
        self.event_log = event_log
        self.rng_factory = rng_factory
        self.processing_rng = rng_factory.get(f"processing_time::{station_cfg.station_id}")
        self.micro_stop_rng = rng_factory.get(f"micro_stop::{station_cfg.station_id}")
        self.scenario_manager = scenario_manager
        self.sensor_models = sensor_models
        self.material_batches = material_batches
        self.state = StationState.IDLE
        self.processed_count = 0

    def _set_state(self, new_state: StationState) -> None:
        if new_state == self.state:
            return
        self.event_log.record(
            EventType.STATION_STATE_CHANGED,
            simulation_time=self.env.now,
            station_id=self.station_cfg.station_id,
            from_state=self.state.value,
            to_state=new_state.value,
        )
        self.state = new_state

    def finalize_idle(self) -> None:
        """Called once after the run completes: a station's natural resting
        state once no more vehicles will ever arrive is IDLE, not an
        eternal STARVED wait. Only fires if the station is actually parked
        waiting (STARVED) — a station left BLOCKED, DOWN, or PROCESSING at
        run end indicates a deadlock/bug, not a normal shift end, and is
        left as-is so tests can catch it."""
        if self.state == StationState.STARVED:
            self._set_state(StationState.IDLE)

    def compute_processing_time(self, variant_id: str, effects: StationEffectBundle) -> float:
        override = self.station_cfg.variant_overrides.get(variant_id)
        if override is not None and override.cycle_time_multiplier is not None:
            variant_multiplier = override.cycle_time_multiplier
        else:
            variant_cfg = self.config.vehicle_variants[variant_id]
            variant_multiplier = variant_cfg.processing_time_modifiers.get(
                self.station_cfg.station_id, 1.0
            )
        mean = self.station_cfg.baseline_cycle_time_seconds * variant_multiplier * effects.cycle_time_multiplier
        std = mean * self.station_cfg.cycle_time_variability * effects.variability_multiplier
        if std <= 0:
            return mean
        # Truncated-normal-with-floor: a simple, bounded stochastic method
        # (illustrative simulation assumption, documented in ASSUMPTIONS.md)
        # chosen specifically to guarantee processing time stays comfortably
        # positive without needing a more sophisticated distribution.
        value = self.processing_rng.gauss(mean, std)
        floor = mean * 0.3
        return max(value, floor)

    def run(self):
        """The station's SimPy process: acquire -> process -> release, in a
        single sequential loop. Because this loop is sequential and never
        starts a new acquire while still holding a vehicle pending release,
        BLOCKED/DOWN and single-vehicle-at-a-time are enforced structurally,
        not by extra locking."""
        station_id = self.station_cfg.station_id

        while True:
            # ---- acquire (STARVED while nothing is available) ----
            vehicle, enqueue_time = yield from self._acquire_vehicle()

            self._set_state(StationState.PROCESSING)
            vehicle.current_station = station_id
            self.event_log.record(
                EventType.VEHICLE_ENTERED_STATION,
                simulation_time=self.env.now,
                vehicle_id=vehicle.vehicle_id,
                vehicle_variant=vehicle.variant_id,
                station_id=station_id,
                route_position=vehicle.position,
            )

            effects = self.scenario_manager.get_station_effects(self.env.now, station_id, vehicle.vehicle_id)

            # Baseline material-batch assignment: EVERY vehicle at a
            # batch-relevant station gets a neutral, observable batch_id,
            # regardless of whether any scenario exists (Step 3 patch 2).
            # A BAD_BATCH scenario never changes this assignment — it only
            # decides, purely latently, whether the already-assigned id is
            # quality-degraded (check_batch_exposure below).
            if self.material_batches.is_relevant(station_id):
                batch_id = self.material_batches.assign(station_id)
                self.event_log.record(
                    EventType.MATERIAL_BATCH_ASSIGNED,
                    simulation_time=self.env.now,
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_variant=vehicle.variant_id,
                    station_id=station_id,
                    batch_id=batch_id,
                )
                self.scenario_manager.check_batch_exposure(vehicle.vehicle_id, self.env.now, station_id, batch_id)

            # ---- processing, with a possible mid-processing micro-stop interruption ----
            # Chronology (Step 3 patch 1): STARTED -> PROCESSING -> [DOWN ->
            # MICRO_STOP_OCCURRED -> PROCESSING] -> COMPLETED. The vehicle
            # is already "at the station" (VEHICLE_ENTERED_STATION already
            # logged above) before any micro-stop check runs, so the delay
            # can never leak into upstream queue waiting_time — it only
            # ever extends processing_completion_time.
            proc_time = self.compute_processing_time(vehicle.variant_id, effects)
            self.event_log.record(
                EventType.STATION_PROCESSING_STARTED,
                simulation_time=self.env.now,
                vehicle_id=vehicle.vehicle_id,
                station_id=station_id,
                value=proc_time,
            )

            micro_stop_duration = yield from self._maybe_run_micro_stop(station_id, vehicle)

            yield self.env.timeout(proc_time)
            self.processed_count += 1
            total_time = proc_time + micro_stop_duration
            self.event_log.record(
                EventType.STATION_PROCESSING_COMPLETED,
                simulation_time=self.env.now,
                vehicle_id=vehicle.vehicle_id,
                station_id=station_id,
                value=total_time,
            )

            generate_sensor_readings(
                station_cfg=self.station_cfg,
                vehicle=vehicle,
                sim_time=self.env.now,
                effects=effects,
                sensor_models=self.sensor_models,
                rng_factory=self.rng_factory,
                event_log=self.event_log,
            )

            # ---- release (BLOCKED if downstream buffer is full) ----
            if vehicle.is_last_station():
                vehicle.completed = True
                vehicle.completed_at = self.env.now
                vehicle.current_station = None
                self.event_log.record(
                    EventType.VEHICLE_COMPLETED_LINE,
                    simulation_time=self.env.now,
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_variant=vehicle.variant_id,
                    station_id=station_id,
                )
            else:
                next_station_id = vehicle.next_station_id()
                out_buffer = self.outgoing_buffer_lookup[next_station_id]
                if out_buffer.is_full():
                    self._set_state(StationState.BLOCKED)
                    while out_buffer.is_full():
                        yield out_buffer.space_available
                vehicle.position += 1
                vehicle.current_station = None
                out_buffer.put(vehicle, self.env.now)
                self.event_log.record(
                    EventType.VEHICLE_ENTERED_BUFFER,
                    simulation_time=self.env.now,
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_variant=vehicle.variant_id,
                    station_id=next_station_id,
                    buffer_id=out_buffer.buffer_id,
                    route_position=vehicle.position,
                    occupancy=len(out_buffer.items),
                )
            # loop back to top; next iteration's acquire will correctly
            # report STARVED or immediately PROCESSING depending on
            # whether another vehicle is already waiting.

    def _maybe_run_micro_stop(self, station_id: str, vehicle: Vehicle):
        """Rolls (using this station's own isolated micro_stop RNG stream)
        whether a currently-active micro-stop scenario interrupts the
        vehicle already being processed (STATION_PROCESSING_STARTED has
        already been logged by the caller). If it fires: transitions
        PROCESSING -> DOWN, logs an observable MICRO_STOP_OCCURRED event
        with its duration, blocks for that duration, then transitions back
        DOWN -> PROCESSING before returning control. The station cannot
        acquire a different vehicle meanwhile — same structural guarantee
        as BLOCKED. Returns the micro-stop duration (0.0 if none fired) so
        the caller can fold it into the observed total processing time.
        No effect at all when no micro-stop scenario is active (params is
        None), so a no-scenario run never touches this RNG stream."""
        params = self.scenario_manager.get_micro_stop_params(self.env.now, station_id)
        if params is None:
            return 0.0
        if self.micro_stop_rng.random() >= params["probability"]:
            return 0.0

        duration = self.micro_stop_rng.uniform(params["min_duration"], params["max_duration"])
        self._set_state(StationState.DOWN)
        self.event_log.record(
            EventType.MICRO_STOP_OCCURRED,
            simulation_time=self.env.now,
            station_id=station_id,
            vehicle_id=vehicle.vehicle_id,
            vehicle_variant=vehicle.variant_id,
            value=duration,
        )
        yield self.env.timeout(duration)
        self._set_state(StationState.PROCESSING)
        return duration

    def _acquire_vehicle(self):
        station_id = self.station_cfg.station_id
        while True:
            candidates = [b for b in self.input_buffers if not b.is_empty()]
            if candidates:
                chosen = min(candidates, key=lambda b: b.peek_enqueue_time())
                vehicle, enqueue_time = chosen.get()
                self.event_log.record(
                    EventType.VEHICLE_LEFT_BUFFER,
                    simulation_time=self.env.now,
                    vehicle_id=vehicle.vehicle_id,
                    vehicle_variant=vehicle.variant_id,
                    station_id=station_id,
                    buffer_id=chosen.buffer_id,
                    occupancy=len(chosen.items),
                )
                return vehicle, enqueue_time

            self._set_state(StationState.STARVED)
            wait_events = [b.item_available for b in self.input_buffers]
            yield self.env.any_of(wait_events)
            # loop back and re-check; safe even if multiple doorbells fired
            # since this station is the sole consumer of each of its inputs
