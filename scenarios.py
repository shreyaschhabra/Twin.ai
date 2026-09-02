from __future__ import annotations

# ---- merged from backend/simulation/scenarios/config.py ----
"""
Strict scenario configuration for TrustTwin.
Scenario configuration is latent simulator truth and must never become an ML feature.
"""
from enum import Enum
from math import isclose
from pathlib import Path
from typing import Dict, List, Optional, Union
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from config import FactoryConfig

class ScenarioFamily(str, Enum):
    EQUIPMENT_DEGRADATION = 'EQUIPMENT_DEGRADATION'
    MICRO_STOPS = 'MICRO_STOPS'
    VEHICLE_MIX_OVERLOAD = 'VEHICLE_MIX_OVERLOAD'
    BAD_BATCH = 'BAD_BATCH'
    ENVIRONMENTAL_DRIFT = 'ENVIRONMENTAL_DRIFT'
    SENSOR_DROPOUT = 'SENSOR_DROPOUT'
    MANUAL_VARIATION = 'MANUAL_VARIATION'
    RANDOM_QUALITY_EVENT = 'RANDOM_QUALITY_EVENT'
    ARRIVAL_BURST = 'ARRIVAL_BURST'

class TemporalProfile(str, Enum):
    STEP = 'STEP'
    STEP_BURST = 'STEP_BURST'
    GRADUAL = 'GRADUAL'
    ACCELERATING = 'ACCELERATING'
    RECOVERING = 'RECOVERING'
    RAMP_BURST = 'RAMP_BURST'
    INTERMITTENT = 'INTERMITTENT'

class DropoutType(str, Enum):
    MISSING = 'missing'
    STUCK = 'stuck'
    NOISY = 'noisy'

class ScenarioDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scenario_id: str = Field(..., min_length=1)
    family: ScenarioFamily
    station_ids: List[str] = Field(default_factory=list)
    start_time: float = Field(default=0.0, ge=0.0)
    duration: Optional[float] = Field(default=None, gt=0.0)
    severity: float = Field(default=1.0, ge=0.0, le=1.0)
    affected_sensors: List[str] = Field(default_factory=list)
    params: Dict[str, float] = Field(default_factory=dict)
    affected_batch_id: Optional[str] = None
    variant_mix_override: Optional[Dict[str, float]] = None
    dropout_type: Optional[DropoutType] = None
    temporal_profile: Optional[TemporalProfile] = None

    @model_validator(mode='after')
    def validate_family(self):
        station_families = {ScenarioFamily.EQUIPMENT_DEGRADATION, ScenarioFamily.MICRO_STOPS, ScenarioFamily.BAD_BATCH, ScenarioFamily.ENVIRONMENTAL_DRIFT, ScenarioFamily.SENSOR_DROPOUT, ScenarioFamily.MANUAL_VARIATION}
        if self.family in station_families and (not self.station_ids):
            raise ValueError(f'{self.family.value} requires station_ids')
        if self.family == ScenarioFamily.BAD_BATCH and (not self.affected_batch_id):
            raise ValueError('BAD_BATCH requires affected_batch_id')
        if self.family == ScenarioFamily.VEHICLE_MIX_OVERLOAD:
            if not self.variant_mix_override:
                raise ValueError('VEHICLE_MIX_OVERLOAD requires variant_mix_override')
            total = sum(self.variant_mix_override.values())
            if any((v < 0 for v in self.variant_mix_override.values())):
                raise ValueError('variant_mix_override weights must be >= 0')
            if not isclose(total, 1.0, abs_tol=1e-09):
                raise ValueError('variant_mix_override must sum to 1.0')
        if self.family == ScenarioFamily.SENSOR_DROPOUT and self.dropout_type is None:
            self.dropout_type = DropoutType.MISSING
        if self.duration is None and self.temporal_profile in {TemporalProfile.GRADUAL, TemporalProfile.ACCELERATING, TemporalProfile.RECOVERING, TemporalProfile.RAMP_BURST, TemporalProfile.INTERMITTENT}:
            raise ValueError(f'{self.temporal_profile.value} requires finite duration')
        return self

    def is_active_at(self, sim_time: float) -> bool:
        if sim_time < self.start_time:
            return False
        if self.duration is None:
            return True
        return sim_time < self.start_time + self.duration

    def profile_fraction(self, sim_time: float, default_profile: str='STEP') -> float:
        if not self.is_active_at(sim_time):
            return 0.0
        profile = self.temporal_profile.value if self.temporal_profile else default_profile
        profile = profile.upper()
        if profile in {'STEP', 'STEP_BURST'}:
            return 1.0
        if self.duration is None:
            raise ValueError(f'{profile} requires finite duration')
        progress = max(0.0, min(1.0, (sim_time - self.start_time) / self.duration))
        if profile == 'GRADUAL':
            return min(1.0, progress / 0.5)
        if profile == 'ACCELERATING':
            return progress * progress
        if profile == 'RECOVERING':
            if progress < 0.25:
                return progress / 0.25
            if progress <= 0.65:
                return 1.0
            return max(0.0, (1.0 - progress) / 0.35)
        if profile == 'RAMP_BURST':
            return min(1.0, progress / 0.25)
        if profile == 'INTERMITTENT':
            period = max(60.0, self.params.get('intermittent_period_seconds', 600.0))
            duty = max(0.05, min(0.95, self.params.get('intermittent_duty_cycle', 0.5)))
            phase = (sim_time - self.start_time) % period / period
            return 1.0 if phase < duty else 0.0
        raise ValueError(f'unsupported temporal profile {profile!r}')

    def strength(self, sim_time: float, default_profile: str='STEP') -> float:
        return self.severity * self.profile_fraction(sim_time, default_profile)

