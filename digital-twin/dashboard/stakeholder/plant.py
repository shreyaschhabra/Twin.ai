"""Plant Manager "Plant Performance" logic: trends, recurrence, concentration.

Everything here aggregates across a *scope* of runs (Current Run, one Production
Day, or All Runs). The unit of recurrence is the production day: a station "was
affected" on a day when it produced at least one bottleneck ``warning`` that day.

Bottleneck activity and defect activity are reported as separate series -- they are
never added together into one "plant risk" number.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from dashboard.stakeholder.streams import RunStreams, bottleneck_drivers

# Peak-risk cut points for a station's recurring-constraint risk label. Percentages.
_HIGH_RISK_PCT = 70.0
_ELEVATED_RISK_PCT = 40.0


def _mean_pct(total: float, count: int) -> int:
    return round(100.0 * total / count) if count else 0


@dataclass(frozen=True)
class ScopeKpis:
    """The Plant Manager KPI strip."""

    production_days: int
    bottleneck_alerts: int  # station-days with >=1 bottleneck warning
    defect_alerts: int  # unit-days with >=1 defect warning
    affected_stations: int  # distinct stations flagged anywhere in scope
    avg_confidence_percent: int  # across every prediction in scope, both streams


def scope_kpis(scope: list[RunStreams]) -> ScopeKpis:
    bottleneck_alerts = 0
    defect_alerts = 0
    affected_stations: set[str] = set()
    confidence_total = 0.0
    confidence_count = 0

    for run_streams in scope:
        for station_id in run_streams.bottleneck.station_ids():
            analytics = run_streams.bottleneck.analytics(station_id)
            if analytics.warning_count > 0:
                bottleneck_alerts += 1
                affected_stations.add(station_id)
        for unit_id in run_streams.defect.unit_ids():
            if run_streams.defect.analytics(unit_id).warning_count > 0:
                defect_alerts += 1
        for series in run_streams.bottleneck.stations.values():
            for point in series.points:
                if point.state_confidence is not None:
                    confidence_total += point.state_confidence
                    confidence_count += 1
        for series in run_streams.defect.units.values():
            for point in series.points:
                if point.state_confidence is not None:
                    confidence_total += point.state_confidence
                    confidence_count += 1

    return ScopeKpis(
        production_days=len(scope),
        bottleneck_alerts=bottleneck_alerts,
        defect_alerts=defect_alerts,
        affected_stations=len(affected_stations),
        avg_confidence_percent=_mean_pct(confidence_total, confidence_count),
    )


@dataclass(frozen=True)
class TrendPoint:
    """One production day on the Performance Trend chart."""

    production_day: int
    run_id: str
    bottleneck_alert_stations: int
    bottleneck_records: int
    defect_alert_units: int
    defect_records: int
    affected_stations: int
    avg_confidence_percent: int
    degraded: bool


def performance_trend(scope: list[RunStreams]) -> list[TrendPoint]:
    points: list[TrendPoint] = []
    for run_streams in sorted(scope, key=lambda rs: rs.production_day):
        alert_stations = {
            s for s in run_streams.bottleneck.station_ids()
            if run_streams.bottleneck.analytics(s).warning_count > 0
        }
        alert_units = {
            u for u in run_streams.defect.unit_ids()
            if run_streams.defect.analytics(u).warning_count > 0
        }
        confidence_total = 0.0
        confidence_count = 0
        for series in list(run_streams.bottleneck.stations.values()) + list(
            run_streams.defect.units.values()
        ):
            for point in series.points:
                if point.state_confidence is not None:
                    confidence_total += point.state_confidence
                    confidence_count += 1
        points.append(
            TrendPoint(
                production_day=run_streams.production_day,
                run_id=run_streams.run_id,
                bottleneck_alert_stations=len(alert_stations),
                bottleneck_records=run_streams.bottleneck.record_count,
                defect_alert_units=len(alert_units),
                defect_records=run_streams.defect.record_count,
                affected_stations=len(alert_stations),
                avg_confidence_percent=_mean_pct(confidence_total, confidence_count),
                degraded=run_streams.degraded,
            )
        )
    return points


@dataclass(frozen=True)
class RecurringConstraint:
    """A station ranked by how persistently it constrains flow across the scope."""

    station: str
    days_affected: int
    days_in_scope: int
    alert_count: int  # total bottleneck warning records across the scope
    peak_risk_percent: float
    avg_confidence_percent: int
    drivers: tuple[str, ...]
    risk_level: str  # "High" | "Elevated" | "Watch"


def recurring_constraints(scope: list[RunStreams]) -> list[RecurringConstraint]:
    days_affected: dict[str, int] = defaultdict(int)
    alert_count: dict[str, int] = defaultdict(int)
    peak_risk: dict[str, float] = defaultdict(float)
    confidence_total: dict[str, float] = defaultdict(float)
    confidence_count: dict[str, int] = defaultdict(int)
    driver_freq: dict[str, Counter] = defaultdict(Counter)

    for run_streams in scope:
        for station_id, series in run_streams.bottleneck.stations.items():
            for point in series.points:
                if point.state_confidence is not None:
                    confidence_total[station_id] += point.state_confidence
                    confidence_count[station_id] += 1
            analytics = run_streams.bottleneck.analytics(station_id)
            if analytics.warning_count <= 0:
                continue
            days_affected[station_id] += 1
            alert_count[station_id] += analytics.warning_count
            peak_risk[station_id] = max(
                peak_risk[station_id], (analytics.peak_risk or 0.0) * 100.0
            )
            record = run_streams.latest_bottleneck_records.get(station_id, {})
            for name in bottleneck_drivers(record, limit=3):
                driver_freq[station_id][name] += 1

    days_in_scope = len(scope)
    constraints: list[RecurringConstraint] = []
    for station_id, affected in days_affected.items():
        peak = round(peak_risk[station_id], 1)
        if (days_in_scope > 1 and affected >= days_in_scope) or peak >= _HIGH_RISK_PCT:
            level = "High"
        elif peak >= _ELEVATED_RISK_PCT or affected > 1:
            level = "Elevated"
        else:
            level = "Watch"
        constraints.append(
            RecurringConstraint(
                station=station_id,
                days_affected=affected,
                days_in_scope=days_in_scope,
                alert_count=alert_count[station_id],
                peak_risk_percent=peak,
                avg_confidence_percent=_mean_pct(
                    confidence_total[station_id], confidence_count[station_id]
                ),
                drivers=tuple(name for name, _ in driver_freq[station_id].most_common(3)),
                risk_level=level,
            )
        )
    constraints.sort(
        key=lambda c: (c.days_affected, c.alert_count, c.peak_risk_percent), reverse=True
    )
    return constraints


@dataclass(frozen=True)
class DefectConcentration:
    """A station where defect exposure recurs, ranked by persistence and spread."""

    station: str
    days_affected: int
    defect_events: int  # defect warning records at this station across the scope
    units_affected: int  # distinct units with a defect warning at this station
    peak_risk_percent: float
    avg_confidence_percent: int


def defect_concentration(scope: list[RunStreams]) -> list[DefectConcentration]:
    days_affected: dict[str, int] = defaultdict(int)
    events: dict[str, int] = defaultdict(int)
    units: dict[str, set[str]] = defaultdict(set)
    peak_risk: dict[str, float] = defaultdict(float)
    confidence_total: dict[str, float] = defaultdict(float)
    confidence_count: dict[str, int] = defaultdict(int)

    for run_streams in scope:
        stations_today: set[str] = set()
        for unit_id, series in run_streams.defect.units.items():
            for point in series.points:
                station = point.station_id or "—"
                if point.state_confidence is not None:
                    confidence_total[station] += point.state_confidence
                    confidence_count[station] += 1
                if point.warning:
                    events[station] += 1
                    units[station].add(unit_id)
                    peak_risk[station] = max(peak_risk[station], point.risk_percent)
                    stations_today.add(station)
        for station in stations_today:
            days_affected[station] += 1

    concentration: list[DefectConcentration] = []
    for station, event_count in events.items():
        concentration.append(
            DefectConcentration(
                station=station,
                days_affected=days_affected[station],
                defect_events=event_count,
                units_affected=len(units[station]),
                peak_risk_percent=round(peak_risk[station], 1),
                avg_confidence_percent=_mean_pct(
                    confidence_total[station], confidence_count[station]
                ),
            )
        )
    concentration.sort(
        key=lambda c: (c.days_affected, c.units_affected, c.defect_events), reverse=True
    )
    return concentration


@dataclass(frozen=True)
class Observability:
    """Sensor coverage, confidence and degraded-state exposure for the scope."""

    coverage_breakdown: dict[str, int] = field(default_factory=dict)  # coverage -> stations
    dark_zone_stations: int = 0
    total_stations: int = 0
    bottleneck_confidence_percent: int = 0
    defect_confidence_percent: int = 0
    low_confidence_predictions: int = 0
    dark_inferred_predictions: int = 0
    degraded_runs: int = 0
    runs_in_scope: int = 0
    bottleneck_subsystem_issue_runs: int = 0
    defect_subsystem_issue_runs: int = 0

    @property
    def instrumented_fraction(self) -> float:
        if not self.total_stations:
            return 0.0
        instrumented = self.total_stations - self.coverage_breakdown.get("NONE", 0)
        return instrumented / self.total_stations


def observability(scope: list[RunStreams], factory_data: dict | None) -> Observability:
    from dashboard.domain.station import Station  # local: keep module import-light

    stations = Station.all_from_factory(factory_data or {})
    coverage_breakdown: dict[str, int] = defaultdict(int)
    for station in stations:
        coverage_breakdown[station.sensor_coverage] += 1
    dark_zone_stations = sum(1 for station in stations if station.is_dark)

    from dashboard.stakeholder.streams import LOW_CONFIDENCE

    b_total = 0.0
    b_count = 0
    d_total = 0.0
    d_count = 0
    low_confidence = 0
    dark_inferred = 0
    degraded_runs = 0
    bottleneck_issue_runs = 0
    defect_issue_runs = 0

    for run_streams in scope:
        if run_streams.degraded:
            degraded_runs += 1
        if run_streams.subsystem_status("bottleneck") not in {"PASS", "—", "UNKNOWN"}:
            bottleneck_issue_runs += 1
        if run_streams.subsystem_status("defect") not in {"PASS", "—", "UNKNOWN"}:
            defect_issue_runs += 1
        for series in run_streams.bottleneck.stations.values():
            for point in series.points:
                if point.state_confidence is not None:
                    b_total += point.state_confidence
                    b_count += 1
                    if point.state_confidence < LOW_CONFIDENCE:
                        low_confidence += 1
                if point.zone == "DARK":
                    dark_inferred += 1
        for series in run_streams.defect.units.values():
            for point in series.points:
                if point.state_confidence is not None:
                    d_total += point.state_confidence
                    d_count += 1
                    if point.state_confidence < LOW_CONFIDENCE:
                        low_confidence += 1
                if point.route and str(point.route).upper().startswith("DARK"):
                    dark_inferred += 1

    return Observability(
        coverage_breakdown=dict(sorted(coverage_breakdown.items())),
        dark_zone_stations=dark_zone_stations,
        total_stations=len(stations),
        bottleneck_confidence_percent=_mean_pct(b_total, b_count),
        defect_confidence_percent=_mean_pct(d_total, d_count),
        low_confidence_predictions=low_confidence,
        dark_inferred_predictions=dark_inferred,
        degraded_runs=degraded_runs,
        runs_in_scope=len(scope),
        bottleneck_subsystem_issue_runs=bottleneck_issue_runs,
        defect_subsystem_issue_runs=defect_issue_runs,
    )
