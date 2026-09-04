"""Deterministic aggregation and business logic for the stakeholder views.

The three stakeholder pages -- Supervisor (Action Center), Plant Manager (Plant
Performance) and Leadership (Executive Economics) -- are Streamlit-free below this
package. Everything here is pure functions over ``RunStreams`` snapshots so the
numbers can be tested without a browser.

Boundaries this package keeps:

* It reads the *existing* prediction streams through the *existing* abstractions
  (:class:`dashboard.live.bottleneck_state.LiveBottleneckState`,
  :class:`dashboard.live.defect_state.LiveDefectState`, the JSONL tailer, the
  runtime health reader). It never re-implements a stream parser, never touches
  SQL, and never imports the simulator / ML / CLI code.
* Bottleneck risk and defect risk stay separate. Nothing here averages or blends
  the two probabilities; a combined *queue* still ranks each item by its own risk.
* ``warning`` is authoritative for both streams and is used verbatim -- defect
  status never falls back to ``threshold_crossed``.
* ``state_confidence`` is surfaced, not hidden; low-confidence / DARK-inferred
  predictions are flagged rather than silently trusted.
* No prediction is fabricated. A missing stream yields empty results plus a note.

Financial figures produced by :mod:`dashboard.stakeholder.economics` are modeled
from user-supplied assumptions multiplied by observed run events. They are always
labelled Estimated / Modeled / Illustrative and never presented as measured plant
financials.
"""

from dashboard.stakeholder.economics import (
    EconomicsAssumptions,
    FinancialOverview,
    ObservedEconomics,
    QualityLossRow,
    StationEconomics,
    financial_overview,
    observe_economics,
    profit_loss_trend,
    quality_loss,
    scenario_savings,
    station_economics,
    what_matters_most,
)
from dashboard.stakeholder.plant import (
    DefectConcentration,
    Observability,
    RecurringConstraint,
    ScopeKpis,
    TrendPoint,
    defect_concentration,
    observability,
    performance_trend,
    recurring_constraints,
    scope_kpis,
)
from dashboard.stakeholder.streams import (
    RunStreams,
    load_run_streams,
    load_scope,
    resolve_scope,
    scope_options,
)
from dashboard.stakeholder.supervisor import (
    PriorityAction,
    QualityWatchRow,
    ShiftHealth,
    StationWatchRow,
    build_priority_queue,
    quality_watch,
    shift_health,
    station_watch,
)

__all__ = [
    "DefectConcentration",
    "EconomicsAssumptions",
    "FinancialOverview",
    "Observability",
    "ObservedEconomics",
    "PriorityAction",
    "QualityLossRow",
    "QualityWatchRow",
    "RecurringConstraint",
    "RunStreams",
    "ScopeKpis",
    "ShiftHealth",
    "StationEconomics",
    "StationWatchRow",
    "TrendPoint",
    "build_priority_queue",
    "defect_concentration",
    "financial_overview",
    "load_run_streams",
    "load_scope",
    "observability",
    "observe_economics",
    "performance_trend",
    "profit_loss_trend",
    "quality_loss",
    "quality_watch",
    "recurring_constraints",
    "resolve_scope",
    "scenario_savings",
    "scope_kpis",
    "scope_options",
    "shift_health",
    "station_economics",
    "station_watch",
    "what_matters_most",
]
