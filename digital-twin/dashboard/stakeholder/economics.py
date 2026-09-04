"""Leadership "Executive Economics" logic.

The repository holds **no measured plant financial data**. Every number this module
produces is ``observed run event count x user-supplied assumption``. Nothing here
reads a price, a cost or a revenue figure from the simulator or the run artifacts,
because none exists. Callers must label the outputs Estimated / Modeled /
Illustrative and must not present them as measured results.

Observed counts, and how they are defined:

* ``units_produced``   -- simulator ``units_created`` when present, else the number
  of distinct units seen in the defect stream.
* ``maintenance_alarms`` -- the number of *entries into* a bottleneck warning state
  (``StationAnalytics.threshold_crossings``), summed over stations. A discrete
  intervention event, not one per emitted flagged record.
* ``defective_units`` -- distinct units with at least one defect ``warning`` (the
  authoritative actionable flag; never ``threshold_crossed``).

All functions are pure and deterministic: same ``ObservedEconomics`` +
``EconomicsAssumptions`` in, same numbers out, with no Streamlit or clock involved.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from dashboard.stakeholder.streams import RunStreams

_MODELED_BASIS = (
    "Modeled: user-supplied assumptions x observed run events. Not measured plant "
    "financials."
)


@dataclass(frozen=True)
class EconomicsAssumptions:
    """User-configurable economic assumptions. Every default is illustrative."""

    revenue_per_unit: float = 1200.0
    #: Optional flat revenue credited per unit per value-adding station/operation.
    revenue_per_station_operation: float | None = None
    maintenance_cost_per_alarm: float = 400.0
    cost_per_defective_unit: float = 750.0
    #: Optional downtime / lost-production cost attributed to each maintenance alarm.
    downtime_cost_per_alarm: float = 0.0
    #: Optional scrap / rework cost added on top of ``cost_per_defective_unit``.
    scrap_rework_cost_per_unit: float = 0.0
    currency: str = "$"

    @property
    def defect_unit_cost(self) -> float:
        return self.cost_per_defective_unit + self.scrap_rework_cost_per_unit

    @property
    def alarm_cost(self) -> float:
        return self.maintenance_cost_per_alarm + self.downtime_cost_per_alarm


@dataclass(frozen=True)
class DayEconomics:
    """Observed counts for one production day (used by the P/L trend)."""

    production_day: int
    run_id: str
    units: int
    maintenance_alarms: int
    defective_units: int


@dataclass(frozen=True)
class ObservedEconomics:
    """Event counts pulled from a scope of runs -- no money yet."""

    units_produced: int = 0
    maintenance_alarms: int = 0
    bottleneck_alert_records: int = 0
    defective_units: int = 0
    defect_alert_records: int = 0
    days: int = 0
    per_station_alarms: dict[str, int] = field(default_factory=dict)
    per_station_units: dict[str, int] = field(default_factory=dict)
    per_station_defect_units: dict[str, int] = field(default_factory=dict)
    per_station_defect_events: dict[str, int] = field(default_factory=dict)
    per_day: tuple[DayEconomics, ...] = ()


def observe_economics(scope: list[RunStreams]) -> ObservedEconomics:
    """Reduce a scope of runs to the event counts the economic model consumes."""
    units_produced = 0
    maintenance_alarms = 0
    bottleneck_alert_records = 0
    defective_units = 0
    defect_alert_records = 0
    per_station_alarms: dict[str, int] = defaultdict(int)
    per_station_units: dict[str, int] = defaultdict(int)
    per_station_defect_units: dict[str, set[str]] = defaultdict(set)
    per_station_defect_events: dict[str, int] = defaultdict(int)
    per_day: list[DayEconomics] = []

    for run_streams in sorted(scope, key=lambda rs: rs.production_day):
        day_units = run_streams.units_produced()
        units_produced += day_units

        day_alarms = 0
        for station_id in run_streams.bottleneck.station_ids():
            analytics = run_streams.bottleneck.analytics(station_id)
            day_alarms += analytics.threshold_crossings
            per_station_alarms[station_id] += analytics.threshold_crossings
            bottleneck_alert_records += analytics.warning_count
        maintenance_alarms += day_alarms

        day_defective: set[str] = set()
        for unit_id, series in run_streams.defect.units.items():
            unit_stations = {p.station_id for p in series.points if p.station_id}
            for station in unit_stations:
                per_station_units[station] += 1
            unit_flagged = False
            for point in series.points:
                if not point.warning:
                    continue
                unit_flagged = True
                defect_alert_records += 1
                station = point.station_id or "—"
                per_station_defect_events[station] += 1
                per_station_defect_units[station].add(unit_id)
            if unit_flagged:
                day_defective.add(unit_id)
        defective_units += len(day_defective)

        per_day.append(
            DayEconomics(
                production_day=run_streams.production_day,
                run_id=run_streams.run_id,
                units=day_units,
                maintenance_alarms=day_alarms,
                defective_units=len(day_defective),
            )
        )

    return ObservedEconomics(
        units_produced=units_produced,
        maintenance_alarms=maintenance_alarms,
        bottleneck_alert_records=bottleneck_alert_records,
        defective_units=defective_units,
        defect_alert_records=defect_alert_records,
        days=len(scope),
        per_station_alarms=dict(per_station_alarms),
        per_station_units=dict(per_station_units),
        per_station_defect_units={s: len(u) for s, u in per_station_defect_units.items()},
        per_station_defect_events=dict(per_station_defect_events),
        per_day=tuple(per_day),
    )


@dataclass(frozen=True)
class FinancialOverview:
    """Modeled headline economics for a scope. Every field is an estimate."""

    estimated_revenue: float
    estimated_maintenance_cost: float
    estimated_defect_loss: float
    estimated_downtime_cost: float
    estimated_profit: float
    estimated_avoidable_loss: float
    basis: str = _MODELED_BASIS


def financial_overview(
    observed: ObservedEconomics, assumptions: EconomicsAssumptions
) -> FinancialOverview:
    revenue = observed.units_produced * assumptions.revenue_per_unit
    if assumptions.revenue_per_station_operation:
        revenue += sum(observed.per_station_units.values()) * assumptions.revenue_per_station_operation

    maintenance = observed.maintenance_alarms * assumptions.maintenance_cost_per_alarm
    downtime = observed.maintenance_alarms * assumptions.downtime_cost_per_alarm
    defect_loss = observed.defective_units * assumptions.defect_unit_cost
    avoidable = maintenance + downtime + defect_loss

    return FinancialOverview(
        estimated_revenue=round(revenue, 2),
        estimated_maintenance_cost=round(maintenance, 2),
        estimated_defect_loss=round(defect_loss, 2),
        estimated_downtime_cost=round(downtime, 2),
        estimated_profit=round(revenue - avoidable, 2),
        estimated_avoidable_loss=round(avoidable, 2),
    )


@dataclass(frozen=True)
class StationEconomics:
    """One row of the ranked station economics table (worst cost first)."""

    station: str
    revenue_contribution: float
    maintenance_alarm_count: int
    estimated_maintenance_cost: float
    net_modeled_contribution: float


def station_economics(
    observed: ObservedEconomics, assumptions: EconomicsAssumptions
) -> list[StationEconomics]:
    stations = sorted(set(observed.per_station_alarms) | set(observed.per_station_units))
    total_station_units = sum(observed.per_station_units.values())
    revenue_pool = observed.units_produced * assumptions.revenue_per_unit

    rows: list[StationEconomics] = []
    for station in stations:
        units_here = observed.per_station_units.get(station, 0)
        if assumptions.revenue_per_station_operation:
            revenue = units_here * assumptions.revenue_per_station_operation
        elif total_station_units:
            # Even attribution of the modeled revenue pool by observed throughput.
            revenue = revenue_pool * units_here / total_station_units
        else:
            revenue = 0.0
        alarms = observed.per_station_alarms.get(station, 0)
        maintenance_cost = alarms * assumptions.alarm_cost
        rows.append(
            StationEconomics(
                station=station,
                revenue_contribution=round(revenue, 2),
                maintenance_alarm_count=alarms,
                estimated_maintenance_cost=round(maintenance_cost, 2),
                net_modeled_contribution=round(revenue - maintenance_cost, 2),
            )
        )
    rows.sort(
        key=lambda row: (row.estimated_maintenance_cost, -row.net_modeled_contribution),
        reverse=True,
    )
    return rows


@dataclass(frozen=True)
class QualityLossRow:
    """One row of the quality-loss table (largest modeled loss first)."""

    station: str
    defect_events: int
    units_affected: int
    estimated_defect_loss: float


def quality_loss(
    observed: ObservedEconomics, assumptions: EconomicsAssumptions
) -> list[QualityLossRow]:
    rows = [
        QualityLossRow(
            station=station,
            defect_events=observed.per_station_defect_events.get(station, 0),
            units_affected=units_affected,
            estimated_defect_loss=round(units_affected * assumptions.defect_unit_cost, 2),
        )
        for station, units_affected in observed.per_station_defect_units.items()
    ]
    rows.sort(key=lambda row: row.estimated_defect_loss, reverse=True)
    return rows


def profit_loss_trend(
    observed: ObservedEconomics, assumptions: EconomicsAssumptions
) -> list[dict]:
    """Modeled revenue / cost / profit per production day."""
    trend: list[dict] = []
    for day in observed.per_day:
        revenue = day.units * assumptions.revenue_per_unit
        cost = day.maintenance_alarms * assumptions.alarm_cost + day.defective_units * assumptions.defect_unit_cost
        trend.append(
            {
                "production_day": day.production_day,
                "run_id": day.run_id,
                "modeled_revenue": round(revenue, 2),
                "modeled_cost": round(cost, 2),
                "estimated_profit": round(revenue - cost, 2),
            }
        )
    return trend


def what_matters_most(
    observed: ObservedEconomics, assumptions: EconomicsAssumptions, *, limit: int = 4
) -> list[str]:
    """A short executive read of where modeled cost concentrates, from run data."""
    currency = assumptions.currency
    messages: list[str] = []

    stations = station_economics(observed, assumptions)
    if stations and stations[0].estimated_maintenance_cost > 0:
        top = stations[0]
        messages.append(
            f"Maintenance cost concentrates at {top.station}: "
            f"{top.maintenance_alarm_count} modeled alarm(s), "
            f"~{currency}{top.estimated_maintenance_cost:,.0f}."
        )

    losses = quality_loss(observed, assumptions)
    if losses and losses[0].estimated_defect_loss > 0:
        top = losses[0]
        messages.append(
            f"Quality loss concentrates at {top.station}: {top.units_affected} unit(s) "
            f"flagged over {top.defect_events} event(s), ~{currency}{top.estimated_defect_loss:,.0f}."
        )

    overview = financial_overview(observed, assumptions)
    if overview.estimated_avoidable_loss > 0:
        if overview.estimated_revenue > 0:
            share = 100.0 * overview.estimated_avoidable_loss / overview.estimated_revenue
            context = f" ({share:.1f}% of modeled revenue)"
        else:
            context = "; set a revenue-per-unit assumption to see it in context"
        messages.append(
            f"Modeled avoidable loss is ~{currency}{overview.estimated_avoidable_loss:,.0f}"
            f"{context} across {observed.days} production day(s)."
        )

    if not messages:
        messages.append(
            "No maintenance or defect alerts in the selected scope — the model shows no "
            "avoidable-loss concentration."
        )
    return messages[:limit]


def scenario_savings(
    observed: ObservedEconomics,
    assumptions: EconomicsAssumptions,
    *,
    reductions: tuple[float, ...] = (0.10, 0.20, 0.30),
) -> list[dict]:
    """Modeled savings if avoidable alarms / defect losses fell by each fraction.

    Scenario analysis on user assumptions -- not a measured or realised ROI.
    """
    overview = financial_overview(observed, assumptions)
    scenarios: list[dict] = []
    for reduction in reductions:
        saving = overview.estimated_avoidable_loss * reduction
        scenarios.append(
            {
                "reduction": reduction,
                "label": f"{int(round(reduction * 100))}% fewer avoidable alarms / defect losses",
                "modeled_saving": round(saving, 2),
                "modeled_profit_after": round(overview.estimated_profit + saving, 2),
            }
        )
    return scenarios
