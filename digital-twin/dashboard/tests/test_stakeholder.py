"""Deterministic tests for the stakeholder aggregation / business logic.

These never launch Streamlit. They build synthetic prediction streams the way the
runtime writes them (complete JSONL records) and assert on the pure functions in
:mod:`dashboard.stakeholder`.

Contract guards exercised here:

* defect status comes from ``warning`` only -- a final-inspection record with
  ``threshold_crossed = true`` / ``warning = false`` is never actioned and never
  counted as a defective unit;
* bottleneck and defect risk are never blended into one score;
* ``state_confidence`` drives the low-confidence / DARK flags;
* a missing stream yields empty results plus a note, never fabricated data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from dashboard.stakeholder import (
    EconomicsAssumptions,
    build_priority_queue,
    defect_concentration,
    financial_overview,
    observability,
    observe_economics,
    performance_trend,
    profit_loss_trend,
    quality_loss,
    quality_watch,
    recurring_constraints,
    resolve_scope,
    scenario_savings,
    scope_kpis,
    scope_options,
    shift_health,
    station_economics,
    station_watch,
    what_matters_most,
)
from dashboard.stakeholder.streams import load_run_streams
from dashboard.stakeholder.supervisor import KIND_BOTTLENECK, KIND_DEFECT


# -- builders ------------------------------------------------------------------


@dataclass
class FakeRun:
    run_id: str
    production_day: int
    predictions_path: str | None = None
    is_demo: bool = False
    metadata: dict = field(default_factory=dict)


def b_record(
    station, ts, prob, warning, *, confidence=1.0, zone="LIGHT", route="LIGHT",
    drivers=None, threshold=0.15, run_id="r1",
):
    record = {
        "schema_version": "bottleneck-prediction-v1",
        "run_id": run_id,
        "timestamp_ms": ts,
        "station_id": station,
        "vehicle_id": "U000001",
        "zone": zone,
        "route": route,
        "prediction_trigger": "UNIT_ARRIVED",
        "bottleneck_probability": prob,
        "bottleneck_risk_percent": prob * 100,
        "warning": warning,
        "decision_threshold": threshold,
        "decision_threshold_percent": threshold * 100,
        "state_confidence": confidence,
    }
    if drivers:
        record["explanation"] = {
            "top_drivers": [
                {"feature": name, "direction": "increases_risk"} for name in drivers
            ]
        }
    return record


def d_record(
    unit, ts, prob, warning, *, station="S02", confidence=1.0, route="LIGHT",
    threshold_crossed=None, drivers=None, final="S31", run_id="r1",
):
    record = {
        "schema_version": "defect-prediction-v2",
        "run_id": run_id,
        "timestamp_ms": ts,
        "unit_id": unit,
        "station_id": station,
        "station_index": 1,
        "final_inspection_station": final,
        "defect_probability": prob,
        "defect_risk_percent": prob * 100,
        "warning": warning,
        "threshold_crossed": warning if threshold_crossed is None else threshold_crossed,
        "route": route,
        "prediction_trigger": "UNIT_ARRIVED",
        "state_confidence": confidence,
        "decision_threshold": 0.14,
    }
    if drivers:
        record["top_risk_drivers"] = [
            {"feature": name, "label": name.replace("_", " ").title(), "effect": "raises_risk"}
            for name in drivers
        ]
    return record


def make_streams(tmp_path: Path, day: int, bottleneck_rows, defect_rows, *, health="PASS", metadata=None):
    run_dir = tmp_path / f"day{day:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if bottleneck_rows is not None:
        (run_dir / "bottleneck_predictions.jsonl").write_text(
            "\n".join(json.dumps(r) for r in bottleneck_rows) + "\n", encoding="utf-8"
        )
    if defect_rows is not None:
        (run_dir / "defect_predictions.jsonl").write_text(
            "\n".join(json.dumps(r) for r in defect_rows) + "\n", encoding="utf-8"
        )
    if health is not None:
        (run_dir / "system_health.json").write_text(
            json.dumps(
                {
                    "overall_status": health,
                    "bottleneck": {"status": "PASS" if health == "PASS" else "FAILED_ISOLATED"},
                    "defect": {"status": "PASS"},
                }
            ),
            encoding="utf-8",
        )
    return load_run_streams(
        FakeRun(
            run_id=f"r{day}", production_day=day, predictions_path=str(run_dir),
            metadata=metadata or {},
        )
    )


FACTORY = {
    "stations": [
        {"id": 0, "name": "Source", "sensorCoverage": "FULL", "source": True},
        {"id": 1, "name": "S02", "sensorCoverage": "FULL"},
        {"id": 2, "name": "S03", "sensorCoverage": "PARTIAL"},
        {"id": 3, "name": "S04", "sensorCoverage": "NONE"},
        {"id": 4, "name": "S05", "sensorCoverage": "NONE"},
    ],
    "darkZones": [{"id": "dz1", "startStationId": 3, "endStationId": 4}],
}


# -- Supervisor --------------------------------------------------------------


class TestPriorityQueue:
    def test_only_warning_rows_are_actioned_and_ranked_by_own_risk(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [
                b_record("S02", 100, 0.80, True, drivers=["queue_depth", "capacity_headroom"]),
                b_record("S03", 100, 0.90, False),  # high risk but not flagged -> excluded
            ],
            [
                d_record("U000005", 100, 0.62, True, station="S07", drivers=["line_fraction"]),
            ],
        )
        queue = build_priority_queue(streams)
        assert [a.reference for a in queue] == ["S02", "U000005"]  # 80% before 62%
        assert queue[0].kind == KIND_BOTTLENECK and queue[1].kind == KIND_DEFECT
        assert queue[0].drivers == ("Queue depth", "Capacity headroom")
        assert queue[1].drivers == ("Line Fraction",)
        # risks are each row's own value, never blended
        assert queue[0].risk_percent == 80.0
        assert queue[1].risk_percent == 62.0

    def test_defect_final_inspection_threshold_crossed_is_not_actioned(self, tmp_path):
        streams = make_streams(
            tmp_path, 1, [],
            [d_record("U000009", 200, 0.95, False, station="S31", final="S31", threshold_crossed=True)],
        )
        assert build_priority_queue(streams) == []

    def test_low_confidence_and_dark_context_flags(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [b_record("S04", 100, 0.77, True, confidence=0.4, zone="DARK", route="DARK_CORRIDOR")],
            [d_record("U000002", 100, 0.71, True, route="DARK_INFERRED", confidence=0.6)],
        )
        queue = build_priority_queue(streams)
        assert all(a.low_confidence for a in queue)
        assert all(a.dark_context for a in queue)


class TestWatchTables:
    def test_station_watch_lists_all_stations_alerting_first(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [
                b_record("S02", 100, 0.30, False),
                b_record("S03", 100, 0.55, True),
            ],
            [],
        )
        rows = station_watch(streams)
        assert [r.station for r in rows] == ["S03", "S02"]
        assert rows[0].warning and not rows[1].warning

    def test_quality_watch_priority_follows_warning(self, tmp_path):
        streams = make_streams(
            tmp_path, 1, [],
            [
                d_record("U000001", 100, 0.20, False, station="S02"),
                d_record("U000002", 100, 0.65, True, station="S08"),
            ],
        )
        rows = quality_watch(streams)
        assert rows[0].unit == "U000002"
        assert rows[0].inspection_priority == "High"
        assert rows[1].inspection_priority == "Monitor"
        assert rows[0].station == "S08"


class TestShiftHealth:
    def test_degraded_runtime_forces_intervention(self, tmp_path):
        streams = make_streams(tmp_path, 1, [b_record("S02", 100, 0.1, False)], [], health="DEGRADED")
        health = shift_health(streams)
        assert health.degraded is True
        assert health.intervention_required is True
        assert any("not PASS" in note for note in health.notes)

    def test_missing_defect_stream_is_a_note_not_a_crash(self, tmp_path):
        streams = make_streams(tmp_path, 1, [b_record("S02", 100, 0.1, False)], None)
        health = shift_health(streams)
        assert health.defect_stream_available is False
        assert any("No defect prediction stream" in note for note in health.notes)

    def test_counts_active_alerts_and_low_confidence(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [b_record("S02", 100, 0.8, True, confidence=0.5), b_record("S03", 100, 0.2, False)],
            [d_record("U000001", 100, 0.7, True, confidence=1.0)],
        )
        health = shift_health(streams)
        assert health.active_bottleneck_alerts == 1
        assert health.active_defect_alerts == 1
        assert health.low_confidence_bottleneck == 1
        assert health.low_confidence_defect == 0


# -- Plant Manager --------------------------------------------------------


def _two_day_scope(tmp_path):
    day1 = make_streams(
        tmp_path, 1,
        [
            b_record("S02", 100, 0.80, True, drivers=["queue_depth"]),
            b_record("S02", 200, 0.60, False),
            b_record("S05", 100, 0.30, False),
        ],
        [
            d_record("U000001", 100, 0.70, True, station="S09"),
            d_record("U000002", 100, 0.20, False, station="S03"),
        ],
    )
    day2 = make_streams(
        tmp_path, 2,
        [
            b_record("S02", 100, 0.85, True, drivers=["queue_depth", "capacity_headroom"]),
            b_record("S07", 100, 0.72, True, drivers=["cycle_time"]),
        ],
        [
            d_record("U000003", 100, 0.66, True, station="S09"),
        ],
        health="DEGRADED",
    )
    return [day1, day2]


class TestScopeKpis:
    def test_counts_days_alerts_and_affected_stations(self, tmp_path):
        kpi = scope_kpis(_two_day_scope(tmp_path))
        assert kpi.production_days == 2
        # S02 both days + S07 day 2 = 3 station-days
        assert kpi.bottleneck_alerts == 3
        assert kpi.defect_alerts == 2  # U1 day1, U3 day2
        assert kpi.affected_stations == 2  # S02, S07
        assert 0 <= kpi.avg_confidence_percent <= 100


class TestRecurringConstraints:
    def test_station_affected_every_day_ranks_first_and_is_high(self, tmp_path):
        constraints = recurring_constraints(_two_day_scope(tmp_path))
        assert constraints[0].station == "S02"
        assert constraints[0].days_affected == 2
        assert constraints[0].days_in_scope == 2
        assert constraints[0].risk_level == "High"
        assert "Queue depth" in constraints[0].drivers

    def test_empty_scope_has_no_constraints(self, tmp_path):
        clean = make_streams(tmp_path, 9, [b_record("S02", 100, 0.1, False)], [])
        assert recurring_constraints([clean]) == []


class TestDefectConcentration:
    def test_ranks_recurring_station_and_counts_distinct_units(self, tmp_path):
        conc = defect_concentration(_two_day_scope(tmp_path))
        assert conc[0].station == "S09"
        assert conc[0].days_affected == 2
        assert conc[0].units_affected == 2  # U1, U3
        assert conc[0].defect_events == 2


class TestPerformanceTrend:
    def test_series_are_separate_and_ordered_by_day(self, tmp_path):
        trend = performance_trend(_two_day_scope(tmp_path))
        assert [p.production_day for p in trend] == [1, 2]
        assert trend[0].bottleneck_alert_stations == 1
        assert trend[1].bottleneck_alert_stations == 2
        assert trend[0].defect_alert_units == 1
        assert trend[1].degraded is True


class TestObservability:
    def test_reads_coverage_from_factory_and_flags_dark(self, tmp_path):
        obs = observability(_two_day_scope(tmp_path), FACTORY)
        assert obs.total_stations == 5
        assert obs.coverage_breakdown.get("NONE") == 2
        assert obs.dark_zone_stations == 2
        assert obs.degraded_runs == 1
        assert obs.runs_in_scope == 2

    def test_handles_missing_factory(self, tmp_path):
        obs = observability(_two_day_scope(tmp_path), None)
        assert obs.total_stations == 0
        assert obs.coverage_breakdown == {}


# -- Leadership economics -------------------------------------------------


class TestObserveEconomics:
    def test_counts_alarms_as_warning_entries_and_defective_units_by_warning(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [
                b_record("S02", 100, 0.80, True),
                b_record("S02", 200, 0.82, True),   # same warning period -> 1 alarm
                b_record("S02", 300, 0.20, False),
                b_record("S02", 400, 0.81, True),   # re-entry -> 2nd alarm
            ],
            [
                d_record("U000001", 100, 0.90, True, station="S09"),
                d_record("U000001", 200, 0.91, True, station="S09"),  # same unit, still 1
                d_record("U000002", 100, 0.95, False, station="S31", final="S31", threshold_crossed=True),
            ],
        )
        observed = observe_economics([streams])
        assert observed.maintenance_alarms == 2
        assert observed.per_station_alarms["S02"] == 2
        assert observed.defective_units == 1  # U2's threshold_crossed row does not count
        assert observed.units_produced == 2  # distinct units in defect stream, no metadata

    def test_units_produced_prefers_simulator_metadata(self, tmp_path):
        streams = make_streams(
            tmp_path, 1, [], [d_record("U000001", 100, 0.1, False)],
            metadata={"run_metadata": {"units_created": 480}},
        )
        assert observe_economics([streams]).units_produced == 480


ASSUMPTIONS = EconomicsAssumptions(
    revenue_per_unit=1000.0,
    maintenance_cost_per_alarm=500.0,
    cost_per_defective_unit=800.0,
    downtime_cost_per_alarm=200.0,
    scrap_rework_cost_per_unit=100.0,
)


class TestFinancialOverview:
    def test_is_assumptions_times_events(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [b_record("S02", 100, 0.8, True), b_record("S02", 200, 0.2, False), b_record("S02", 300, 0.8, True)],
            [d_record("U000001", 100, 0.9, True, station="S09")],
            metadata={"run_metadata": {"units_created": 100}},
        )
        observed = observe_economics([streams])
        overview = financial_overview(observed, ASSUMPTIONS)
        # 2 alarms, 1 defective unit, 100 units
        assert overview.estimated_revenue == 100 * 1000.0
        assert overview.estimated_maintenance_cost == 2 * 500.0
        assert overview.estimated_downtime_cost == 2 * 200.0
        assert overview.estimated_defect_loss == 1 * (800.0 + 100.0)
        avoidable = 1000.0 + 400.0 + 900.0
        assert overview.estimated_avoidable_loss == avoidable
        assert overview.estimated_profit == 100_000.0 - avoidable
        assert "Not measured plant financials" in overview.basis

    def test_is_deterministic(self, tmp_path):
        streams = make_streams(
            tmp_path, 1, [b_record("S02", 100, 0.8, True)], [d_record("U000001", 100, 0.9, True)],
        )
        observed = observe_economics([streams])
        assert financial_overview(observed, ASSUMPTIONS) == financial_overview(observed, ASSUMPTIONS)


class TestStationAndQualityTables:
    def test_station_economics_attributes_revenue_and_ranks_by_cost(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [b_record("S02", 100, 0.8, True), b_record("S03", 100, 0.9, True), b_record("S03", 200, 0.2, False), b_record("S03", 300, 0.9, True)],
            [
                d_record("U000001", 100, 0.1, False, station="S02"),
                d_record("U000002", 100, 0.1, False, station="S03"),
                d_record("U000003", 100, 0.1, False, station="S03"),
            ],
            metadata={"run_metadata": {"units_created": 90}},
        )
        observed = observe_economics([streams])
        rows = station_economics(observed, ASSUMPTIONS)
        assert rows[0].station == "S03"  # 2 alarms -> highest maintenance cost first
        assert rows[0].maintenance_alarm_count == 2
        assert rows[0].estimated_maintenance_cost == 2 * (500.0 + 200.0)
        total_revenue = sum(r.revenue_contribution for r in rows)
        assert round(total_revenue, 2) == 90 * 1000.0  # whole pool attributed

    def test_quality_loss_sorted_by_loss(self, tmp_path):
        streams = make_streams(
            tmp_path, 1, [],
            [
                d_record("U000001", 100, 0.9, True, station="S09"),
                d_record("U000002", 100, 0.9, True, station="S09"),
                d_record("U000003", 100, 0.9, True, station="S12"),
            ],
        )
        observed = observe_economics([streams])
        rows = quality_loss(observed, ASSUMPTIONS)
        assert rows[0].station == "S09"
        assert rows[0].units_affected == 2
        assert rows[0].estimated_defect_loss == 2 * (800.0 + 100.0)


class TestTrendAndScenario:
    def test_profit_loss_trend_is_per_day(self, tmp_path):
        scope = _two_day_scope(tmp_path)
        # give each day a unit count via metadata-less distinct units already present
        trend = profit_loss_trend(observe_economics(scope), ASSUMPTIONS)
        assert [row["production_day"] for row in trend] == [1, 2]
        for row in trend:
            assert row["estimated_profit"] == row["modeled_revenue"] - row["modeled_cost"]

    def test_scenario_savings_scale_with_reduction(self, tmp_path):
        streams = make_streams(
            tmp_path, 1,
            [b_record("S02", 100, 0.8, True), b_record("S02", 200, 0.2, False), b_record("S02", 300, 0.8, True)],
            [d_record("U000001", 100, 0.9, True)],
            metadata={"run_metadata": {"units_created": 100}},
        )
        observed = observe_economics([streams])
        overview = financial_overview(observed, ASSUMPTIONS)
        scenarios = scenario_savings(observed, ASSUMPTIONS)
        assert [s["reduction"] for s in scenarios] == [0.10, 0.20, 0.30]
        assert scenarios[0]["modeled_saving"] == round(overview.estimated_avoidable_loss * 0.10, 2)
        assert scenarios[2]["modeled_profit_after"] == round(
            overview.estimated_profit + overview.estimated_avoidable_loss * 0.30, 2
        )

    def test_what_matters_most_handles_a_clean_scope(self, tmp_path):
        clean = make_streams(tmp_path, 1, [b_record("S02", 100, 0.1, False)], [d_record("U000001", 100, 0.1, False)])
        messages = what_matters_most(observe_economics([clean]), ASSUMPTIONS)
        assert messages and "no" in messages[0].lower()


# -- scope resolution -----------------------------------------------------


class TestScopeResolution:
    def _runs(self):
        return [FakeRun("r3", 3), FakeRun("r2", 2), FakeRun("r1", 1)]  # newest first

    def test_options_list_current_all_then_days(self):
        assert scope_options(self._runs())[:2] == ["Current Run", "All Runs"]
        assert "Production Day 3" in scope_options(self._runs())

    def test_all_runs_returns_everything(self):
        assert len(resolve_scope(self._runs(), "All Runs")) == 3

    def test_production_day_selects_that_day(self):
        picked = resolve_scope(self._runs(), "Production Day 2")
        assert [r.run_id for r in picked] == ["r2"]

    def test_current_run_honours_selection_then_falls_back_to_latest(self):
        runs = self._runs()
        assert [r.run_id for r in resolve_scope(runs, "Current Run", selected_run_id="r1")] == ["r1"]
        assert [r.run_id for r in resolve_scope(runs, "Current Run")] == ["r3"]

    def test_empty_history_is_empty(self):
        assert resolve_scope([], "All Runs") == []
