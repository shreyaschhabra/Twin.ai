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
configs/sensor_models.yaml, keyed by (station_id, sensor_name) — baselines
differ by station even for the same sensor family (e.g. weld_current at
S01 vs S02), so a single global per-sensor-name default would be wrong.

"cycle_time" is deliberately never generated as a SENSOR_READING: it would
duplicate information the STATION_PROCESSING_COMPLETED event already
carries (see events.py's documented "avoid duplicate events" principle).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import yaml
from pydantic import BaseModel

from backend.config.schemas import StationInstance
from backend.simulation.events import EventLog, EventType
from backend.simulation.rng import RNGStreamFactory
from backend.simulation.scenarios.effects import StationEffectBundle
from backend.simulation.vehicle import Vehicle

EXCLUDED_SENSORS = {"cycle_time"}


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
        raise FileNotFoundError(f"Sensor model config file not found: {resolved}")
    with resolved.open("r") as f:
        data = yaml.safe_load(f) or {}
    registry: SensorModelRegistry = {}
    for station_id, sensors in data.get("stations", {}).items():
        for sensor_name, fields in sensors.items():
            registry[(station_id, sensor_name)] = SensorDefinition(**fields)
    return registry


def generate_sensor_readings(
    station_cfg: StationInstance,
    vehicle: Vehicle,
    sim_time: float,
    effects: StationEffectBundle,
    sensor_models: SensorModelRegistry,
    rng_factory: RNGStreamFactory,
    event_log: EventLog,
) -> None:
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
            continue  # no model configured for this (station, sensor) pair

        dropout_type = effects.sensor_dropout_type.get(sensor_name)
        dropout_prob = effects.sensor_dropout_probability.get(sensor_name, 0.0)
        rng = rng_factory.get(f"sensor_noise::{station_id}::{sensor_name}")

        dropped_out = dropout_type is not None and rng.random() < dropout_prob

        if dropped_out and dropout_type == "missing":
            event_log.record(
                EventType.SENSOR_READING,
                simulation_time=sim_time,
                vehicle_id=vehicle.vehicle_id,
                vehicle_variant=vehicle.variant_id,
                station_id=station_id,
                sensor_name=sensor_name,
                unit=definition.unit,
                value=None,
                measurement_status="missing",
            )
            continue

        if dropped_out and dropout_type == "stuck":
            event_log.record(
                EventType.SENSOR_READING,
                simulation_time=sim_time,
                vehicle_id=vehicle.vehicle_id,
                vehicle_variant=vehicle.variant_id,
                station_id=station_id,
                sensor_name=sensor_name,
                unit=definition.unit,
                value=definition.baseline,
                measurement_status="stuck",
            )
            continue

        mean = definition.baseline + effects.sensor_mean_shift.get(sensor_name, 0.0)
        noise_multiplier = effects.sensor_noise_multiplier.get(sensor_name, 1.0)
        # extra noise for "noisy" dropout, on top of any scenario-driven
        # noise multiplier already present (e.g. concurrent degradation)
        if dropped_out and dropout_type == "noisy":
            noise_multiplier *= 4.0
        std = definition.noise_std * noise_multiplier

        value = rng.gauss(mean, std) if std > 0 else mean
        if definition.valid_min is not None:
            value = max(value, definition.valid_min)
        if definition.valid_max is not None:
            value = min(value, definition.valid_max)

        event_log.record(
            EventType.SENSOR_READING,
            simulation_time=sim_time,
            vehicle_id=vehicle.vehicle_id,
            vehicle_variant=vehicle.variant_id,
            station_id=station_id,
            sensor_name=sensor_name,
            unit=definition.unit,
            value=value,
            measurement_status="available",
        )
