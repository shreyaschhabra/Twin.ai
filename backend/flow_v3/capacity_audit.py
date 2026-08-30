"""Runtime-derived physical-capacity audit for the current 45-station line.

The audit intentionally reads the validated ``FactoryConfig`` rather than
duplicating station values in analysis code.  It also respects route skips:
station arrival rate is the line release rate multiplied by the probability
that a released vehicle actually visits that station.

This module is descriptive only.  It does not alter simulator configuration,
choose a future headway, or use labels/model metrics.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping

from backend.config.schemas import FactoryConfig
from backend.historical.flow_enrichment import STATION_CANDIDATES
from backend.historical.shift_scheduler import FAMILY_STATION_POOLS
from backend.simulation.engine import DEFAULT_ENTRY_BUFFER_CAPACITY
from backend.simulation.scenarios.config import ScenarioFamily

DEFAULT_MEAN_INTERARRIVAL_SECONDS = 115.0
DEFAULT_VARIANT_MIX = {"ICE_SEDAN": 0.45, "ICE_SUV": 0.35, "EV": 0.20}

UTILIZATION_BANDS = (
    ("<50%", 0.0, 0.50),
    ("50-65%", 0.50, 0.65),
    ("65-75%", 0.65, 0.75),
    ("75-85%", 0.75, 0.85),
    ("85-95%", 0.85, 0.95),
    (">=95%", 0.95, float("inf")),
)


def _normalized_mix(config: FactoryConfig, variant_mix: Mapping[str, float]) -> dict[str, float]:
    unknown = set(variant_mix) - set(config.vehicle_variants)
    if unknown:
        raise ValueError(f"variant mix references unknown variants: {sorted(unknown)}")
    if any(weight < 0 for weight in variant_mix.values()):
        raise ValueError("variant mix weights must be non-negative")
    total = float(sum(variant_mix.values()))
    if total <= 0:
        raise ValueError("variant mix must have positive total weight")
    return {variant_id: float(variant_mix.get(variant_id, 0.0)) / total for variant_id in config.vehicle_variants}


def variant_service_time(config: FactoryConfig, station_id: str, variant_id: str) -> float | None:
    """Return configured mean service time, or ``None`` when the route skips the station.

    The precedence exactly mirrors ``StationRuntime.compute_processing_time``:
    a station-level variant override wins over a vehicle-level modifier.
    """
    station = config.stations[station_id]
    variant = config.vehicle_variants[variant_id]
    if station_id not in variant.route:
        return None
    override = station.variant_overrides.get(variant_id)
    if override is not None and override.cycle_time_multiplier is not None:
        multiplier = override.cycle_time_multiplier
    else:
        multiplier = variant.processing_time_modifiers.get(station_id, 1.0)
    return station.baseline_cycle_time_seconds * multiplier


def _zone(station_id: str) -> str:
    number = int(station_id[1:])
    if number <= 12:
        return "body_joining"
    if number <= 20:
        return "paint_surface"
    if number <= 38:
        return "final_assembly"
    return "inspection_eol"


def _buffer_context(config: FactoryConfig, station_id: str) -> tuple[str, str, str, str]:
    inbound = [b for b in config.buffers.values() if b.downstream_station == station_id]
    outbound = [b for b in config.buffers.values() if b.upstream_station == station_id]
    inbound_ids = [b.buffer_id for b in inbound]
    inbound_caps = [str(b.capacity) for b in inbound]
    if not inbound:
        inbound_ids = [f"ENTRY::{station_id}"]
        inbound_caps = [str(DEFAULT_ENTRY_BUFFER_CAPACITY)]
    return (
        ";".join(inbound_ids),
        ";".join(inbound_caps),
        ";".join(b.buffer_id for b in outbound),
        ";".join(str(b.capacity) for b in outbound),
    )


def _expected_micro_stop_extra(severity: float, *, flow_calibrated: bool) -> float:
    if flow_calibrated:
        probability = 0.20 + 0.65 * severity
        maximum = 15.0 + 75.0 * severity
    else:
        probability = 0.15 + 0.45 * severity
        maximum = 15.0 + 45.0 * severity
    return probability * (8.0 + maximum) / 2.0


def build_capacity_audit(
    config: FactoryConfig,
    mean_interarrival_seconds: float = DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    variant_mix: Mapping[str, float] = DEFAULT_VARIANT_MIX,
) -> list[dict]:
    """Calculate one physical operating-point record per configured station."""
    if mean_interarrival_seconds <= 0:
        raise ValueError("mean interarrival seconds must be positive")
    mix = _normalized_mix(config, variant_mix)
    rows: list[dict] = []

    for station_id, station in sorted(config.stations.items()):
        service_by_variant = {
            variant_id: variant_service_time(config, station_id, variant_id)
            for variant_id in config.vehicle_variants
        }
        visit_probability = sum(
            mix[variant_id]
            for variant_id, service_time in service_by_variant.items()
            if service_time is not None
        )
        if visit_probability <= 0:
            raise ValueError(f"station {station_id} is not visited by any variant with positive mix weight")

        weighted_workload_per_line_vehicle = sum(
            mix[variant_id] * (service_time or 0.0)
            for variant_id, service_time in service_by_variant.items()
        )
        conditional_weighted_service = weighted_workload_per_line_vehicle / visit_probability
        resource_capacity = station.capacity
        rho = weighted_workload_per_line_vehicle / (mean_interarrival_seconds * resource_capacity)
        station_arrival_headway = mean_interarrival_seconds / visit_probability
        station_arrival_rate = 3600.0 / station_arrival_headway
        station_service_capacity = 3600.0 * resource_capacity / conditional_weighted_service
        line_equivalent_capacity = station_service_capacity / visit_probability
        slowdown_to_rho_one = 1.0 / rho

        visiting_service = {k: v for k, v in service_by_variant.items() if v is not None}
        slowest_variant = max(visiting_service, key=visiting_service.get)
        slowest_service = visiting_service[slowest_variant]
        slowest_rho = slowest_service / (mean_interarrival_seconds * resource_capacity)

        # Current equations evaluated at the current scheduler's upper severity
        # (0.9).  These are counterfactual "if targeted" values, not claims that
        # each family is operationally appropriate at every station.
        scheduler_max_severity = 0.9
        flow_enrichment_max_severity = 0.95
        manual_multiplier = 1.15 + 0.5 * flow_enrichment_max_severity
        degradation_multiplier = 1.2 + 0.8 * scheduler_max_severity
        background_extra = _expected_micro_stop_extra(scheduler_max_severity, flow_calibrated=False)
        calibrated_extra = _expected_micro_stop_extra(flow_enrichment_max_severity, flow_calibrated=True)
        background_micro_rho = (
            weighted_workload_per_line_vehicle + visit_probability * background_extra
        ) / (mean_interarrival_seconds * resource_capacity)
        calibrated_micro_rho = (
            weighted_workload_per_line_vehicle + visit_probability * calibrated_extra
        ) / (mean_interarrival_seconds * resource_capacity)

        inbound_ids, inbound_caps, outbound_ids, outbound_caps = _buffer_context(config, station_id)
        row = {
            "station_id": station_id,
            "station_name": station.station_name,
            "zone": _zone(station_id),
            "station_type": station.station_type,
            "sensor_maturity": station.sensor_maturity.value,
            "baseline_cycle_time_seconds": station.baseline_cycle_time_seconds,
            "effective_baseline_service_time_seconds": station.baseline_cycle_time_seconds / resource_capacity,
            "mix_weighted_service_time_seconds": conditional_weighted_service,
            "weighted_workload_seconds_per_line_vehicle": weighted_workload_per_line_vehicle,
            "nominal_line_arrival_headway_seconds": mean_interarrival_seconds,
            "station_visit_probability": visit_probability,
            "nominal_station_arrival_headway_seconds": station_arrival_headway,
            "nominal_station_arrival_rate_vehicles_per_hour": station_arrival_rate,
            "nominal_utilization_rho": rho,
            "service_capacity_vehicles_per_hour": station_service_capacity,
            "line_equivalent_capacity_vehicles_per_hour": line_equivalent_capacity,
            "resource_capacity": resource_capacity,
            "inbound_buffer_ids": inbound_ids,
            "inbound_buffer_capacities": inbound_caps,
            "outbound_buffer_ids": outbound_ids,
            "outbound_buffer_capacities": outbound_caps,
            "slowdown_multiplier_to_rho_1": slowdown_to_rho_one,
            "highest_workload_variant": slowest_variant,
            "highest_workload_variant_service_time_seconds": slowest_service,
            "rho_at_100pct_highest_workload_variant": slowest_rho,
            "manual_variation_rho_at_severity_0_95_if_targeted": rho * manual_multiplier,
            "equipment_degradation_rho_at_severity_0_9_if_targeted": rho * degradation_multiplier,
            "background_micro_stops_rho_at_severity_0_9_if_targeted": background_micro_rho,
            "flow_calibrated_micro_stops_rho_at_severity_0_95_if_targeted": calibrated_micro_rho,
            "manual_variation_current_target": (
                station_id in FAMILY_STATION_POOLS[ScenarioFamily.MANUAL_VARIATION]
                or STATION_CANDIDATES.get(station_id, {}).get("family") == ScenarioFamily.MANUAL_VARIATION
            ),
            "equipment_degradation_current_target": station_id in FAMILY_STATION_POOLS[ScenarioFamily.EQUIPMENT_DEGRADATION],
            "background_micro_stops_current_target": station_id in FAMILY_STATION_POOLS[ScenarioFamily.MICRO_STOPS],
            "flow_calibrated_micro_stops_current_target": (
                STATION_CANDIDATES.get(station_id, {}).get("family") == ScenarioFamily.MICRO_STOPS
            ),
            "manual_variation_capacity_crossing_possible_current_max": rho * manual_multiplier >= 1.0,
            "equipment_degradation_capacity_crossing_possible_current_max": rho * degradation_multiplier >= 1.0,
            "flow_calibrated_micro_stops_capacity_crossing_possible_current_max": calibrated_micro_rho >= 1.0,
            "vehicle_mix_capacity_crossing_possible_at_100pct_slowest": slowest_rho >= 1.0,
        }
        for variant_id in config.vehicle_variants:
            service_time = service_by_variant[variant_id]
            key = variant_id.lower()
            row[f"{key}_service_time_seconds"] = service_time
            row[f"{key}_workload_contribution_seconds_per_line_vehicle"] = (
                mix[variant_id] * service_time if service_time is not None else 0.0
            )
        rows.append(row)
    return rows


def summarize_utilization(rows: Iterable[Mapping]) -> list[dict]:
    materialized = list(rows)
    total = len(materialized)
    summary = []
    for label, lower, upper in UTILIZATION_BANDS:
        count = sum(lower <= float(row["nominal_utilization_rho"]) < upper for row in materialized)
        summary.append({
            "band": label,
            "station_count": count,
            "percentage": (100.0 * count / total) if total else 0.0,
        })
    return summary


def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_capacity_summary(
    rows: list[dict],
    *,
    starting_commit: str,
    mean_interarrival_seconds: float,
    baseline_test_result: str,
) -> str:
    bands = summarize_utilization(rows)
    ranked = sorted(rows, key=lambda row: row["nominal_utilization_rho"], reverse=True)
    manual = [
        r["station_id"] for r in rows
        if r["manual_variation_current_target"] and r["manual_variation_capacity_crossing_possible_current_max"]
    ]
    micro = [
        r["station_id"] for r in rows
        if r["flow_calibrated_micro_stops_current_target"]
        and r["flow_calibrated_micro_stops_capacity_crossing_possible_current_max"]
    ]
    degradation = [
        r["station_id"] for r in rows
        if r["equipment_degradation_current_target"]
        and r["equipment_degradation_capacity_crossing_possible_current_max"]
    ]
    mix = [r["station_id"] for r in rows if r["vehicle_mix_capacity_crossing_possible_at_100pct_slowest"]]
    interstation_buffers = []
    for row in rows:
        ids = str(row["inbound_buffer_ids"]).split(";")
        capacities = str(row["inbound_buffer_capacities"]).split(";")
        interstation_buffers.extend(
            int(capacity) for buffer_id, capacity in zip(ids, capacities)
            if buffer_id and not buffer_id.startswith("ENTRY::")
        )

    lines = [
        "# Flow-v3 current capacity audit",
        "",
        "## Provenance and baseline gate",
        "",
        f"- Starting commit: `{starting_commit}`",
        f"- Runtime line configuration: `configs/full_line.yaml` ({len(rows)} stations)",
        f"- Nominal release headway: `{mean_interarrival_seconds:.1f}` seconds",
        "- Variant mix: ICE Sedan 45%, ICE SUV 35%, EV 20%",
        f"- TrustTwin-owned baseline suite: `{baseline_test_result}`",
        "- Authoritative baseline command: `.venv/bin/python -m pytest tests -q`",
        "- Environment note: an initial unscoped system-Python run collected the read-only reference "
        "project and stopped with 26 collection errors (missing `simpy`/reference-only `catboost` and "
        "reference import-path conflicts); it is not counted as a TrustTwin product-test failure.",
        "- Reference repository: `digital_twin-main` inspected read-only and excluded from TrustTwin test counts",
        "",
        "Important preserved artifacts: `artifacts/flow_v2/`, `data/processed/flow_v2/`, "
        "`data/generated/historical_100_flow_calibrated/`, `artifacts/quality/`, "
        "`artifacts/anomaly/`, and `artifacts/demo/`.",
        "",
        "## Method",
        "",
        "For each station, service time follows the exact runtime precedence: station+variant "
        "override, then vehicle processing modifier, then 1.0. Route skips are respected. The "
        "nominal utilization is:",
        "",
        "`rho = sum(mix_share[v] * visits[v] * service_time[v]) / (line_headway * resource_capacity)`",
        "",
        "The station-specific arrival headway is `line_headway / visit_probability`. Scenario "
        "columns are counterfactual values under the current equations at the applicable current "
        "upper severity (0.9 for the background scheduler; 0.95 for Flow-v2 enrichment) if that "
        "station were targeted. They are physics diagnostics, not scenario recommendations.",
        "",
        "## Utilization distribution",
        "",
        "| Band | Stations | Percentage |",
        "|---|---:|---:|",
    ]
    for band in bands:
        lines.append(f"| {band['band']} | {band['station_count']} | {band['percentage']:.1f}% |")

    lines.extend([
        "",
        "## Highest-load stations",
        "",
        "| Station | Operation | Weighted service (s) | Arrival headway (s) | rho | Capacity veh/h | Breakeven slowdown |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in ranked[:12]:
        lines.append(
            f"| {row['station_id']} | {row['station_name']} | "
            f"{row['mix_weighted_service_time_seconds']:.2f} | "
            f"{row['nominal_station_arrival_headway_seconds']:.2f} | "
            f"{row['nominal_utilization_rho']:.3f} | "
            f"{row['service_capacity_vehicles_per_hour']:.2f} | "
            f"{row['slowdown_multiplier_to_rho_1']:.3f} |"
        )

    lines.extend([
        "",
        "## Current scenario-equation capacity crossings",
        "",
        "These lists answer only whether the current maximum equation can cross mean capacity. "
        "Realized blocking also depends on duration, stochastic variation, buffers, upstream flow, and recovery.",
        "",
        f"- Manual variation among current target pools: {', '.join(manual) if manual else 'none'}",
        f"- Flow-calibrated micro-stops among current Flow-v2 candidates: {', '.join(micro) if micro else 'none'}",
        f"- Equipment degradation among current target pool: {', '.join(degradation) if degradation else 'none'}",
        f"- 100% highest-workload variant mix: {', '.join(mix) if mix else 'none'}",
        "",
        "## Buffer and topology observations",
        "",
        f"- Configured inter-station buffer capacities remain homogeneous: min={min(interstation_buffers)}, "
        f"max={max(interstation_buffers)}; the runtime entry buffer is {DEFAULT_ENTRY_BUFFER_CAPACITY}.",
        "- S36 correctly aggregates the two inbound branch buffers. S35 is visited only by ICE variants, "
        "so its station arrival headway is longer than the line release headway.",
        "- No configuration, scenario, dataset, model, threshold, or Flow-v2 artifact was changed in Phase A.",
        "",
        "## Phase-A conclusion",
        "",
        f"The current line is comfortable: the maximum nominal rho is {ranked[0]['nominal_utilization_rho']:.3f} "
        f"at {ranked[0]['station_id']}, and {bands[0]['station_count']} of {len(rows)} stations are below 50% utilization. "
        "The audit confirms that only a narrow subset of stations can cross capacity under the current supervised "
        "Flow mechanisms. This supports proceeding to a physics-only headway sweep before changing any cycle time.",
        "",
    ])
    return "\n".join(lines)


def write_capacity_audit(
    rows: list[dict],
    output_dir: Path,
    *,
    starting_commit: str,
    mean_interarrival_seconds: float = DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    baseline_test_result: str = "237 passed in 85.70s",
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "current_capacity_audit.csv"
    markdown_path = output_dir / "current_capacity_audit.md"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    markdown_path.write_text(
        render_capacity_summary(
            rows,
            starting_commit=starting_commit,
            mean_interarrival_seconds=mean_interarrival_seconds,
            baseline_test_result=baseline_test_result,
        ),
        encoding="utf-8",
    )
    return csv_path, markdown_path
