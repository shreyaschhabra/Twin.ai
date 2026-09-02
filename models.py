from __future__ import annotations

# ---- merged from backend/simulation/events.py ----
"""
Internal canonical event stream for TrustTwin simulation.

Deployable consumers must never read this stream directly; they consume the
public projection in observability.py.

Important semantics:
- VEHICLE_CREATED = exogenous production-demand arrival.
- VEHICLE_ENTERED_BUFFER with buffer_id "ENTRY::<station>" = physical admission
  into plant WIP.
- STATION_PROCESSING_STARTED.value may contain sampled future work duration and
  is therefore INTERNAL ONLY information at that timestamp.
- Scenario identity / latent quality truth never live on Event.
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

class EventType(str, Enum):
    VEHICLE_CREATED = 'VEHICLE_CREATED'
    VEHICLE_ENTERED_BUFFER = 'VEHICLE_ENTERED_BUFFER'
    VEHICLE_LEFT_BUFFER = 'VEHICLE_LEFT_BUFFER'
    VEHICLE_ENTERED_STATION = 'VEHICLE_ENTERED_STATION'
    STATION_PROCESSING_STARTED = 'STATION_PROCESSING_STARTED'
    STATION_PROCESSING_COMPLETED = 'STATION_PROCESSING_COMPLETED'
    STATION_STATE_CHANGED = 'STATION_STATE_CHANGED'
    VEHICLE_COMPLETED_LINE = 'VEHICLE_COMPLETED_LINE'
    SENSOR_READING = 'SENSOR_READING'
    MICRO_STOP_OCCURRED = 'MICRO_STOP_OCCURRED'
    MATERIAL_BATCH_ASSIGNED = 'MATERIAL_BATCH_ASSIGNED'
    QC_RESULT_RECORDED = 'QC_RESULT_RECORDED'

@dataclass(slots=True)
class Event:
    event_id: int
    simulation_time: float
    event_type: str
    vehicle_id: Optional[str] = None
    vehicle_variant: Optional[str] = None
    station_id: Optional[str] = None
    buffer_id: Optional[str] = None
    route_position: Optional[int] = None
    from_state: Optional[str] = None
    to_state: Optional[str] = None
    value: Optional[float] = None
    occupancy: Optional[int] = None
    sensor_name: Optional[str] = None
    unit: Optional[str] = None
    measurement_status: Optional[str] = None
    batch_id: Optional[str] = None
    batch_key: Optional[str] = None
    qc_result: Optional[str] = None

class EventLog:
    """Append-only, auto-numbered, chronological internal event collector."""

    def __init__(self) -> None:
        self._events: List[Event] = []
        self._next_id = 1
        self._last_time = float('-inf')

    def record(self, event_type: EventType, simulation_time: float, **fields) -> Event:
        if not isinstance(event_type, EventType):
            raise TypeError('event_type must be an EventType')
        if not math.isfinite(simulation_time) or simulation_time < 0:
            raise ValueError('simulation_time must be finite and >= 0')
        if simulation_time < self._last_time:
            raise RuntimeError(f'non-chronological event: {event_type.value} at {simulation_time} after {self._last_time}')
        self._validate_required_fields(event_type, fields)
        event = Event(event_id=self._next_id, simulation_time=float(simulation_time), event_type=event_type.value, **fields)
        self._next_id += 1
        self._last_time = float(simulation_time)
        self._events.append(event)
        return event

    @staticmethod
    def _validate_required_fields(event_type: EventType, fields: dict) -> None:
        vehicle_required = {EventType.VEHICLE_CREATED, EventType.VEHICLE_ENTERED_BUFFER, EventType.VEHICLE_LEFT_BUFFER, EventType.VEHICLE_ENTERED_STATION, EventType.STATION_PROCESSING_STARTED, EventType.STATION_PROCESSING_COMPLETED, EventType.VEHICLE_COMPLETED_LINE, EventType.MICRO_STOP_OCCURRED, EventType.MATERIAL_BATCH_ASSIGNED, EventType.QC_RESULT_RECORDED}
        station_required = {EventType.VEHICLE_ENTERED_BUFFER, EventType.VEHICLE_LEFT_BUFFER, EventType.VEHICLE_ENTERED_STATION, EventType.STATION_PROCESSING_STARTED, EventType.STATION_PROCESSING_COMPLETED, EventType.STATION_STATE_CHANGED, EventType.SENSOR_READING, EventType.MICRO_STOP_OCCURRED, EventType.MATERIAL_BATCH_ASSIGNED, EventType.QC_RESULT_RECORDED}
        if event_type in vehicle_required and (not fields.get('vehicle_id')):
            raise ValueError(f'{event_type.value} requires vehicle_id')
        if event_type in station_required and (not fields.get('station_id')):
            raise ValueError(f'{event_type.value} requires station_id')
        if event_type in {EventType.VEHICLE_ENTERED_BUFFER, EventType.VEHICLE_LEFT_BUFFER}:
            if not fields.get('buffer_id'):
                raise ValueError(f'{event_type.value} requires buffer_id')
            occupancy = fields.get('occupancy')
            if occupancy is None or occupancy < 0:
                raise ValueError(f'{event_type.value} requires occupancy >= 0')
        if event_type == EventType.STATION_STATE_CHANGED:
            if fields.get('from_state') is None or fields.get('to_state') is None:
                raise ValueError('STATION_STATE_CHANGED requires from_state/to_state')
        if event_type == EventType.SENSOR_READING:
            if not fields.get('sensor_name'):
                raise ValueError('SENSOR_READING requires sensor_name')
        if event_type == EventType.MATERIAL_BATCH_ASSIGNED:
            if not fields.get('batch_key'):
                raise ValueError('MATERIAL_BATCH_ASSIGNED requires batch_key')
        if event_type == EventType.QC_RESULT_RECORDED:
            if fields.get('qc_result') not in {'PASS', 'DEFECT'}:
                raise ValueError('QC_RESULT_RECORDED qc_result must be PASS or DEFECT')

    @property
    def events(self) -> List[Event]:
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

# ---- merged from backend/simulation/vehicle.py ----
"""
Minimal runtime vehicle state.

