from __future__ import annotations

# ---- merged from backend/simulation/station.py ----
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
from enum import Enum
from typing import Dict, List, Optional
import simpy
from config import FactoryConfig, StationInstance
from models import SimBuffer
from models import EventLog, EventType
from models import MaterialBatchScheduler
from models import QCOutcomeGenerator
from models import RNGStreamFactory
from scenarios import StationEffectBundle
from scenarios import LatentTruthLog, QCGenerationRecord
from scenarios import ScenarioManager
from models import SensorModelRegistry, generate_sensor_readings
from models import Vehicle

class StationState(str, Enum):
    IDLE = 'IDLE'
    STARVED = 'STARVED'
    PROCESSING = 'PROCESSING'
    BLOCKED = 'BLOCKED'
    DOWN = 'DOWN'

class StationRuntime:
    """Holds a station's live state plus the SimPy process generator that
    drives it. All routing/buffer decisions come from FactoryConfig — no
    station-count or station-id assumptions live here."""

    def __init__(self, env: simpy.Environment, station_cfg: StationInstance, config: FactoryConfig, input_buffers: List[SimBuffer], outgoing_buffer_lookup: Dict[str, SimBuffer], event_log: EventLog, rng_factory: RNGStreamFactory, scenario_manager: ScenarioManager, sensor_models: SensorModelRegistry, material_batches: MaterialBatchScheduler, qc_station_id: Optional[str]=None, qc_generator: Optional[QCOutcomeGenerator]=None, latent_truth: Optional[LatentTruthLog]=None):
        if station_cfg.capacity != 1:
            raise NotImplementedError(f"station '{station_cfg.station_id}' has capacity={station_cfg.capacity}; this engine only implements single-slot (capacity=1) stations. Multi-slot concurrent stations are a documented future extension (state semantics like BLOCKED become per-slot, not per-station), not built now since no current config needs it.")
        self.env = env
        self.station_cfg = station_cfg
        self.config = config
        self.input_buffers = input_buffers
        self.outgoing_buffer_lookup = outgoing_buffer_lookup
        self.event_log = event_log
        self.rng_factory = rng_factory
        self.processing_rng = rng_factory.get(f'processing_time::{station_cfg.station_id}')
        self.micro_stop_rng = rng_factory.get(f'micro_stop::{station_cfg.station_id}')
        self.scenario_manager = scenario_manager
        self.sensor_models = sensor_models
        self.material_batches = material_batches
        self.qc_station_id = qc_station_id
        self.qc_generator = qc_generator
        self.latent_truth = latent_truth
        self.state = StationState.IDLE
        self.processed_count = 0

    def _set_state(self, new_state: StationState, vehicle_id: Optional[str]=None, buffer_id: Optional[str]=None, occupancy: Optional[int]=None) -> None:
        """vehicle_id/buffer_id/occupancy are populated only for the
        BLOCKED transition (Step 4 patch 1): they let an audit directly
        verify, from the observable event alone, that BLOCKED was only
        ever entered when the named buffer was already at its configured
        capacity — no reconstruction/heuristic join required. Other
        transitions (STARVED/PROCESSING/DOWN) don't carry a buffer
        context and leave these as None, unchanged from before."""
        if new_state == self.state:
            return
        self.event_log.record(EventType.STATION_STATE_CHANGED, simulation_time=self.env.now, station_id=self.station_cfg.station_id, from_state=self.state.value, to_state=new_state.value, vehicle_id=vehicle_id, buffer_id=buffer_id, occupancy=occupancy)
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
        """Sample positive service work around the config-defined nominal value.

        Variant work content is resolved centrally by FactoryConfig so the
        simulator, offline feature builders, and runtime services cannot apply
        different precedence rules for variant multipliers.
        """
        nominal = self.config.nominal_service_seconds(self.station_cfg.station_id, variant_id)
        mean = nominal * effects.cycle_time_multiplier
        std = mean * self.station_cfg.cycle_time_variability * effects.variability_multiplier
        if std <= 0:
            return mean
        value = self.processing_rng.gauss(mean, std)
        return max(value, mean * 0.3)

    def run(self):
        """The station's SimPy process: acquire -> process -> release, in a
        single sequential loop. Because this loop is sequential and never
        starts a new acquire while still holding a vehicle pending release,
        BLOCKED/DOWN and single-vehicle-at-a-time are enforced structurally,
        not by extra locking."""
        station_id = self.station_cfg.station_id
        while True:
            vehicle, enqueue_time = (yield from self._acquire_vehicle())
            self._set_state(StationState.PROCESSING)
            vehicle.current_station = station_id
            self.event_log.record(EventType.VEHICLE_ENTERED_STATION, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, route_position=vehicle.position)
            effects = self.scenario_manager.get_station_effects(self.env.now, station_id, vehicle.vehicle_id)
            if self.material_batches.is_relevant(station_id):
                batch_id = self.material_batches.assign(station_id)
                self.event_log.record(EventType.MATERIAL_BATCH_ASSIGNED, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, batch_id=batch_id, batch_key=f'{station_id}::{batch_id}')
                self.scenario_manager.check_batch_exposure(vehicle.vehicle_id, self.env.now, station_id, batch_id)
            proc_time = self.compute_processing_time(vehicle.variant_id, effects)
            self.event_log.record(EventType.STATION_PROCESSING_STARTED, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, station_id=station_id, value=proc_time)
            micro_stop_duration = (yield from self._run_processing_with_interruptions(station_id, vehicle, proc_time))
            self.processed_count += 1
            total_time = proc_time + micro_stop_duration
            self.event_log.record(EventType.STATION_PROCESSING_COMPLETED, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, station_id=station_id, value=total_time)
            generate_sensor_readings(station_cfg=self.station_cfg, vehicle=vehicle, sim_time=self.env.now, effects=effects, sensor_models=self.sensor_models, rng_factory=self.rng_factory, event_log=self.event_log)
            if self.qc_generator is not None and station_id == self.qc_station_id:
                total_exposure = self.latent_truth.total_exposure_for_vehicle(vehicle.vehicle_id)
                is_defect, probability = self.qc_generator.draw_outcome(total_exposure)
                qc_result = 'DEFECT' if is_defect else 'PASS'
                self.latent_truth.record_qc_generation(QCGenerationRecord(vehicle_id=vehicle.vehicle_id, simulation_time=self.env.now, total_exposure=total_exposure, probability_used=probability, qc_result=qc_result))
                self.event_log.record(EventType.QC_RESULT_RECORDED, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, qc_result=qc_result)
            if vehicle.is_last_station():
                vehicle.completed = True
                vehicle.completed_at = self.env.now
                vehicle.current_station = None
                self.event_log.record(EventType.VEHICLE_COMPLETED_LINE, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id)
            else:
                next_station_id = vehicle.next_station_id()
                out_buffer = self.outgoing_buffer_lookup[next_station_id]
                if out_buffer.is_full():
                    self._set_state(StationState.BLOCKED, vehicle_id=vehicle.vehicle_id, buffer_id=out_buffer.buffer_id, occupancy=out_buffer.occupancy)
                    while out_buffer.is_full():
                        yield out_buffer.space_available
                vehicle.position += 1
                vehicle.current_station = None
                out_buffer.put(vehicle, self.env.now)
                self.event_log.record(EventType.VEHICLE_ENTERED_BUFFER, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=next_station_id, buffer_id=out_buffer.buffer_id, route_position=vehicle.position, occupancy=out_buffer.occupancy)

    def _run_processing_with_interruptions(self, station_id: str, vehicle: Vehicle, processing_work_seconds: float):
        """Run processing work with stochastic in-process interruptions.

        `rate_process` supports zero/one/multiple stops using an exponential
        work-to-stop process.

        The legacy probability mode is retained only for compatibility with
        current scenario definitions, but its stop is now placed *inside* the
        processing interval rather than unrealistically occurring before any
        process work has been completed.
        """
        params = self.scenario_manager.get_micro_stop_params(self.env.now, station_id)
        if params is None:
            yield self.env.timeout(processing_work_seconds)
            return 0.0
        if params.get('mode') != 'rate_process':
            probability = params['probability']
            if self.micro_stop_rng.random() >= probability:
                yield self.env.timeout(processing_work_seconds)
                return 0.0
            work_before_stop = self.micro_stop_rng.uniform(0.0, processing_work_seconds)
            work_after_stop = processing_work_seconds - work_before_stop
            if work_before_stop > 0:
                yield self.env.timeout(work_before_stop)
            duration = self.micro_stop_rng.uniform(params['min_duration'], params['max_duration'])
            self._set_state(StationState.DOWN)
            self.event_log.record(EventType.MICRO_STOP_OCCURRED, simulation_time=self.env.now, station_id=station_id, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, value=duration)
            yield self.env.timeout(duration)
            self._set_state(StationState.PROCESSING)
            if work_after_stop > 0:
                yield self.env.timeout(work_after_stop)
            return duration
        rate_per_second = params['rate_per_processing_minute'] / 60.0
        if rate_per_second <= 0:
            yield self.env.timeout(processing_work_seconds)
            return 0.0
        remaining_work = processing_work_seconds
        total_stop_seconds = 0.0
        while remaining_work > 0:
            work_until_stop = self.micro_stop_rng.expovariate(rate_per_second)
            if work_until_stop >= remaining_work:
                yield self.env.timeout(remaining_work)
                break
            yield self.env.timeout(work_until_stop)
            remaining_work -= work_until_stop
            duration = self.micro_stop_rng.uniform(params['min_duration'], params['max_duration'])
            self._set_state(StationState.DOWN)
            self.event_log.record(EventType.MICRO_STOP_OCCURRED, simulation_time=self.env.now, station_id=station_id, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, value=duration)
            yield self.env.timeout(duration)
            total_stop_seconds += duration
            self._set_state(StationState.PROCESSING)
        return total_stop_seconds

    def _acquire_vehicle(self):
        station_id = self.station_cfg.station_id
        while True:
            candidates = [b for b in self.input_buffers if not b.is_empty()]
            if candidates:
                chosen = min(candidates, key=lambda b: b.peek_enqueue_time())
                vehicle, enqueue_time = chosen.get()
                self.event_log.record(EventType.VEHICLE_LEFT_BUFFER, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, buffer_id=chosen.buffer_id, occupancy=chosen.occupancy)
                return (vehicle, enqueue_time)
            self._set_state(StationState.STARVED)
            wait_events = [b.item_available for b in self.input_buffers]
            yield self.env.any_of(wait_events)

