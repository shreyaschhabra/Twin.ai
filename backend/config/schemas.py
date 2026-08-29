"""
Data-driven factory configuration schemas for TrustTwin.ai.

These models describe WHAT the line looks like (stations, buffers, vehicle
variants, sensor availability). They intentionally contain no simulation
behavior, no ML logic, and no runtime state. A YAML file conforming to these
schemas should be loadable for either the 12-station development line or the
eventual 45-station production line without any code changes here.

IMPORTANT (per PRD Section 26 / project ground rules): station configuration
must never carry hidden future-outcome information (e.g. a future defect
label, a scenario ID, a "this station will fail" flag). Everything modeled
here is information that would plausibly be knowable about a real station's
design and instrumentation ahead of time.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class SensorMaturity(str, Enum):
    """How well-instrumented a station instance is, as a design-time fact."""

    RICH = "rich"
    PARTIAL = "partial"
    POOR = "poor"


class TrustState(str, Enum):
    """
    Product-facing runtime trust states (see PRD Section 22 / Round-1 concept).

    NOT a static config field. This enum is defined here only so later layers
    (twin state, API, frontend) share one vocabulary. At runtime, roughly:
      - RICH-sensor stations can produce LIVE trust for their available signals
      - PARTIAL-sensor stations often produce INFERRED estimates for signals
        they don't directly measure
      - POOR-sensor stations mostly produce UNKNOWN for process variables,
        relying on manual checklists / timestamps
    That mapping is a later-step behavior, not something this config encodes.
    """

    LIVE = "live"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class StationType(BaseModel):
    """A reusable template describing a family of stations (e.g. all torque
    stations), independent of any specific station instance's operation."""

    type_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    process_family: str = Field(..., min_length=1)
    possible_sensor_families: List[str] = Field(default_factory=list)
    relevant_process_variables: List[str] = Field(default_factory=list)
    plausible_degradation_modes: List[str] = Field(default_factory=list)
    plausible_quality_risk_mechanisms: List[str] = Field(default_factory=list)


class StationVariantOverride(BaseModel):
    """Describes how one vehicle variant's experience at a station differs
    from the station's default, when that difference is more than a plain
    speed multiplier.

    `operation_profile` names what the variant actually DOES at this
    station (e.g. "battery_pack_marriage" vs. "powertrain_marriage") — two
    variants can share a physical station while running semantically
    different processes with different degradation/quality-risk mechanisms.
    `cycle_time_multiplier`, when present here, is the source of truth for
    that station+variant pair and takes precedence over any entry for the
    same station in that variant's `processing_time_modifiers` (see
    VehicleVariant). Stations/variants that only need a plain speed
    difference (no distinct operation) should keep using
    `processing_time_modifiers` instead of adding an override here, to
    avoid two places defining the same number.
    """

    operation_profile: Optional[str] = None
    cycle_time_multiplier: Optional[float] = Field(default=None, gt=0)


class StationInstance(BaseModel):
    """One physical station on the line. `station_type` links back to a
    StationType; `specific_operation` is what makes this instance distinct
    from another station of the same type (PRD example: two TORQUE stations
    performing different fastening operations)."""

    station_id: str = Field(..., min_length=1)
    station_name: str = Field(..., min_length=1)
    station_type: str = Field(..., min_length=1)
    specific_operation: str = Field(..., min_length=1)
    baseline_cycle_time_seconds: float = Field(..., gt=0)
    cycle_time_variability: float = Field(..., ge=0)
    sensor_maturity: SensorMaturity
    available_sensors: List[str] = Field(default_factory=list)
    applicable_vehicle_variants: List[str] = Field(default_factory=list)
    process_parameters: Dict[str, float] = Field(default_factory=dict)
    variant_overrides: Dict[str, StationVariantOverride] = Field(default_factory=dict)
    sensor_justifications: Optional[Dict[str, str]] = None
    notes: Optional[str] = None


class Buffer(BaseModel):
    """A WIP buffer sitting on one edge of the line graph, between an
    upstream and downstream station."""

    buffer_id: str = Field(..., min_length=1)
    upstream_station: str = Field(..., min_length=1)
    downstream_station: str = Field(..., min_length=1)
    capacity: int = Field(..., gt=0)


