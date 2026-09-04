"""Supervisor "Action Center" logic: what needs attention right now.

Current-state only. Every function here reads the *latest* prediction per station
/ unit for one run and answers an operational question -- it does not look across
production days (that is the Plant Manager's job).

The priority queue deliberately interleaves bottleneck and defect interventions
into one ranked list while keeping their semantics distinct: each row carries its
own ``kind`` and its own risk %, and ranking compares an item only against its own
risk -- the two probabilities are never averaged or combined into one score.
"""

from __future__ import annotations

from dataclasses import dataclass

from dashboard.stakeholder.streams import (
    LOW_CONFIDENCE,
    RunStreams,
    bottleneck_drivers,
    defect_drivers,
)

KIND_BOTTLENECK = "BOTTLENECK"
KIND_DEFECT = "DEFECT"

_BOTTLENECK_ACTION = (
    "Inspect {station}: check queue depth, buffer headroom and the upstream feed; "
    "clear the constraint before it propagates downstream."
)
_DEFECT_ACTION = (
    "Hold unit {unit} at {station} for quality inspection before it advances toward "
    "final inspection."
)
_DEFECT_ACTION_AT_FINAL = (
    "Unit {unit} is at final inspection ({station}) with elevated modeled defect "
    "risk -- confirm the inspection disposition before release."
)


def _confidence_pct(confidence: float | None) -> int:
    return 0 if confidence is None else round(float(confidence) * 100)


def _is_low_confidence(confidence: float | None) -> bool:
    return confidence is not None and float(confidence) < LOW_CONFIDENCE


def _is_dark_route(route: str | None) -> bool:
    return bool(route) and str(route).upper().startswith("DARK")


@dataclass(frozen=True)
class PriorityAction:
    """One ranked intervention in the combined queue."""

    kind: str  # KIND_BOTTLENECK | KIND_DEFECT
    reference: str  # station id (bottleneck) or unit id (defect)
    station: str  # station context for the row
    risk_percent: float
    confidence_percent: int
    drivers: tuple[str, ...]
    recommended_action: str
    low_confidence: bool
    dark_context: bool

    @property
    def risk_label(self) -> str:
        return "Bottleneck risk" if self.kind == KIND_BOTTLENECK else "Defect risk"


def build_priority_queue(streams: RunStreams, *, limit: int = 12) -> list[PriorityAction]:
    """Actionable bottleneck + defect alerts for the current run, most severe first.

    A row is included only when the stream's own ``warning`` flag is set -- the
    authoritative actionable state for each stream. Defect status is never derived
    from ``threshold_crossed``.
    """
    actions: list[PriorityAction] = []

    for station_id, point in streams.bottleneck.latest_by_station().items():
        if not point.warning:
            continue
        record = streams.latest_bottleneck_records.get(station_id, {})
        actions.append(
            PriorityAction(
                kind=KIND_BOTTLENECK,
                reference=station_id,
                station=station_id,
                risk_percent=round(point.risk_percent, 1),
                confidence_percent=_confidence_pct(point.state_confidence),
                drivers=tuple(bottleneck_drivers(record)),
                recommended_action=_BOTTLENECK_ACTION.format(station=station_id),
                low_confidence=_is_low_confidence(point.state_confidence),
                dark_context=(point.zone == "DARK") or _is_dark_route(record.get("route")),
            )
        )

    for unit_id, point in streams.defect.latest_by_unit().items():
        if not point.warning:
            continue
        record = streams.latest_defect_records.get(unit_id, {})
        station = point.station_id or str(record.get("station_id") or "—")
        final_station = record.get("final_inspection_station")
        at_final = bool(final_station) and str(final_station) == str(station)
        template = _DEFECT_ACTION_AT_FINAL if at_final else _DEFECT_ACTION
        actions.append(
            PriorityAction(
                kind=KIND_DEFECT,
                reference=unit_id,
                station=station,
                risk_percent=round(point.risk_percent, 1),
                confidence_percent=_confidence_pct(point.state_confidence),
                drivers=tuple(defect_drivers(record)),
                recommended_action=template.format(unit=unit_id, station=station),
                low_confidence=_is_low_confidence(point.state_confidence),
                dark_context=_is_dark_route(record.get("route")) or _is_dark_route(point.route),
            )
        )

    # One queue, but each item is ranked on its own risk %. Confident alerts come
    # ahead of low-confidence ones at equal risk.
    actions.sort(
        key=lambda action: (action.risk_percent, action.confidence_percent),
        reverse=True,
    )
    return actions[:limit]


@dataclass(frozen=True)
class StationWatchRow:
    """Highest-risk current stations, whether or not they are alerting."""

    station: str
    risk_percent: float
    warning: bool
    confidence_percent: int
    trend: str
    predictions: int