# ---- merged from backend/simulation/engine.py ----
"""
FactoryEngine for the TrustTwin final discrete-event simulation.

Key rules:
- topology/routing/service baselines come from FactoryConfig
- external demand is exogenous: a full line-entry buffer must NOT stop future
  customer/production-order arrivals from being generated
- finite entry/inter-station buffers control admission/WIP, not demand creation
- scenario effects are latent simulator truth and never encoded in FactoryConfig
"""
from dataclasses import dataclass, field
from math import isclose
from typing import Dict, List, Optional, Tuple
import simpy
from config import FactoryConfig
from models import SimBuffer
from models import Event, EventLog, EventType
from models import StationVisitRecord, build_genealogy
from models import MaterialBatchScheduler
from models import QCOutcomeGenerator, QCParameters
from models import RNGStreamFactory
from scenarios import ScenarioDefinition
from scenarios import LatentTruthLog
from scenarios import ScenarioManager
from models import SensorModelRegistry
from models import Vehicle
DEFAULT_ENTRY_BUFFER_CAPACITY = 20
LEGACY_DEFAULT_MEAN_INTERARRIVAL_SECONDS = 200.0
LEGACY_DEFAULT_STD_INTERARRIVAL_SECONDS = 20.0
LEGACY_DEFAULT_VARIANT_MIX = {'ICE_SEDAN': 0.45, 'ICE_SUV': 0.35, 'EV': 0.2}

