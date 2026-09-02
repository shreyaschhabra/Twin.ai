from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Union
import yaml

"""
Strict, data-driven factory configuration schemas for TrustTwin.ai.

This module describes design-time factory truth only:
- station/equipment definitions
- buffers/topology
- vehicle routes and variant-specific work content
- optional manufacturing zones
- optional nominal production plan

It intentionally does NOT contain:
- scenario/fault labels
- future outcomes
- ML targets/predictions
- runtime station state
- hidden simulator truth

The configuration is deliberately suitable for both the development line and
the final line. Cross-reference validation is strict because silent config
mistakes can otherwise become data leakage, impossible routing, or stale-model
problems downstream.
"""
from enum import Enum
from math import isclose
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, field_validator, model_validator

class StrictConfigModel(BaseModel):
    """Base class for config objects.

    `extra="forbid"` is intentional. A misspelled YAML field must fail loudly
    rather than be silently ignored by Pydantic.
    """
    model_config = ConfigDict(extra='forbid')

class SensorMaturity(str, Enum):
    """Coarse station-level instrumentation maturity known at design time."""
    RICH = 'rich'
    PARTIAL = 'partial'
    POOR = 'poor'

class TrustState(str, Enum):
    """Runtime product vocabulary; not a static station property."""
    LIVE = 'live'
    INFERRED = 'inferred'
    UNKNOWN = 'unknown'

class ServiceTimeSemantics(str, Enum):
    """Meaning of `baseline_cycle_time_seconds`.

    UNIT_PROCESSING_TIME:
        One vehicle occupies the modeled station for approximately this long.

    EFFECTIVE_EXIT_HEADWAY:
        Capacity abstraction for a continuous/multi-vehicle process such as a
        cure tunnel. The value describes the effective exit/service headway,
        not physical vehicle residence time.
    """
    UNIT_PROCESSING_TIME = 'unit_processing_time'
    EFFECTIVE_EXIT_HEADWAY = 'effective_exit_headway'

class ArrivalProcess(str, Enum):
    """Nominal line-entry process used for baseline production planning."""
    FIXED_HEADWAY = 'fixed_headway'
    EXPONENTIAL = 'exponential'

class StationType(StrictConfigModel):
    """Reusable equipment/process template.

    `process_family` is retained for backward compatibility with existing
    configs, but it must NOT be used as the physical factory zone. A station
    type can appear in multiple zones.
    """
    type_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    process_family: str = Field(..., min_length=1)
    possible_sensor_families: List[str] = Field(default_factory=list)
    relevant_process_variables: List[str] = Field(default_factory=list)
    plausible_degradation_modes: List[str] = Field(default_factory=list)
    plausible_quality_risk_mechanisms: List[str] = Field(default_factory=list)

    @field_validator('possible_sensor_families', 'relevant_process_variables', 'plausible_degradation_modes', 'plausible_quality_risk_mechanisms')
    @classmethod
    def _unique_nonempty_strings(cls, value: List[str]) -> List[str]:
        if any((not item.strip() for item in value)):
            raise ValueError('list entries must be non-empty strings')
        if len(value) != len(set(value)):
            raise ValueError('list entries must be unique')
        return value

class StationVariantOverride(StrictConfigModel):
    """Variant-specific semantic operation and/or cycle-time override."""
    operation_profile: Optional[str] = Field(default=None, min_length=1)
    cycle_time_multiplier: Optional[PositiveFloat] = None