class UniqueKeySafeLoader(yaml.SafeLoader):
    pass

def _construct_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f'duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}')
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping
UniqueKeySafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)

def load_scenarios(path: Union[str, Path], factory_config: Optional[FactoryConfig]=None) -> List[ScenarioDefinition]:
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f'Scenario config file not found: {resolved}')
    with resolved.open('r') as f:
        data = yaml.load(f, Loader=UniqueKeySafeLoader) or {}
    unknown = set(data) - {'scenarios'}
    if unknown:
        raise ValueError(f'unknown top-level keys: {sorted(unknown)}')
    raw = data.get('scenarios')
    if not isinstance(raw, dict):
        raise ValueError("scenario config requires a 'scenarios' mapping")
    scenarios = [ScenarioDefinition(scenario_id=scenario_id, **fields) for scenario_id, fields in raw.items()]
    if factory_config is not None:
        for scenario in scenarios:
            for station_id in scenario.station_ids:
                if station_id not in factory_config.stations:
                    raise ValueError(f'scenario {scenario.scenario_id!r} references unknown station {station_id!r}')
            if scenario.variant_mix_override is not None:
                if set(scenario.variant_mix_override) != set(factory_config.vehicle_variants):
                    raise ValueError(f'scenario {scenario.scenario_id!r} variant mix does not match factory variants')
            for station_id in scenario.station_ids:
                available = set(factory_config.stations[station_id].available_sensors)
                for sensor in scenario.affected_sensors:
                    if sensor not in available:
                        raise ValueError(f'scenario {scenario.scenario_id!r} targets unavailable sensor {sensor!r} at {station_id}')
    return scenarios

# ---- merged from backend/simulation/scenarios/effects.py ----
"""
StationEffectBundle: the one channel through which active scenarios can
influence a station's processing time and sensor generation. Station code
asks "what's active for me right now" once per visit and applies whatever
comes back — it never checks `if station_id == "S09"` or any scenario
family by name.
"""
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class StationEffectBundle:
    cycle_time_multiplier: float = 1.0
    variability_multiplier: float = 1.0
    sensor_mean_shift: Dict[str, float] = field(default_factory=dict)
    sensor_noise_multiplier: Dict[str, float] = field(default_factory=dict)
    sensor_dropout_type: Dict[str, str] = field(default_factory=dict)
    sensor_dropout_probability: Dict[str, float] = field(default_factory=dict)
    active_scenario_ids: List[str] = field(default_factory=list)

