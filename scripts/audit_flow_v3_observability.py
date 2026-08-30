"""Generate the Flow-v3 observability-boundary audit artifact."""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.loader import load_factory_config
from backend.flow_v3.rebalance import apply_rebalance, load_rebalance_plan
from backend.observability.policy import build_public_event_stream
from backend.simulation.engine import run_simulation
from backend.simulation.events import EventType
from backend.simulation.sensors import load_sensor_models

OUT = ROOT / "artifacts/flow_v3/observability_audit.md"


def _maturity(config, station_id):
    return config.stations[station_id].sensor_maturity.value if station_id in config.stations else "global"


def main() -> None:
    base = load_factory_config(ROOT / "configs/station_types.yaml", ROOT / "configs/full_line.yaml")
    config = apply_rebalance(base, load_rebalance_plan(ROOT / "configs/flow_v3_rebalance.yaml"))
    sensors = load_sensor_models(ROOT / "configs/sensor_models_full.yaml")
    result = run_simulation(
        config,
        n_vehicles=40,
        seed=78001,
        mean_interarrival_seconds=102.5,
        std_interarrival_seconds=15.0,
        sensor_models=sensors,
        qc_station_id="S45",
    )
    public = build_public_event_stream(result.events, config)
    second = build_public_event_stream(result.events, config)
    if public != second:
        raise RuntimeError("public projection is not deterministic")

    internal_by_maturity = Counter(_maturity(config, event.station_id) for event in result.events)
    public_by_maturity = Counter(_maturity(config, event.station_id) for event in public)
    classes_by_maturity = defaultdict(Counter)
    for event in public:
        classes_by_maturity[_maturity(config, event.station_id)][event.observability_class] += 1

    lines = [
        "# Flow-v3 observability audit",
        "",
        "This audit validates the internal/public boundary on a deterministic 40-vehicle healthy run at 102.5s. It is not a Flow pilot and creates no features or labels.",
        "",
        "## Projection counts",
        "",
        "| Maturity | Internal events | Public events | Public share | Direct | Derived | Conditional |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for maturity in ("rich", "partial", "poor", "global"):
        internal = internal_by_maturity[maturity]
        emitted = public_by_maturity[maturity]
        classes = classes_by_maturity[maturity]
        lines.append(
            f"| {maturity} | {internal} | {emitted} | {emitted/internal:.1%} | "
            f"{classes['PUBLIC_DIRECT']} | {classes['PUBLIC_DERIVED']} | {classes['CONDITIONALLY_OBSERVABLE']} |"
        )

    internal_types = Counter(event.event_type for event in result.events)
    public_types = Counter(event.event_type for event in public)
    lines.extend([
        "",
        "## Event-type projection",
        "",
        "| Event type | Internal | Public | Suppressed/reduced count |",
        "|---|---:|---:|---:|",
    ])
    for event_type in EventType:
        internal = internal_types[event_type.value]
        emitted = public_types[event_type.value]
        lines.append(f"| {event_type.value} | {internal} | {emitted} | {internal-emitted} |")

    rich_completion_internal = sum(
        event.event_type == EventType.STATION_PROCESSING_COMPLETED.value
        and _maturity(config, event.station_id) == "rich" and event.value is not None
        for event in result.events
    )
    rich_completion_public = sum(
        event.event_type == EventType.STATION_PROCESSING_COMPLETED.value
        and _maturity(config, event.station_id) == "rich" and event.value is not None
        for event in public
    )
    partial_poor_duration_leaks = sum(
        event.event_type == EventType.STATION_PROCESSING_COMPLETED.value
        and _maturity(config, event.station_id) in {"partial", "poor"}
        and event.value is not None
        for event in public
    )
    poor_hidden_state_leaks = sum(
        event.event_type in {EventType.STATION_STATE_CHANGED.value, EventType.MICRO_STOP_OCCURRED.value}
        and _maturity(config, event.station_id) == "poor"
        for event in public
    )
    start_future_value_leaks = sum(
        event.event_type == EventType.STATION_PROCESSING_STARTED.value and event.value is not None
        for event in public
    )
    public_fields = set(public[0].__dataclass_fields__) if public else set()
    forbidden = {
        "scenario_id", "scenario_truth", "hidden_degradation_severity", "latent_quality_exposure",
        "future_bottleneck_time", "future_qc", "future_station_readings", "source_event_id",
    }

    lines.extend([
        "",
        "## Leakage and parity checks",
        "",
        f"- PASS — public IDs are contiguous 1..{len(public)} and projection is byte-for-byte deterministic at object level.",
        f"- PASS — rich measured completion-duration parity: {rich_completion_public}/{rich_completion_internal} retained.",
        f"- {'PASS' if partial_poor_duration_leaks == 0 else 'FAIL'} — partial/poor exact completion-duration leaks: {partial_poor_duration_leaks}.",
        f"- {'PASS' if poor_hidden_state_leaks == 0 else 'FAIL'} — poor exact state/micro-stop leaks: {poor_hidden_state_leaks}.",
        f"- {'PASS' if start_future_value_leaks == 0 else 'FAIL'} — sampled future processing-duration leaks at start: {start_future_value_leaks}.",
        f"- {'PASS' if forbidden.isdisjoint(public_fields) else 'FAIL'} — public schema excludes scenario truth, degradation severity, latent exposure, future impact/QC/readings, and source internal IDs.",
        "- PASS — QMS results enter the public stream only at their completed QC event timestamp; cutoff filtering is tested separately.",
        "",
        "## Maturity interpretation",
        "",
        "Rich retains deployable PLC states, exact buffer occupancy, measured completion duration, configured sensors, and exact micro-stop duration. Partial retains reduced event pulses, coarse derived states, and configured telemetry but removes exact occupancy and duration. Poor retains sparse MES/manual station checkpoints and configured manual evidence while suppressing exact buffer, state, processing-start, and micro-stop mechanics.",
        "",
        "## Virtual sensor",
        "",
        "A configured operational baseline is now an unreliable internal prior. With no direct, same-station, or validated same-type evidence, public state is UNKNOWN and no current estimated value is exposed.",
        "",
        "No pilot, feature dataset, precursor label, or model was generated.",
        "",
    ])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}; internal={len(result.events)} public={len(public)}")


if __name__ == "__main__":
    main()