The object carries only routing and lifecycle bookkeeping. Defect labels,
scenario identities, root-cause truth, predictions, and genealogy do not live
here; those remain in their dedicated event/latent-truth layers.
"""
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Vehicle:
    vehicle_id: str
    variant_id: str
    route: List[str]
    created_at: float
    admitted_at: Optional[float] = None
    position: int = 0
    current_station: Optional[str] = None
    completed: bool = False
    completed_at: Optional[float] = None

    def current_station_id(self) -> str:
        return self.route[self.position]

    def is_last_station(self) -> bool:
        return self.position == len(self.route) - 1

    def next_station_id(self) -> Optional[str]:
        if self.is_last_station():
            return None
        return self.route[self.position + 1]

# ---- merged from backend/simulation/rng.py ----
"""
Deterministic, isolated RNG streams derived from one master seed.

Problem this solves: a single shared random.Random instance means every
consumer (vehicle arrivals, variant selection, each station's processing
time — and, starting Step 3, sensor noise, scenario occurrence/severity,
defect background noise) draws from the same sequence. Adding a draw
anywhere shifts every later consumer's numbers, which makes it impossible
to add a new stochastic mechanism later without silently changing the
timing of everything already validated.

RNGStreamFactory instead gives each named concern its own independent
random.Random instance, seeded by hashing (master_seed, stream_name)
together. Two streams from the same master seed are therefore both:
  - fully independent (separate random.Random state machines — consuming
    values from one can never affect another, by construction, not by
    convention), and
  - individually reproducible (the same master seed always derives the
    same per-stream seed, so re-running with the same seed reproduces
    every stream's sequence exactly).

Seeds are derived via SHA-256 over a UTF-8 string, never via Python's
built-in hash() — str hash() is randomized per-process (PYTHONHASHSEED)
unless explicitly disabled, which would silently break reproducibility
across processes/machines. SHA-256 has no such randomization.
"""
import hashlib
import random
from typing import Dict

def derive_seed(master_seed: int, stream_name: str) -> int:
    digest = hashlib.sha256(f'{master_seed}::{stream_name}'.encode('utf-8')).hexdigest()
    return int(digest[:16], 16)

class RNGStreamFactory:
    """One master seed in, any number of independent named streams out.
    Streams are created lazily and cached, so asking for the same name
    twice returns the same still-advancing Random instance, while a name
    never asked for is never created and therefore can't perturb anything
    (a future "sensor_noise::S01" stream unused in Step 2 has zero effect
    on Step 2 results)."""

    def __init__(self, master_seed: int):
        self.master_seed = master_seed
        self._streams: Dict[str, random.Random] = {}

    def get(self, stream_name: str) -> random.Random:
        if stream_name not in self._streams:
            self._streams[stream_name] = random.Random(derive_seed(self.master_seed, stream_name))
        return self._streams[stream_name]

# ---- merged from backend/simulation/buffer.py ----
"""
Finite-capacity FIFO buffer used for physical line-entry and inter-station WIP.

A custom deque is used instead of racing multiple simpy.Store.get() requests at
merge stations. Every physical buffer has one producer and one consumer; plain
SimPy Events act only as side-effect-free availability notifications.
"""
from collections import deque
from typing import Deque, Tuple
import simpy

class SimBuffer:

    def __init__(self, env: simpy.Environment, buffer_id: str, capacity: int):
        if capacity <= 0:
            raise ValueError('buffer capacity must be > 0')
        self.env = env
        self.buffer_id = buffer_id
        self.capacity = capacity
        self.items: Deque[Tuple[Vehicle, float]] = deque()
        self.max_occupancy = 0
        self.item_available = env.event()
        self.space_available = env.event()

    @property
    def occupancy(self) -> int:
        return len(self.items)

    def is_empty(self) -> bool:
        return self.occupancy == 0

    def is_full(self) -> bool:
        return self.occupancy >= self.capacity

    def peek_enqueue_time(self) -> float:
        if self.is_empty():
            raise RuntimeError(f'cannot peek empty buffer {self.buffer_id}')
        return self.items[0][1]

    def put(self, vehicle: Vehicle, enqueue_time: float) -> None:
        if self.is_full():
            raise RuntimeError(f'buffer {self.buffer_id} overflow (capacity {self.capacity})')
        self.items.append((vehicle, enqueue_time))
        self.max_occupancy = max(self.max_occupancy, self.occupancy)
        old_event = self.item_available
        self.item_available = self.env.event()
        if not old_event.triggered:
            old_event.succeed()

    def get(self) -> Tuple[Vehicle, float]:
        if self.is_empty():
            raise RuntimeError(f'buffer {self.buffer_id} underflow')
        item = self.items.popleft()
        old_event = self.space_available
        self.space_available = self.env.event()
        if not old_event.triggered:
            old_event.succeed()
        return item

# ---- merged from backend/simulation/qc.py ----
"""
Final QC outcome generation (Step 4). Converts a vehicle's accumulated
latent quality exposure into a probabilistic binary QC outcome — the
first place in the project where an actual PASS/DEFECT label is created.

Deliberately NOT a deterministic threshold (`if exposure > x: defect`),
per instructions — that produces unrealistic, perfectly separable labels.
Instead a smooth, bounded, monotonic mapping from exposure to probability,
then a single Bernoulli draw from an isolated RNG stream.

QCParameters is intentionally small and easy to recalibrate: the
historical generator regenerates data after adjusting these three numbers
until the overall defect rate lands in the target band — see
ASSUMPTIONS.md for the actual calibration history.
"""
import math
import random
from dataclasses import dataclass

@dataclass
class QCParameters:
    background_probability: float = 0.0088
    max_probability: float = 0.8
    midpoint: float = 0.0445
    steepness: float = 110.0

class QCOutcomeGenerator:

    def __init__(self, params: QCParameters, rng: random.Random):
        self.params = params
        self.rng = rng

    def compute_probability(self, total_exposure: float) -> float:
        """Logistic-style mapping, monotonically increasing in exposure,
        bounded in (background_probability, max_probability)."""
        p = self.params
        z = p.steepness * (total_exposure - p.midpoint)
        sigmoid = 1.0 / (1.0 + math.exp(-z))
        return p.background_probability + (p.max_probability - p.background_probability) * sigmoid

    def draw_outcome(self, total_exposure: float):
        """Returns (is_defect: bool, probability_used: float). The
        probability is returned for latent-truth logging only — it must
        never be attached to the observable QC_RESULT_RECORDED event."""
        probability = self.compute_probability(total_exposure)
        is_defect = self.rng.random() < probability
        return (is_defect, probability)

# ---- merged from backend/simulation/material_batches.py ----
"""
Baseline material/component batch scheduling (Step 3 patch 2).

This is deliberately NOT part of ScenarioManager: batch assignment is a
normal production concern that happens for every vehicle at a
batch-relevant station whether or not any scenario is configured. If only
scenario-affected vehicles ever received a batch_id or a
MATERIAL_BATCH_ASSIGNED event, the mere PRESENCE of that data would be a
synthetic tell distinguishing healthy from bad-batch runs — exactly the
shortcut this patch removes.

The schedule is a deterministic, index-based rotation (no RNG needed —
reproducibility is automatic from n_vehicles/config alone): every
`cohort_size` visits to a batch-relevant station, a new batch_id is
minted. A BAD_BATCH scenario never changes this schedule; it only
declares one already-assigned batch_id as latently quality-degraded (see
ScenarioManager.check_batch_exposure), so the SAME master seed produces
the identical observable batch-id sequence whether or not that scenario
is present — only latent exposure differs.

Numbering is PER STATION, each starting at 1001, not one counter shared
across every batch-relevant station. Two different stations track two
different material streams (e.g. adhesive vs. fasteners) in reality, so
they shouldn't share one running counter — and a shared counter would
make "declare batch B1002 as bad" ambiguous about which station's B1002
it means once more than one station is configured. Combined with
station_id, a batch_id is unambiguous.

Batch-relevant station settings are stored in the consolidated factory.yaml configuration.
"""
from pathlib import Path
from typing import Dict, Union
import yaml

class MaterialBatchScheduler:

    def __init__(self, batch_relevant_stations: Dict[str, int], starting_batch_number: int=1001):
        self.cohort_sizes = dict(batch_relevant_stations)
        self.starting_batch_number = starting_batch_number
        self._visit_counts: Dict[str, int] = {sid: 0 for sid in self.cohort_sizes}
        self._current_batch: Dict[str, str] = {}
        self._next_batch_number: Dict[str, int] = {sid: starting_batch_number for sid in self.cohort_sizes}

    def is_relevant(self, station_id: str) -> bool:
        return station_id in self.cohort_sizes

    def assign(self, station_id: str) -> str:
        count = self._visit_counts[station_id]
        cohort_size = self.cohort_sizes[station_id]
        if count % cohort_size == 0:
            self._current_batch[station_id] = f'B{self._next_batch_number[station_id]}'
            self._next_batch_number[station_id] += 1
        self._visit_counts[station_id] = count + 1
        return self._current_batch[station_id]

def load_batch_relevant_stations(path: Union[str, Path]) -> Dict[str, int]:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f'Material batch config file not found: {resolved}')
    with resolved.open('r') as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get('batch_relevant_stations', {}))

# ---- merged from backend/simulation/sensors.py ----
"""
Observable sensor generation. One summary reading per (vehicle, station,
sensor) visit, at processing-completion time — not high-frequency
telemetry.

SAMPLING CADENCE (illustrative simulation assumption, documented per
instructions): a single process-level summary measurement per visit is
enough time structure for later 1-minute Flow aggregation and anomaly
detection, because the meaningful trend structure comes from comparing
many visits to the SAME station over time (e.g. gradual degradation shows
up as a slow drift across dozens of visits' worth of summary readings),
not from sampling faster within any one ~15-100s visit. Generating
multiple samples per visit would multiply data volume for no analytical
benefit at this stage and was deliberately avoided (see Step 3
instructions: avoid high-frequency fake telemetry).

Sensor definitions (name/unit/baseline/noise/valid range) are loaded from
the consolidated factory.yaml file, keyed by (station_id, sensor_name) — baselines
differ by station even for the same sensor family (e.g. weld_current at
S01 vs S02), so a single global per-sensor-name default would be wrong.
Sensor models remain station-specific: dev-line and full-line both use IDs S01-S12, but those IDs mean
different stations with different sensors in each config, so one global
file keyed by bare station_id would silently collide.

"cycle_time" is deliberately never generated as a SENSOR_READING: it would
duplicate information the STATION_PROCESSING_COMPLETED event already
carries (see events.py's documented "avoid duplicate events" principle).
"""
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
import yaml
from pydantic import BaseModel
from config import StationInstance
from scenarios import StationEffectBundle
EXCLUDED_SENSORS = {'cycle_time'}

class SensorDefinition(BaseModel):
    unit: str
    baseline: float
    noise_std: float
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
SensorModelRegistry = Dict[Tuple[str, str], SensorDefinition]

def load_sensor_models(path: Union[str, Path]) -> SensorModelRegistry:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f'Sensor model config file not found: {resolved}')
    with resolved.open('r') as f:
        data = yaml.safe_load(f) or {}
    registry: SensorModelRegistry = {}
    for station_id, sensors in data.get('sensor_models', {}).items():
        for sensor_name, fields in sensors.items():
            registry[station_id, sensor_name] = SensorDefinition(**fields)
    return registry

def generate_sensor_readings(station_cfg: StationInstance, vehicle: Vehicle, sim_time: float, effects: StationEffectBundle, sensor_models: SensorModelRegistry, rng_factory: RNGStreamFactory, event_log: EventLog) -> None:
    """Appends one SENSOR_READING event per applicable sensor directly to
    event_log. Respects station.available_sensors — a station never
    exposes a sensor it isn't configured to have, regardless of scenario
    activity (sensor maturity must matter, per instructions)."""
    station_id = station_cfg.station_id
    for sensor_name in station_cfg.available_sensors:
        if sensor_name in EXCLUDED_SENSORS:
            continue
        definition = sensor_models.get((station_id, sensor_name))
        if definition is None:
            continue
        dropout_type = effects.sensor_dropout_type.get(sensor_name)
        dropout_prob = effects.sensor_dropout_probability.get(sensor_name, 0.0)
        rng = rng_factory.get(f'sensor_noise::{station_id}::{sensor_name}')
        dropped_out = dropout_type is not None and rng.random() < dropout_prob
        if dropped_out and dropout_type == 'missing':
            event_log.record(EventType.SENSOR_READING, simulation_time=sim_time, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, sensor_name=sensor_name, unit=definition.unit, value=None, measurement_status='missing')
            continue
        if dropped_out and dropout_type == 'stuck':
            event_log.record(EventType.SENSOR_READING, simulation_time=sim_time, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, sensor_name=sensor_name, unit=definition.unit, value=definition.baseline, measurement_status='stuck')
            continue
        mean = definition.baseline + effects.sensor_mean_shift.get(sensor_name, 0.0)
        noise_multiplier = effects.sensor_noise_multiplier.get(sensor_name, 1.0)
        if dropped_out and dropout_type == 'noisy':
            noise_multiplier *= 4.0
        std = definition.noise_std * noise_multiplier
        value = rng.gauss(mean, std) if std > 0 else mean
        if definition.valid_min is not None:
            value = max(value, definition.valid_min)
        if definition.valid_max is not None:
            value = min(value, definition.valid_max)
        event_log.record(EventType.SENSOR_READING, simulation_time=sim_time, vehicle_id=vehicle.vehicle_id, vehicle_variant=vehicle.variant_id, station_id=station_id, sensor_name=sensor_name, unit=definition.unit, value=value, measurement_status='available')

# ---- merged from backend/simulation/genealogy.py ----
"""
Vehicle genealogy, reconstructed from the master event stream — never
maintained as a second, independently-mutated structure during simulation,
so it cannot disagree with the event log by construction.

Relies on one convention from events.py: a VEHICLE_ENTERED_BUFFER event's
`station_id` always names the station the vehicle is now queued FOR (its
upcoming station), whether that buffer is the initial entry queue or an
ordinary inter-station buffer. That gives a uniform definition of
`entry_time` for every station a vehicle visits, including its first.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

@dataclass
class StationVisitRecord:
    station_id: str
    entry_time: float
    processing_start_time: float
    processing_completion_time: float
    exit_time: float
    waiting_time: float
    processing_time: float
    blocked_time: float

def build_genealogy(events: List[Event]) -> Dict[str, List[StationVisitRecord]]:
    """Single chronological pass over the event stream. For each vehicle,
    keeps at most one "open" visit (the station it's currently at) and
    closes it out — computing waiting/processing/blocked time — the moment
    either a VEHICLE_ENTERED_BUFFER for its *next* station or a
    VEHICLE_COMPLETED_LINE event confirms it has left."""
    genealogy: Dict[str, List[StationVisitRecord]] = {}
    pending_entry: Dict[Tuple[str, str], float] = {}
    open_visit: Dict[str, Tuple[str, dict]] = {}
    for event in events:
        vid = event.vehicle_id
        if vid is None:
            continue
        if event.event_type == EventType.VEHICLE_ENTERED_BUFFER.value:
            if vid in open_visit:
                station_id, record = open_visit[vid]
                if station_id != event.station_id:
                    open_visit.pop(vid)
                    _close_and_store(genealogy, vid, station_id, record, event.simulation_time)
            pending_entry[vid, event.station_id] = event.simulation_time
        elif event.event_type == EventType.VEHICLE_ENTERED_STATION.value:
            entry_time = pending_entry.pop((vid, event.station_id), event.simulation_time)
            open_visit[vid] = (event.station_id, {'entry_time': entry_time})
        elif event.event_type == EventType.STATION_PROCESSING_STARTED.value:
            _, record = open_visit[vid]
            record['processing_start_time'] = event.simulation_time
        elif event.event_type == EventType.STATION_PROCESSING_COMPLETED.value:
            _, record = open_visit[vid]
            record['processing_completion_time'] = event.simulation_time
            record['processing_time'] = event.value
        elif event.event_type == EventType.VEHICLE_COMPLETED_LINE.value:
            station_id, record = open_visit.pop(vid)
            _close_and_store(genealogy, vid, station_id, record, event.simulation_time)
    return genealogy

def _close_and_store(genealogy, vehicle_id, station_id, record, exit_time) -> None:
    record['exit_time'] = exit_time
    record['waiting_time'] = record['processing_start_time'] - record['entry_time']
    record['blocked_time'] = exit_time - record['processing_completion_time']
    visit = StationVisitRecord(station_id=station_id, entry_time=record['entry_time'], processing_start_time=record['processing_start_time'], processing_completion_time=record['processing_completion_time'], exit_time=record['exit_time'], waiting_time=record['waiting_time'], processing_time=record['processing_time'], blocked_time=record['blocked_time'])
    genealogy.setdefault(vehicle_id, []).append(visit)