@dataclass
class RunResult:
    events: List[Event]
    vehicles: Dict[str, Vehicle]
    genealogy: Dict[str, List[StationVisitRecord]]
    summary: dict = field(default_factory=dict)
    latent_truth: Optional[LatentTruthLog] = None

class FactoryEngine:

    def __init__(self, config: FactoryConfig, seed: int, entry_buffer_capacity: int=DEFAULT_ENTRY_BUFFER_CAPACITY, scenarios: Optional[List[ScenarioDefinition]]=None, sensor_models: Optional[SensorModelRegistry]=None, batch_relevant_stations: Optional[Dict[str, int]]=None, qc_station_id: Optional[str]=None, qc_params: Optional[QCParameters]=None):
        if entry_buffer_capacity <= 0:
            raise ValueError('entry_buffer_capacity must be > 0')
        self.config = config
        self.rng_factory = RNGStreamFactory(master_seed=seed)
        self.arrival_rng = self.rng_factory.get('vehicle_interarrival')
        self.variant_rng = self.rng_factory.get('vehicle_variant_selection')
        self.background_quality_rng = self.rng_factory.get('background_quality_disturbance')
        self.latent_truth = LatentTruthLog()
        self.scenario_manager = ScenarioManager(scenarios or [], self.latent_truth)
        self.sensor_models: SensorModelRegistry = sensor_models or {}
        self.material_batches = MaterialBatchScheduler(batch_relevant_stations or {})
        self.qc_station_id = qc_station_id
        self.qc_generator: Optional[QCOutcomeGenerator] = None
        if qc_station_id is not None:
            if qc_station_id not in config.stations:
                raise ValueError(f"unknown qc_station_id '{qc_station_id}'")
            self.qc_generator = QCOutcomeGenerator(qc_params or QCParameters(), self.rng_factory.get('qc_outcome'))
        self.env = simpy.Environment()
        self.event_log = EventLog()
        self.vehicles: Dict[str, Vehicle] = {}
        self.entry_stations = sorted({variant.route[0] for variant in config.vehicle_variants.values()})
        self.buffers: Dict[str, SimBuffer] = {buffer_id: SimBuffer(self.env, buffer_id, buf_cfg.capacity) for buffer_id, buf_cfg in config.buffers.items()}
        self.entry_buffers: Dict[str, SimBuffer] = {station_id: SimBuffer(self.env, f'ENTRY::{station_id}', entry_buffer_capacity) for station_id in self.entry_stations}
        self.external_arrival_queues: Dict[str, simpy.Store] = {station_id: simpy.Store(self.env) for station_id in self.entry_stations}
        self.max_external_queue: Dict[str, int] = {station_id: 0 for station_id in self.entry_stations}
        self.outgoing_buffer: Dict[Tuple[str, str], SimBuffer] = {(buf_cfg.upstream_station, buf_cfg.downstream_station): self.buffers[buffer_id] for buffer_id, buf_cfg in config.buffers.items()}
        self.outgoing_by_station: Dict[str, Dict[str, SimBuffer]] = {}
        for (upstream, downstream), buf in self.outgoing_buffer.items():
            self.outgoing_by_station.setdefault(upstream, {})[downstream] = buf
        self.incoming_buffers: Dict[str, List[SimBuffer]] = {sid: [] for sid in config.stations}
        for buffer_id, buf_cfg in config.buffers.items():
            self.incoming_buffers[buf_cfg.downstream_station].append(self.buffers[buffer_id])
        for station_id, entry_buf in self.entry_buffers.items():
            self.incoming_buffers[station_id].append(entry_buf)
        self.station_runtimes: Dict[str, StationRuntime] = {station_id: StationRuntime(env=self.env, station_cfg=station_cfg, config=config, input_buffers=self.incoming_buffers[station_id], outgoing_buffer_lookup=self.outgoing_by_station.get(station_id, {}), event_log=self.event_log, rng_factory=self.rng_factory, scenario_manager=self.scenario_manager, sensor_models=self.sensor_models, material_batches=self.material_batches, qc_station_id=self.qc_station_id, qc_generator=self.qc_generator, latent_truth=self.latent_truth) for station_id, station_cfg in config.stations.items()}

    def run(self, n_vehicles: int, mean_interarrival_seconds: Optional[float]=None, std_interarrival_seconds: Optional[float]=None, variant_mix: Optional[Dict[str, float]]=None) -> RunResult:
        if n_vehicles <= 0:
            raise ValueError('n_vehicles must be > 0')
        mean_interarrival_seconds, std_interarrival_seconds, variant_mix = self._resolve_production_inputs(mean_interarrival_seconds, std_interarrival_seconds, variant_mix)
        for runtime in self.station_runtimes.values():
            self.env.process(runtime.run())
        for station_id in self.entry_stations:
            self.env.process(self._entry_admission_loop(station_id))
        self.env.process(self._vehicle_generator(n_vehicles, mean_interarrival_seconds, std_interarrival_seconds, variant_mix))
        self.env.run()
        for runtime in self.station_runtimes.values():
            runtime.finalize_idle()
        genealogy = build_genealogy(self.event_log.events)
        summary = self._build_summary()
        return RunResult(events=self.event_log.events, vehicles=self.vehicles, genealogy=genealogy, summary=summary, latent_truth=self.latent_truth)

    def _resolve_production_inputs(self, mean_interarrival_seconds: Optional[float], std_interarrival_seconds: Optional[float], variant_mix: Optional[Dict[str, float]]) -> Tuple[float, float, Dict[str, float]]:
        plan = getattr(self.config, 'production_plan', None)
        if mean_interarrival_seconds is None:
            if plan is not None:
                mean_interarrival_seconds = float(plan.nominal_interarrival_seconds)
            else:
                mean_interarrival_seconds = LEGACY_DEFAULT_MEAN_INTERARRIVAL_SECONDS
        if std_interarrival_seconds is None:
            std_interarrival_seconds = 0.0 if plan is not None else LEGACY_DEFAULT_STD_INTERARRIVAL_SECONDS
        if variant_mix is None:
            if plan is not None:
                variant_mix = dict(plan.baseline_variant_mix)
            else:
                variant_mix = dict(LEGACY_DEFAULT_VARIANT_MIX)
        if mean_interarrival_seconds <= 0:
            raise ValueError('mean_interarrival_seconds must be > 0')
        if std_interarrival_seconds < 0:
            raise ValueError('std_interarrival_seconds must be >= 0')
        self._validate_variant_mix(variant_mix)
        return (float(mean_interarrival_seconds), float(std_interarrival_seconds), dict(variant_mix))

    def _validate_variant_mix(self, variant_mix: Dict[str, float]) -> None:
        expected = set(self.config.vehicle_variants)
        actual = set(variant_mix)
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            parts = []
            if missing:
                parts.append(f'missing variants {sorted(missing)}')
            if extra:
                parts.append(f'unknown variants {sorted(extra)}')
            raise ValueError('invalid variant_mix: ' + '; '.join(parts))
        if any((weight < 0 for weight in variant_mix.values())):
            raise ValueError('variant_mix weights must be non-negative')
        total = sum(variant_mix.values())
        if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-09):
            raise ValueError(f'variant_mix must sum to 1.0, got {total:.12f}')

    def _sample_interarrival(self, mean_interarrival: float, std_interarrival: float) -> float:
        if std_interarrival == 0:
            return mean_interarrival
        value = self.arrival_rng.gauss(mean_interarrival, std_interarrival)
        return max(value, mean_interarrival * 0.3)

    def _vehicle_generator(self, n_vehicles: int, mean_interarrival: float, std_interarrival: float, variant_mix: Dict[str, float]):
        for i in range(1, n_vehicles + 1):
            arrival_multiplier = self.scenario_manager.get_arrival_headway_multiplier(self.env.now)
            effective_mean = mean_interarrival * arrival_multiplier
            effective_std = std_interarrival * arrival_multiplier
            interarrival = self._sample_interarrival(effective_mean, effective_std)
            yield self.env.timeout(interarrival)
            active_mix = self.scenario_manager.get_variant_mix_override(self.env.now, variant_mix) or variant_mix
            self._validate_variant_mix(active_mix)
            variant_ids = list(active_mix.keys())
            weights = list(active_mix.values())
            variant_id = self.variant_rng.choices(variant_ids, weights=weights, k=1)[0]
            vehicle_id = f'V{i:05d}'
            route = list(self.config.vehicle_variants[variant_id].route)
            vehicle = Vehicle(vehicle_id=vehicle_id, variant_id=variant_id, route=route, created_at=self.env.now)
            self.vehicles[vehicle_id] = vehicle
            self.event_log.record(EventType.VEHICLE_CREATED, simulation_time=self.env.now, vehicle_id=vehicle_id, vehicle_variant=variant_id, route_position=0)
            self.scenario_manager.roll_random_quality_event(vehicle_id, self.env.now, self.background_quality_rng)
            entry_station = route[0]
            queue = self.external_arrival_queues[entry_station]
            yield queue.put(vehicle)
            self.max_external_queue[entry_station] = max(self.max_external_queue[entry_station], len(queue.items))

    def _entry_admission_loop(self, station_id: str):
        external_queue = self.external_arrival_queues[station_id]
        entry_buf = self.entry_buffers[station_id]
        while True:
            vehicle = (yield external_queue.get())
            while entry_buf.is_full():
                yield entry_buf.space_available
            vehicle.admitted_at = self.env.now
            entry_buf.put(vehicle, self.env.now)
            self.event_log.record(EventType.VEHICLE_ENTERED_BUFFER, simulation_time=self.env.now, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, buffer_id=entry_buf.buffer_id, route_position=0, occupancy=entry_buf.occupancy)

    def _build_summary(self) -> dict:
        events = self.event_log.events
        sim_end = events[-1].simulation_time if events else 0.0
        completed = [v for v in self.vehicles.values() if v.completed]
        by_variant: Dict[str, int] = {}
        for vehicle in self.vehicles.values():
            by_variant[vehicle.variant_id] = by_variant.get(vehicle.variant_id, 0) + 1
        demand_to_completion = [v.completed_at - v.created_at for v in completed if v.completed_at is not None]
        plant_time = [v.completed_at - v.admitted_at for v in completed if v.completed_at is not None and v.admitted_at is not None]
        external_wait = [v.admitted_at - v.created_at for v in self.vehicles.values() if v.admitted_at is not None]
        processing_counts: Dict[str, int] = {sid: runtime.processed_count for sid, runtime in self.station_runtimes.items()}
        proc_time_sums: Dict[str, float] = {sid: 0.0 for sid in self.config.stations}
        proc_time_counts: Dict[str, int] = {sid: 0 for sid in self.config.stations}
        for event in events:
            if event.event_type == EventType.STATION_PROCESSING_COMPLETED.value:
                proc_time_sums[event.station_id] += event.value
                proc_time_counts[event.station_id] += 1
        avg_effective_service_time = {sid: proc_time_sums[sid] / proc_time_counts[sid] if proc_time_counts[sid] else 0.0 for sid in self.config.stations}
        state_time = _integrate_state_durations(events, self.config.stations.keys(), sim_end)
        max_buffer_occupancy = {bid: buf.max_occupancy for bid, buf in self.buffers.items()}
        processing_utilization = {sid: state_time[sid].get('PROCESSING', 0.0) / sim_end if sim_end else 0.0 for sid in self.config.stations}
        return {'vehicles_generated': len(self.vehicles), 'vehicles_completed': len(completed), 'vehicles_by_variant': by_variant, 'simulated_duration_seconds': sim_end, 'throughput_vehicles_per_hour': len(completed) / sim_end * 3600 if sim_end else 0.0, 'avg_demand_to_completion_seconds': sum(demand_to_completion) / len(demand_to_completion) if demand_to_completion else 0.0, 'avg_plant_time_seconds': sum(plant_time) / len(plant_time) if plant_time else 0.0, 'avg_external_admission_wait_seconds': sum(external_wait) / len(external_wait) if external_wait else 0.0, 'max_external_arrival_queue': dict(self.max_external_queue), 'station_processing_utilization': processing_utilization, 'processing_counts_per_station': processing_counts, 'avg_effective_service_time_per_station': avg_effective_service_time, 'max_buffer_occupancy': max_buffer_occupancy, 'blocked_time_per_station': {sid: state_time[sid].get('BLOCKED', 0.0) for sid in self.config.stations}, 'starved_time_per_station': {sid: state_time[sid].get('STARVED', 0.0) for sid in self.config.stations}, 'avg_time_in_system_seconds': sum(demand_to_completion) / len(demand_to_completion) if demand_to_completion else 0.0, 'station_utilization': processing_utilization, 'avg_processing_time_per_station': avg_effective_service_time}