class StationInstance(StrictConfigModel):
    """One physical station instance."""
    station_id: str = Field(..., min_length=1)
    station_name: str = Field(..., min_length=1)
    station_type: str = Field(..., min_length=1)
    specific_operation: str = Field(..., min_length=1)
    baseline_cycle_time_seconds: PositiveFloat
    cycle_time_variability: float = Field(..., ge=0, le=1.0)
    service_time_semantics: ServiceTimeSemantics = ServiceTimeSemantics.UNIT_PROCESSING_TIME
    capacity: int = Field(default=1, gt=0)
    sensor_maturity: SensorMaturity
    available_sensors: List[str] = Field(default_factory=list)
    applicable_vehicle_variants: List[str] = Field(default_factory=list)
    process_parameters: Dict[str, float] = Field(default_factory=dict)
    variant_overrides: Dict[str, StationVariantOverride] = Field(default_factory=dict)
    sensor_justifications: Optional[Dict[str, str]] = None
    notes: Optional[str] = None

    @field_validator('available_sensors', 'applicable_vehicle_variants')
    @classmethod
    def _unique_lists(cls, value: List[str]) -> List[str]:
        if any((not item.strip() for item in value)):
            raise ValueError('list entries must be non-empty strings')
        if len(value) != len(set(value)):
            raise ValueError('list entries must be unique')
        return value

    @model_validator(mode='after')
    def _validate_justifications(self) -> 'StationInstance':
        if self.sensor_justifications:
            listed = set(self.available_sensors)
            stale = set(self.sensor_justifications) - listed
            if stale:
                raise ValueError(f'sensor_justifications contains signals not present in available_sensors: {sorted(stale)}')
            if any((not text.strip() for text in self.sensor_justifications.values())):
                raise ValueError('sensor_justifications values must be non-empty')
        return self

class Buffer(StrictConfigModel):
    """Finite WIP buffer on one directed route edge."""
    buffer_id: str = Field(..., min_length=1)
    upstream_station: str = Field(..., min_length=1)
    downstream_station: str = Field(..., min_length=1)
    capacity: int = Field(..., gt=0)

    @model_validator(mode='after')
    def _not_self_loop(self) -> 'Buffer':
        if self.upstream_station == self.downstream_station:
            raise ValueError('buffer cannot connect a station to itself')
        return self

class VehicleVariant(StrictConfigModel):
    """One producible vehicle variant and its ordered station route."""
    variant_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    route: List[str] = Field(..., min_length=1)
    processing_time_modifiers: Dict[str, PositiveFloat] = Field(default_factory=dict)
    notes: Optional[str] = None

    @field_validator('route')
    @classmethod
    def _route_has_no_duplicate_station(cls, value: List[str]) -> List[str]:
        if len(value) != len(set(value)):
            raise ValueError('a vehicle route may not visit the same station twice')
        return value

class ZoneDefinition(StrictConfigModel):
    """Machine-readable logical manufacturing zone."""
    display_name: str = Field(..., min_length=1)
    stations: List[str] = Field(..., min_length=1)

    @field_validator('stations')
    @classmethod
    def _unique_stations(cls, value: List[str]) -> List[str]:
        if len(value) != len(set(value)):
            raise ValueError('zone station list must be unique')
        return value

class ProductionPlan(StrictConfigModel):
    """Nominal healthy line-entry plan.

    This is design-time information, not an ML label. Keeping demand and
    baseline variant mix in config prevents hidden hard-coded workload choices
    in simulator/training scripts.
    """
    nominal_interarrival_seconds: PositiveFloat
    baseline_variant_mix: Dict[str, float]
    arrival_process: ArrivalProcess = ArrivalProcess.FIXED_HEADWAY
    notes: Optional[str] = None

    @model_validator(mode='after')
    def _validate_mix(self) -> 'ProductionPlan':
        if not self.baseline_variant_mix:
            raise ValueError('baseline_variant_mix cannot be empty')
        for variant_id, probability in self.baseline_variant_mix.items():
            if probability < 0 or probability > 1:
                raise ValueError(f'baseline_variant_mix[{variant_id!r}] must be between 0 and 1')
        total = sum(self.baseline_variant_mix.values())
        if not isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-09):
            raise ValueError(f'baseline_variant_mix must sum to 1.0, got {total:.12f}')
        return self