class VehicleVariant(BaseModel):
    """One producible vehicle variant and the ordered list of stations it
    visits. Routes may differ in length/order between variants (skips), but
    should mostly overlap."""

    variant_id: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)
    route: List[str] = Field(..., min_length=1)
    processing_time_modifiers: Dict[str, float] = Field(default_factory=dict)
    notes: Optional[str] = None


class FactoryConfig(BaseModel):
    """Top-level container for one complete, internally-consistent line
    configuration (e.g. the 12-station dev line or the 45-station final
    line). All cross-referential validation happens here, after every
    sub-model has already validated its own fields."""

    line_name: str
    station_types: Dict[str, StationType]
    stations: Dict[str, StationInstance]
    buffers: Dict[str, Buffer]
    vehicle_variants: Dict[str, VehicleVariant]

    @model_validator(mode="after")
    def _validate_cross_references(self) -> "FactoryConfig":
        errors: List[str] = []

        # station_id keys must match the station's own station_id field
        for key, station in self.stations.items():
            if key != station.station_id:
                errors.append(
                    f"stations key '{key}' does not match station_id "
                    f"'{station.station_id}'"
                )

        # every station must reference a real station type
        for station in self.stations.values():
            if station.station_type not in self.station_types:
                errors.append(
                    f"station '{station.station_id}' references unknown "
                    f"station_type '{station.station_type}'"
                )

        # every listed sensor must belong to the station type's possible
        # sensor families, unless explicitly justified on the instance
        for station in self.stations.values():
            station_type = self.station_types.get(station.station_type)
            if station_type is None:
                continue  # already reported above
            justified = set((station.sensor_justifications or {}).keys())
            allowed = set(station_type.possible_sensor_families)
            for sensor in station.available_sensors:
                if sensor not in allowed and sensor not in justified:
                    errors.append(
                        f"station '{station.station_id}' lists sensor "
                        f"'{sensor}' not in station_type "
                        f"'{station.station_type}' possible_sensor_families "
                        f"and not justified via sensor_justifications"
                    )

        # variant_overrides must reference real, applicable variants
        for station in self.stations.values():
            for variant_id in station.variant_overrides:
                if variant_id not in self.vehicle_variants:
                    errors.append(
                        f"station '{station.station_id}' variant_overrides "
                        f"references unknown variant '{variant_id}'"
                    )
                elif variant_id not in station.applicable_vehicle_variants:
                    errors.append(
                        f"station '{station.station_id}' variant_overrides "
                        f"has an entry for '{variant_id}' but that variant "
                        f"is not in applicable_vehicle_variants"
                    )

        # every buffer must reference real stations
        for buffer in self.buffers.values():
            if buffer.upstream_station not in self.stations:
                errors.append(
                    f"buffer '{buffer.buffer_id}' references unknown "
                    f"upstream_station '{buffer.upstream_station}'"
                )
            if buffer.downstream_station not in self.stations:
                errors.append(
                    f"buffer '{buffer.buffer_id}' references unknown "
                    f"downstream_station '{buffer.downstream_station}'"
                )

        # every variant route must reference real stations
        for variant in self.vehicle_variants.values():
            for station_id in variant.route:
                if station_id not in self.stations:
                    errors.append(
                        f"variant '{variant.variant_id}' route references "
                        f"unknown station '{station_id}'"
                    )
            for station_id in variant.processing_time_modifiers:
                if station_id not in self.stations:
                    errors.append(
                        f"variant '{variant.variant_id}' "
                        f"processing_time_modifiers references unknown "
                        f"station '{station_id}'"
                    )

        # route graph (union of all variant routes, as directed edges
        # between consecutive stations) must not contain a cycle
        edges: Dict[str, set] = {}
        for variant in self.vehicle_variants.values():
            for a, b in zip(variant.route, variant.route[1:]):
                edges.setdefault(a, set()).add(b)
        if _has_cycle(edges):
            errors.append("variant route graph contains a cycle")

        if errors:
            raise ValueError(
                "FactoryConfig failed cross-reference validation:\n- "
                + "\n- ".join(errors)
            )

        return self


def _has_cycle(edges: Dict[str, set]) -> bool:
    """Simple DFS-based cycle detection over a directed graph given as an
    adjacency dict. No external graph library needed for a line this small."""

    WHITE, GRAY, BLACK = 0, 1, 2
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

    all_nodes = set(edges.keys()) | {n for targets in edges.values() for n in targets}
    for node in all_nodes:
        if color.get(node, WHITE) == WHITE:
            if visit(node):
                return True
    return False