def _integrate_state_durations(events: List[Event], station_ids, sim_end: float) -> Dict[str, Dict[str, float]]:
    durations: Dict[str, Dict[str, float]] = {sid: {} for sid in station_ids}
    last_state: Dict[str, str] = {}
    last_time: Dict[str, float] = {}
    for event in events:
        if event.event_type != EventType.STATION_STATE_CHANGED.value:
            continue
        sid = event.station_id
        if sid in last_state:
            elapsed = event.simulation_time - last_time[sid]
            durations[sid][last_state[sid]] = durations[sid].get(last_state[sid], 0.0) + elapsed
        last_state[sid] = event.to_state
        last_time[sid] = event.simulation_time
    for sid, state in last_state.items():
        elapsed = sim_end - last_time[sid]
        durations[sid][state] = durations[sid].get(state, 0.0) + elapsed
    return durations

def run_simulation(config: FactoryConfig, n_vehicles: int, seed: int, mean_interarrival_seconds: Optional[float]=None, std_interarrival_seconds: Optional[float]=None, variant_mix: Optional[Dict[str, float]]=None, entry_buffer_capacity: int=DEFAULT_ENTRY_BUFFER_CAPACITY, scenarios: Optional[List[ScenarioDefinition]]=None, sensor_models: Optional[SensorModelRegistry]=None, batch_relevant_stations: Optional[Dict[str, int]]=None, qc_station_id: Optional[str]=None, qc_params: Optional[QCParameters]=None) -> RunResult:
    engine = FactoryEngine(config, seed=seed, entry_buffer_capacity=entry_buffer_capacity, scenarios=scenarios, sensor_models=sensor_models, batch_relevant_stations=batch_relevant_stations, qc_station_id=qc_station_id, qc_params=qc_params)
    return engine.run(n_vehicles=n_vehicles, mean_interarrival_seconds=mean_interarrival_seconds, std_interarrival_seconds=std_interarrival_seconds, variant_mix=variant_mix)