def station_watch(streams: RunStreams, *, limit: int = 6) -> list[StationWatchRow]:
    rows: list[StationWatchRow] = []
    for station_id, point in streams.bottleneck.latest_by_station().items():
        analytics = streams.bottleneck.analytics(station_id)
        rows.append(
            StationWatchRow(
                station=station_id,
                risk_percent=round(point.risk_percent, 1),
                warning=point.warning,
                confidence_percent=_confidence_pct(point.state_confidence),
                trend=analytics.trend,
                predictions=analytics.point_count,
            )
        )
    rows.sort(key=lambda row: (row.warning, row.risk_percent), reverse=True)
    return rows[:limit]


@dataclass(frozen=True)
class QualityWatchRow:
    """Highest-risk current units, with where they are and how urgently to inspect."""

    unit: str
    risk_percent: float
    station: str
    inspection_priority: str  # "High" | "Monitor"
    confidence_percent: int
    warning: bool


def quality_watch(streams: RunStreams, *, limit: int = 6) -> list[QualityWatchRow]:
    rows: list[QualityWatchRow] = []
    for unit_id, point in streams.defect.latest_by_unit().items():
        rows.append(
            QualityWatchRow(
                unit=unit_id,
                risk_percent=round(point.risk_percent, 1),
                station=point.station_id or "—",
                inspection_priority="High" if point.warning else "Monitor",
                confidence_percent=_confidence_pct(point.state_confidence),
                warning=point.warning,
            )
        )
    rows.sort(key=lambda row: (row.warning, row.risk_percent), reverse=True)
    return rows[:limit]


@dataclass(frozen=True)
class ShiftHealth:
    """Runtime trust for the current run: is the picture safe to act on as-is?"""

    health_status: str
    degraded: bool
    bottleneck_subsystem: str
    defect_subsystem: str
    active_bottleneck_alerts: int
    active_defect_alerts: int
    low_confidence_bottleneck: int
    low_confidence_defect: int
    dark_inferred_alerts: int
    bottleneck_stream_available: bool
    defect_stream_available: bool
    intervention_required: bool
    notes: tuple[str, ...]


def shift_health(streams: RunStreams) -> ShiftHealth:
    bottleneck_latest = streams.bottleneck.latest_by_station()
    defect_latest = streams.defect.latest_by_unit()

    active_bottleneck = [s for s, p in bottleneck_latest.items() if p.warning]
    active_defect = [u for u, p in defect_latest.items() if p.warning]

    low_bottleneck = sum(1 for p in bottleneck_latest.values() if _is_low_confidence(p.state_confidence))
    low_defect = sum(1 for p in defect_latest.values() if _is_low_confidence(p.state_confidence))

    dark_alerts = sum(
        1
        for s in active_bottleneck
        if bottleneck_latest[s].zone == "DARK"
        or _is_dark_route(streams.latest_bottleneck_records.get(s, {}).get("route"))
    ) + sum(
        1
        for u in active_defect
        if _is_dark_route(defect_latest[u].route)
        or _is_dark_route(streams.latest_defect_records.get(u, {}).get("route"))
    )

    degraded = streams.degraded
    intervention_required = bool(active_bottleneck or active_defect or degraded)

    notes: list[str] = []
    if degraded:
        notes.append(
            f"Coordinated runtime health is {streams.health.label}, not PASS — treat the "
            "affected stream as stale and verify on the floor before acting."
        )
    if not streams.bottleneck_exists:
        notes.append("No bottleneck prediction stream for this run; station risk is unavailable.")
    if not streams.defect_exists:
        notes.append("No defect prediction stream for this run; unit quality risk is unavailable.")
    if low_bottleneck or low_defect:
        notes.append(
            f"{low_bottleneck + low_defect} current prediction(s) below "
            f"{int(LOW_CONFIDENCE * 100)}% state confidence (reconstructed / DARK state) — "
            "weight these lower."
        )
    if dark_alerts:
        notes.append(f"{dark_alerts} active alert(s) rely on DARK-zone / inferred state.")
    if not intervention_required and not notes:
        notes.append("No active alerts and runtime health is PASS — no intervention required.")

    return ShiftHealth(
        health_status=streams.health.label,
        degraded=degraded,
        bottleneck_subsystem=streams.subsystem_status("bottleneck"),
        defect_subsystem=streams.subsystem_status("defect"),
        active_bottleneck_alerts=len(active_bottleneck),
        active_defect_alerts=len(active_defect),
        low_confidence_bottleneck=low_bottleneck,
        low_confidence_defect=low_defect,
        dark_inferred_alerts=dark_alerts,
        bottleneck_stream_available=streams.bottleneck_exists,
        defect_stream_available=streams.defect_exists,
        intervention_required=intervention_required,
        notes=tuple(notes),
    )