# ---- merged from backend/simulation/scenarios/latent.py ----
"""
Simulator-only latent truth.
Nothing here belongs in observable events or ML features.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

@dataclass
class ScenarioTruthRecord:
    scenario_id: str
    family: str
    station_ids: List[str]
    start_time: float
    end_time: Optional[float]
    severity: float
    params: Dict[str, float] = field(default_factory=dict)
    affected_batch_id: Optional[str] = None

@dataclass
class QualityExposureRecord:
    vehicle_id: str
    simulation_time: float
    scenario_id: Optional[str]
    family: str
    station_id: Optional[str]
    contribution: float
    reason: str

@dataclass
class QCGenerationRecord:
    vehicle_id: str
    simulation_time: float
    total_exposure: float
    probability_used: float
    qc_result: str

class LatentTruthLog:

    def __init__(self) -> None:
        self.scenario_truth: List[ScenarioTruthRecord] = []
        self.quality_exposure: List[QualityExposureRecord] = []
        self.qc_generation: List[QCGenerationRecord] = []
        self._exposure_totals: Dict[str, float] = {}

    def record_scenario(self, record: ScenarioTruthRecord) -> None:
        self.scenario_truth.append(record)

    def record_exposure(self, record: QualityExposureRecord) -> None:
        self.quality_exposure.append(record)
        self._exposure_totals[record.vehicle_id] = self._exposure_totals.get(record.vehicle_id, 0.0) + record.contribution

    def record_qc_generation(self, record: QCGenerationRecord) -> None:
        self.qc_generation.append(record)

    def total_exposure_by_vehicle(self) -> Dict[str, float]:
        return dict(self._exposure_totals)

    def total_exposure_for_vehicle(self, vehicle_id: str) -> float:
        return self._exposure_totals.get(vehicle_id, 0.0)
PROHIBITED_OBSERVABLE_FIELDS = {'scenario_type', 'scenario_id', 'scenario_severity', 'scenario_family', 'hidden_degradation_state', 'latent_quality_exposure', 'quality_exposure', 'future_defect', 'will_defect', 'bad_batch_truth', 'batch_is_bad', 'is_bad_batch', 'true_degradation_state', 'total_exposure', 'probability_used', 'intended_future_bottleneck', 'active_scenario_ids'}

# ---- merged from backend/simulation/scenarios/manager.py ----
"""
Pure scenario-to-effect mediator.
No RNG lives here; callers use named RNG streams.
"""
import random
from typing import Dict, List, Optional
_MAX_MULTIPLIER = 5.0

class ScenarioManager:

    def __init__(self, scenarios: List[ScenarioDefinition], latent_log: LatentTruthLog):
        self.scenarios = scenarios
        self.latent_log = latent_log
        for s in scenarios:
            latent_log.record_scenario(ScenarioTruthRecord(scenario_id=s.scenario_id, family=s.family.value, station_ids=list(s.station_ids), start_time=s.start_time, end_time=s.start_time + s.duration if s.duration is not None else None, severity=s.severity, params=dict(s.params), affected_batch_id=s.affected_batch_id))

    def _active(self, sim_time: float, families: set, station_id: Optional[str]=None):
        for s in self.scenarios:
            if s.family not in families or not s.is_active_at(sim_time):
                continue
            if station_id is not None and s.station_ids and (station_id not in s.station_ids):
                continue
            yield s

    def get_station_effects(self, sim_time: float, station_id: str, vehicle_id: str) -> StationEffectBundle:
        bundle = StationEffectBundle()
        for s in self._active(sim_time, {ScenarioFamily.EQUIPMENT_DEGRADATION}, station_id):
            if s.temporal_profile is None:
                ramp = s.params.get('ramp_duration_seconds', 3600.0)
                profile = max(0.0, min(1.0, (sim_time - s.start_time) / ramp)) if ramp > 0 else 1.0
                strength = s.severity * profile
            else:
                strength = s.strength(sim_time, 'GRADUAL')
            max_cycle = s.params.get('max_cycle_time_multiplier', 1.0)
            max_noise = s.params.get('max_noise_multiplier', 1.0)
            max_shift = s.params.get('max_sensor_mean_shift', 0.0)
            bundle.cycle_time_multiplier *= 1.0 + strength * (max_cycle - 1.0)
            bundle.variability_multiplier *= 1.0 + strength * (max_noise - 1.0)
            for sensor in s.affected_sensors:
                bundle.sensor_mean_shift[sensor] = bundle.sensor_mean_shift.get(sensor, 0.0) + strength * max_shift
                bundle.sensor_noise_multiplier[sensor] = bundle.sensor_noise_multiplier.get(sensor, 1.0) * (1.0 + strength * (max_noise - 1.0))
            bundle.active_scenario_ids.append(s.scenario_id)
            weight = s.params.get('quality_weight_per_visit', 0.0)
            if weight > 0 and strength > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, strength * weight, 'equipment_degradation')
        for s in self._active(sim_time, {ScenarioFamily.MANUAL_VARIATION}, station_id):
            strength = s.strength(sim_time, 'STEP')
            max_cycle = s.params.get('cycle_time_multiplier', 1.0)
            max_var = s.params.get('variability_multiplier', 1.0)
            bundle.cycle_time_multiplier *= 1.0 + strength * (max_cycle - 1.0)
            bundle.variability_multiplier *= 1.0 + strength * (max_var - 1.0)
            bundle.active_scenario_ids.append(s.scenario_id)
            weight = s.params.get('quality_weight_per_visit', 0.0)
            if weight > 0 and strength > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, strength * weight, 'manual_variation')
        for s in self._active(sim_time, {ScenarioFamily.ENVIRONMENTAL_DRIFT}, station_id):
            strength = s.strength(sim_time, 'GRADUAL')
            max_shift = s.params.get('max_sensor_mean_shift', 0.0)
            for sensor in s.affected_sensors:
                bundle.sensor_mean_shift[sensor] = bundle.sensor_mean_shift.get(sensor, 0.0) + strength * max_shift
            bundle.active_scenario_ids.append(s.scenario_id)
            threshold = s.params.get('deviation_threshold_fraction', 0.3)
            weight = s.params.get('quality_weight_per_visit', 0.0)
            excess = max(0.0, strength - threshold)
            if weight > 0 and excess > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, excess * weight, 'environmental_drift')
        for s in self._active(sim_time, {ScenarioFamily.SENSOR_DROPOUT}, station_id):
            strength = s.strength(sim_time, 'STEP')
            sensors = s.affected_sensors or ['__all__']
            probability = max(0.0, min(1.0, strength * s.params.get('dropout_probability', 1.0)))
            dropout_type = s.dropout_type.value if s.dropout_type else 'missing'
            for sensor in sensors:
                current = bundle.sensor_dropout_probability.get(sensor, -1.0)
                if probability > current:
                    bundle.sensor_dropout_probability[sensor] = probability
                    bundle.sensor_dropout_type[sensor] = dropout_type
            bundle.active_scenario_ids.append(s.scenario_id)
        bundle.cycle_time_multiplier = min(bundle.cycle_time_multiplier, _MAX_MULTIPLIER)
        bundle.variability_multiplier = min(bundle.variability_multiplier, _MAX_MULTIPLIER)
        for sensor in bundle.sensor_noise_multiplier:
            bundle.sensor_noise_multiplier[sensor] = min(bundle.sensor_noise_multiplier[sensor], _MAX_MULTIPLIER)
        return bundle

    def check_batch_exposure(self, vehicle_id: str, sim_time: float, station_id: str, batch_id: str) -> None:
        for s in self._active(sim_time, {ScenarioFamily.BAD_BATCH}, station_id):
            if s.affected_batch_id != batch_id:
                continue
            contribution = s.severity * s.params.get('quality_weight_per_visit', 0.0)
            if contribution > 0:
                self._record_exposure(vehicle_id, sim_time, s, station_id, contribution, 'bad_batch')

    def get_variant_mix_override(self, sim_time: float, baseline_mix: Optional[Dict[str, float]]=None) -> Optional[Dict[str, float]]:
        for s in self._active(sim_time, {ScenarioFamily.VEHICLE_MIX_OVERLOAD}):
            if not s.variant_mix_override:
                continue
            target = dict(s.variant_mix_override)
            if baseline_mix is None:
                return target
            strength = s.strength(sim_time, 'STEP')
            mixed = {variant: (1.0 - strength) * baseline_mix[variant] + strength * target[variant] for variant in baseline_mix}
            total = sum(mixed.values())
            return {k: v / total for k, v in mixed.items()}
        return None

    def get_micro_stop_params(self, sim_time: float, station_id: str) -> Optional[dict]:
        for s in self._active(sim_time, {ScenarioFamily.MICRO_STOPS}, station_id):
            strength = s.strength(sim_time, 'STEP')
            if 'rate_per_processing_minute' in s.params:
                return {'scenario_id': s.scenario_id, 'mode': 'rate_process', 'rate_per_processing_minute': s.params['rate_per_processing_minute'] * strength, 'min_duration': s.params.get('min_duration_seconds', 3.0), 'max_duration': s.params.get('max_duration_seconds', 15.0)}
            return {'scenario_id': s.scenario_id, 'mode': 'legacy_per_visit', 'probability': max(0.0, min(1.0, s.params.get('stop_probability', 0.0) * strength)), 'min_duration': s.params.get('min_duration_seconds', 5.0), 'max_duration': s.params.get('max_duration_seconds', 30.0)}
        return None

    def get_arrival_headway_multiplier(self, sim_time: float) -> float:
        multiplier = 1.0
        for s in self._active(sim_time, {ScenarioFamily.ARRIVAL_BURST}):
            target = s.params.get('headway_multiplier', 1.0)
            strength = s.strength(sim_time, 'STEP_BURST')
            multiplier *= 1.0 - strength * (1.0 - target)
        return max(0.4, min(1.0, multiplier))

    def roll_random_quality_event(self, vehicle_id: str, sim_time: float, rng: random.Random) -> None:
        for s in self._active(sim_time, {ScenarioFamily.RANDOM_QUALITY_EVENT}):
            probability = s.params.get('per_vehicle_probability', 0.01) * s.strength(sim_time, 'STEP')
            if rng.random() < probability:
                magnitude = rng.uniform(s.params.get('min_magnitude', 0.02), s.params.get('max_magnitude', 0.1))
                self._record_exposure(vehicle_id, sim_time, s, None, magnitude, 'random_quality_event')

    def _record_exposure(self, vehicle_id, sim_time, scenario: ScenarioDefinition, station_id, contribution, reason):
        self.latent_log.record_exposure(QualityExposureRecord(vehicle_id=vehicle_id, simulation_time=sim_time, scenario_id=scenario.scenario_id, family=scenario.family.value, station_id=station_id, contribution=contribution, reason=reason))

def empty_manager() -> ScenarioManager:
    return ScenarioManager([], LatentTruthLog())