class FactoryConfig(StrictConfigModel):
    """Complete internally-consistent design-time factory definition."""
    schema_version: int = Field(default=1, ge=1)
    factory_config_id: Optional[str] = Field(default=None, min_length=1)
    line_name: str = Field(..., min_length=1)
    station_types: Dict[str, StationType]
    stations: Dict[str, StationInstance]
    buffers: Dict[str, Buffer]
    vehicle_variants: Dict[str, VehicleVariant]
    zones: Dict[str, ZoneDefinition] = Field(default_factory=dict)
    production_plan: Optional[ProductionPlan] = None
    factory_config_hash: Optional[str] = Field(default=None, pattern='^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def _validate_cross_references(self) -> 'FactoryConfig':
        errors: List[str] = []
        self._check_mapping_keys(errors)
        self._check_station_types_and_signals(errors)
        self._check_variant_station_consistency(errors)
        route_edges = self._check_routes(errors)
        buffer_edges = self._check_buffers(errors)
        self._check_route_buffer_equivalence(route_edges, buffer_edges, errors)
        self._check_zones(errors)
        self._check_production_plan(errors)
        if _has_cycle({a: {b for x, b in route_edges if x == a} for a, _ in route_edges}):
            errors.append('variant route graph contains a cycle')
        if errors:
            raise ValueError('FactoryConfig failed cross-reference validation:\n- ' + '\n- '.join(errors))
        return self

    def _check_mapping_keys(self, errors: List[str]) -> None:
        mappings = (('station_types', self.station_types, 'type_id'), ('stations', self.stations, 'station_id'), ('buffers', self.buffers, 'buffer_id'), ('vehicle_variants', self.vehicle_variants, 'variant_id'))
        for mapping_name, mapping, id_field in mappings:
            for key, item in mapping.items():
                actual = getattr(item, id_field)
                if key != actual:
                    errors.append(f"{mapping_name} key '{key}' does not match {id_field} '{actual}'")

    def _check_station_types_and_signals(self, errors: List[str]) -> None:
        for station in self.stations.values():
            station_type = self.station_types.get(station.station_type)
            if station_type is None:
                errors.append(f"station '{station.station_id}' references unknown station_type '{station.station_type}'")
                continue
            justified = set((station.sensor_justifications or {}).keys())
            allowed = set(station_type.possible_sensor_families)
            for sensor in station.available_sensors:
                if sensor not in allowed and sensor not in justified:
                    errors.append(f"station '{station.station_id}' lists signal '{sensor}' not in station_type '{station.station_type}' possible_sensor_families and not justified")

    def _check_variant_station_consistency(self, errors: List[str]) -> None:
        route_membership = {variant_id: set(variant.route) for variant_id, variant in self.vehicle_variants.items()}
        for station in self.stations.values():
            for variant_id in station.applicable_vehicle_variants:
                if variant_id not in self.vehicle_variants:
                    errors.append(f"station '{station.station_id}' lists unknown applicable variant '{variant_id}'")
                elif station.station_id not in route_membership[variant_id]:
                    errors.append(f"station '{station.station_id}' says variant '{variant_id}' is applicable, but the variant route does not visit it")
            for variant_id, variant in self.vehicle_variants.items():
                visits = station.station_id in route_membership[variant_id]
                declared = variant_id in station.applicable_vehicle_variants
                if visits and (not declared):
                    errors.append(f"variant '{variant_id}' visits station '{station.station_id}' but station.applicable_vehicle_variants omits it")
            for variant_id in station.variant_overrides:
                if variant_id not in self.vehicle_variants:
                    errors.append(f"station '{station.station_id}' variant_overrides references unknown variant '{variant_id}'")
                elif variant_id not in station.applicable_vehicle_variants:
                    errors.append(f"station '{station.station_id}' variant_overrides has '{variant_id}' but that variant is not applicable")
                elif station.station_id in self.vehicle_variants[variant_id].processing_time_modifiers:
                    errors.append(f"cycle-time multiplier for station '{station.station_id}', variant '{variant_id}' is defined in BOTH station.variant_overrides and vehicle_variant.processing_time_modifiers")

    def _check_routes(self, errors: List[str]) -> set[tuple[str, str]]:
        all_edges: set[tuple[str, str]] = set()
        visited_stations: set[str] = set()
        for variant in self.vehicle_variants.values():
            for station_id in variant.route:
                if station_id not in self.stations:
                    errors.append(f"variant '{variant.variant_id}' route references unknown station '{station_id}'")
                visited_stations.add(station_id)
            route_set = set(variant.route)
            for station_id in variant.processing_time_modifiers:
                if station_id not in self.stations:
                    errors.append(f"variant '{variant.variant_id}' processing_time_modifiers references unknown station '{station_id}'")
                elif station_id not in route_set:
                    errors.append(f"variant '{variant.variant_id}' processing_time_modifiers contains '{station_id}', which is not on its route")
            all_edges.update(zip(variant.route, variant.route[1:]))
        unreachable = set(self.stations) - visited_stations
        if unreachable:
            errors.append('stations not visited by any vehicle variant: ' + ', '.join(sorted(unreachable)))
        return all_edges

    def _check_buffers(self, errors: List[str]) -> Dict[tuple[str, str], str]:
        edge_to_buffer: Dict[tuple[str, str], str] = {}
        for buffer in self.buffers.values():
            if buffer.upstream_station not in self.stations:
                errors.append(f"buffer '{buffer.buffer_id}' references unknown upstream station '{buffer.upstream_station}'")
            if buffer.downstream_station not in self.stations:
                errors.append(f"buffer '{buffer.buffer_id}' references unknown downstream station '{buffer.downstream_station}'")
            edge = (buffer.upstream_station, buffer.downstream_station)
            if edge in edge_to_buffer:
                errors.append(f"duplicate buffers '{edge_to_buffer[edge]}' and '{buffer.buffer_id}' represent route edge {edge}")
            else:
                edge_to_buffer[edge] = buffer.buffer_id
        return edge_to_buffer

    @staticmethod
    def _check_route_buffer_equivalence(route_edges: set[tuple[str, str]], buffer_edges: Dict[tuple[str, str], str], errors: List[str]) -> None:
        missing = route_edges - set(buffer_edges)
        if missing:
            errors.append('route transitions missing a buffer: ' + ', '.join((f'{a}->{b}' for a, b in sorted(missing))))
        unused = set(buffer_edges) - route_edges
        if unused:
            errors.append('buffers not used by any configured route: ' + ', '.join((f'{buffer_edges[a, b]}({a}->{b})' for a, b in sorted(unused))))

    def _check_zones(self, errors: List[str]) -> None:
        if not self.zones:
            return
        assigned: Dict[str, str] = {}
        for zone_id, zone in self.zones.items():
            for station_id in zone.stations:
                if station_id not in self.stations:
                    errors.append(f"zone '{zone_id}' references unknown station '{station_id}'")
                    continue
                if station_id in assigned:
                    errors.append(f"station '{station_id}' appears in both zone '{assigned[station_id]}' and '{zone_id}'")
                assigned[station_id] = zone_id
        missing = set(self.stations) - set(assigned)
        if missing:
            errors.append('zones are configured but do not cover stations: ' + ', '.join(sorted(missing)))

    def _check_production_plan(self, errors: List[str]) -> None:
        if self.production_plan is None:
            return
        mix_keys = set(self.production_plan.baseline_variant_mix)
        variant_keys = set(self.vehicle_variants)
        if mix_keys != variant_keys:
            missing = variant_keys - mix_keys
            extra = mix_keys - variant_keys
            if missing:
                errors.append('production_plan.baseline_variant_mix missing variants: ' + ', '.join(sorted(missing)))
            if extra:
                errors.append('production_plan.baseline_variant_mix references unknown variants: ' + ', '.join(sorted(extra)))

    def route_edges(self, variant_id: str) -> List[tuple[str, str]]:
        variant = self.vehicle_variants[variant_id]
        return list(zip(variant.route, variant.route[1:]))

    def cycle_time_multiplier(self, station_id: str, variant_id: str) -> float:
        """Resolve the single source of truth for station+variant work content."""
        station = self.stations[station_id]
        variant = self.vehicle_variants[variant_id]
        override = station.variant_overrides.get(variant_id)
        if override and override.cycle_time_multiplier is not None:
            return float(override.cycle_time_multiplier)
        return float(variant.processing_time_modifiers.get(station_id, 1.0))

    def nominal_service_seconds(self, station_id: str, variant_id: str) -> float:
        station = self.stations[station_id]
        if station_id not in self.vehicle_variants[variant_id].route:
            raise ValueError(f"variant '{variant_id}' does not visit station '{station_id}'")
        return float(station.baseline_cycle_time_seconds) * self.cycle_time_multiplier(station_id, variant_id)

    def nominal_utilization_by_station(self) -> Dict[str, float]:
        """Expected healthy utilization implied by mix, routing and takt.

        For each line arrival, variant `v` contributes its route-specific
        service demand at station `i`. For station capacity `c_i` and nominal
        interarrival headway `H`:

            rho_i = sum_v p(v) * I(v visits i) * service_i(v) / (H * c_i)

        This is a design-time audit, not an ML label.
        """
        if self.production_plan is None:
            raise ValueError('nominal_utilization_by_station requires production_plan')
        headway = float(self.production_plan.nominal_interarrival_seconds)
        mix = self.production_plan.baseline_variant_mix
        utilization: Dict[str, float] = {}
        for station_id, station in self.stations.items():
            workload_per_line_arrival = 0.0
            for variant_id, probability in mix.items():
                if station_id in self.vehicle_variants[variant_id].route:
                    workload_per_line_arrival += probability * self.nominal_service_seconds(station_id, variant_id)
            utilization[station_id] = workload_per_line_arrival / (headway * station.capacity)
        return utilization

    def zone_for_station(self, station_id: str) -> Optional[str]:
        for zone_id, zone in self.zones.items():
            if station_id in zone.stations:
                return zone_id
        return None

def _has_cycle(edges: Dict[str, set[str]]) -> bool:
    """DFS cycle detection for a small directed factory graph."""
    WHITE, GRAY, BLACK = (0, 1, 2)
    color: Dict[str, int] = {}

    def visit(node: str) -> bool:
        color[node] = GRAY
        for neighbor in edges.get(node, ()):
            state = color.get(neighbor, WHITE)
            if state == GRAY:
                return True
            if state == WHITE and visit(neighbor):
                return True
        color[node] = BLACK
        return False
    all_nodes = set(edges) | {n for targets in edges.values() for n in targets}
    for node in all_nodes:
        if color.get(node, WHITE) == WHITE and visit(node):
            return True
    return False

PathLike = Union[str, Path]

class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass

def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"Duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping

_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)

