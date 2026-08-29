"""
Station runtime: the SimPy process loop for one physical station.

STATE SEMANTICS (as approved for Step 2):

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
  DOWN       Reserved for a later step (equipment failure scenarios). Never
             entered in Step 2.

State transitions are only logged when the state actually changes — no
repeated identical-state logging on every simulated tick.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

import simpy

from backend.config.schemas import FactoryConfig, StationInstance
from backend.simulation.buffer import SimBuffer
from backend.simulation.events import EventLog, EventType
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
        rng,
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
        self.rng = rng
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
        waiting (STARVED) — a station left BLOCKED or PROCESSING at run end
        indicates a deadlock/bug, not a normal shift end, and is left as-is
        so tests can catch it."""
        if self.state == StationState.STARVED:
            self._set_state(StationState.IDLE)

    def compute_processing_time(self, variant_id: str) -> float:
        override = self.station_cfg.variant_overrides.get(variant_id)
        if override is not None and override.cycle_time_multiplier is not None:
            multiplier = override.cycle_time_multiplier
        else:
            variant_cfg = self.config.vehicle_variants[variant_id]
            multiplier = variant_cfg.processing_time_modifiers.get(
                self.station_cfg.station_id, 1.0
            )
        mean = self.station_cfg.baseline_cycle_time_seconds * multiplier
        std = mean * self.station_cfg.cycle_time_variability
        if std <= 0:
            return mean
        # Truncated-normal-with-floor: a simple, bounded stochastic method
        # (illustrative simulation assumption, documented in ASSUMPTIONS.md)
        # chosen specifically to guarantee processing time stays comfortably
        # positive without needing a more sophisticated distribution.
        value = self.rng.gauss(mean, std)
        floor = mean * 0.3
        return max(value, floor)

    def run(self):
        """The station's SimPy process: acquire -> process -> release, in a
        single sequential loop. Because this loop is sequential and never
        starts a new acquire while still holding a vehicle pending release,
        BLOCKED and single-vehicle-at-a-time are enforced structurally,
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

            proc_time = self.compute_processing_time(vehicle.variant_id)
            self.event_log.record(
                EventType.STATION_PROCESSING_STARTED,
                simulation_time=self.env.now,
                vehicle_id=vehicle.vehicle_id,
                station_id=station_id,
                value=proc_time,
            )
            yield self.env.timeout(proc_time)
            self.processed_count += 1
            self.event_log.record(
                EventType.STATION_PROCESSING_COMPLETED,
                simulation_time=self.env.now,
                vehicle_id=vehicle.vehicle_id,
                station_id=station_id,
                value=proc_time,
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