def read_config(path: PathLike) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open('r', encoding='utf-8') as f:
        data = yaml.load(f, Loader=_UniqueKeySafeLoader) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Top level of {path} must be a mapping")
    return data

def _mapping(data, key, source, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise ValueError(f"Missing required section '{key}' in {source}")
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"Section '{key}' in {source} must be a mapping")
    return value

def _fingerprint(config: FactoryConfig) -> str:
    payload = config.model_dump(mode='json', exclude={'factory_config_hash'}, exclude_none=False)
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()

def load_factory_config(path: PathLike, *, expected_config_hash: Optional[str] = None) -> FactoryConfig:
    raw = read_config(path)
    allowed = {'schema_version','station_types','factory','sensor_models','batch_relevant_stations'}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"Unknown top-level keys in {path}: {sorted(unknown)}")
    station_types_raw = _mapping(raw, 'station_types', path)
    line_raw = _mapping(raw, 'factory', path)
    required_line = {'line_name','stations','buffers','vehicle_variants'}
    missing = required_line - set(line_raw)
    if missing:
        raise ValueError(f"Missing required factory keys in {path}: {sorted(missing)}")

    station_types = {
        type_id: StationType(**{**fields, 'type_id': type_id})
        for type_id, fields in station_types_raw.items()
    }
    stations = {
        station_id: StationInstance(**{**fields, 'station_id': station_id})
        for station_id, fields in _mapping(line_raw, 'stations', path).items()
    }
    buffers = {
        buffer_id: Buffer(**{**fields, 'buffer_id': buffer_id})
        for buffer_id, fields in _mapping(line_raw, 'buffers', path).items()
    }
    vehicle_variants = {
        variant_id: VehicleVariant(**{**fields, 'variant_id': variant_id})
        for variant_id, fields in _mapping(line_raw, 'vehicle_variants', path).items()
    }
    zones = {
        zone_id: ZoneDefinition(**fields)
        for zone_id, fields in _mapping(line_raw, 'zones', path, required=False).items()
    }
    production_plan = None
    if line_raw.get('production_plan') is not None:
        if not isinstance(line_raw['production_plan'], Mapping):
            raise TypeError(f"'production_plan' in {path} must be a mapping")
        production_plan = ProductionPlan(**dict(line_raw['production_plan']))

    config = FactoryConfig(
        schema_version=int(raw.get('schema_version', 1)),
        factory_config_id=line_raw.get('factory_config_id'),
        line_name=line_raw['line_name'],
        station_types=station_types,
        stations=stations,
        buffers=buffers,
        vehicle_variants=vehicle_variants,
        zones=zones,
        production_plan=production_plan,
    )
    fingerprint = _fingerprint(config)
    config = config.model_copy(update={'factory_config_hash': fingerprint})
    if expected_config_hash is not None and fingerprint != expected_config_hash:
        raise ValueError(
            f"Factory configuration hash mismatch: expected {expected_config_hash}, loaded {fingerprint}."
        )
    return config
