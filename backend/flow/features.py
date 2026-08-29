"""
Flow feature engineering (Step 5, Section M). Strictly point-in-time:
for a row at (shift_id, station_id, window_end_time=t), every feature is
computed from events/readings with `simulation_time <= t` only. There is
no "build everything then drop future columns" step — feature values are
computed directly from time-filtered slices, so there is no future data
in scope to leak from in the first place (see Section O / the
future-mutation test in tests/test_flow_leakage.py).

Lookback windows: 1m (60s), 3m (180s), 5m (300s) — the three "primary
recent windows" from Section C. No other horizon is used.

~35 features across the 7 groups from Section M. Grouped helper
functions below correspond 1:1 to those groups.
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Cold-start rows (e.g. before any buffer event has ever occurred for a
# station this early in a shift) legitimately have no data yet, producing
# expected (not erroneous) all-NaN slices in a handful of nanmax/nanmean
# calls below. Silenced narrowly by category+message rather than broadly,
# so a genuinely new warning class elsewhere still surfaces.
warnings.filterwarnings("ignore", message="All-NaN slice encountered", category=RuntimeWarning)
warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)

LOOKBACKS = {"1m": 60.0, "3m": 180.0, "5m": 300.0}


def _zone_of(station_id: str) -> str:
    n = int(station_id[1:])
    if n <= 12:
        return "body_joining"
    if n <= 20:
        return "paint_surface"
    if n <= 38:
        return "final_assembly"
    return "inspection_eol"


def _asof_value(times: np.ndarray, values: np.ndarray, query_times: np.ndarray) -> np.ndarray:
    """value recorded at the most recent time <= query_time, else NaN.
    times must be sorted ascending."""
    idx = np.searchsorted(times, query_times, side="right") - 1
    out = np.full(len(query_times), np.nan)
    valid = idx >= 0
    out[valid] = values[idx[valid]]
    return out


def _count_in_window(times: np.ndarray, query_times: np.ndarray, lookback: float) -> np.ndarray:
    """count of events with time in (t - lookback, t] for each t in query_times.
    times must be sorted ascending."""
    hi = np.searchsorted(times, query_times, side="right")
    lo = np.searchsorted(times, query_times - lookback, side="right")
    return hi - lo


def _agg_in_window(times: np.ndarray, values: np.ndarray, query_times: np.ndarray, lookback: float, agg: str) -> np.ndarray:
    """mean/std/max of `values` for events with time in (t-lookback, t]."""
    hi = np.searchsorted(times, query_times, side="right")
    lo = np.searchsorted(times, query_times - lookback, side="right")
    out = np.full(len(query_times), np.nan)
    for i, (l, h) in enumerate(zip(lo, hi)):
        if h > l:
            sl = values[l:h]
            if agg == "mean":
                out[i] = sl.mean()
            elif agg == "std":
                out[i] = sl.std() if len(sl) > 1 else 0.0
            elif agg == "max":
                out[i] = sl.max()
            elif agg == "sum":
                out[i] = sl.sum()
    return out


def _time_in_state_over_window(st_t: np.ndarray, st_to: np.ndarray, query_times: np.ndarray,
                                lookback: float, state_name: str) -> np.ndarray:
    """Fraction of `lookback` seconds ending at each query time spent in
    `state_name`, given a sorted array of STATION_STATE_CHANGED
    transition times/target-states. Vectorized replacement for the
    per-row, per-state nested Python loop this used to be (see git
    history) -- verified byte-identical to that loop via
    tests/test_flow_features_performance.py, since a ~4500-group,
    ~800-rows-per-group dataset made the pure-Python O(rows * transitions
    * 4 states) version take tens of minutes.

    Method: build a cumulative "time spent in state_name so far" function
    C(tau) at every transition point (state is piecewise-constant between
    transitions; time before the first transition is implicitly IDLE,
    contributing 0 to every one of the four tracked states, matching the
    original loop's `start_state = ... else "IDLE"` fallback). Window
    time-in-state = C(t) - C(t-lookback), each evaluated via the same
    asof (<=tau) convention as `_asof_value`, extending the last known
    state indefinitely forward past the final transition -- exactly the
    (t-lookback, t] half-open convention `_count_in_window` also uses.
    """
    n = len(query_times)
    if len(st_t) == 0:
        return np.zeros(n)

    is_target = (st_to == state_name).astype(float)
    # segment i (from st_t[i] to st_t[i+1]) is in state st_to[i]; the
    # final segment (from st_t[-1] onward) is handled via the "extend
    # last state forward" term below, not via cumsum.
    segment_durations = np.diff(st_t)
    contrib = segment_durations * is_target[:-1]
    # cumulative[k] = total target-state time strictly before st_t[k]
    cumulative = np.concatenate(([0.0], np.cumsum(contrib)))

    def _C(tau: np.ndarray) -> np.ndarray:
        idx = np.searchsorted(st_t, tau, side="right") - 1
        out = np.zeros(len(tau))
        valid = idx >= 0
        out[valid] = cumulative[idx[valid]] + (tau[valid] - st_t[idx[valid]]) * is_target[idx[valid]]
        return out

    window_time = _C(query_times) - _C(query_times - lookback)
    return np.clip(window_time, 0.0, lookback) / lookback


def build_features(grid: pd.DataFrame, events: pd.DataFrame, config, sensor_models: Dict) -> pd.DataFrame:
    """grid: [shift_id, station_id, window_end_time]. Returns grid with
    feature columns appended (float/categorical), strictly point-in-time."""
    inbound_buffers: Dict[str, List[str]] = {}
    outbound_buffers: Dict[str, List[str]] = {}
    for bid, b in config.buffers.items():
        inbound_buffers.setdefault(b.downstream_station, []).append(bid)
        outbound_buffers.setdefault(b.upstream_station, []).append(bid)
    capacities = {bid: b.capacity for bid, b in config.buffers.items()}

    primary_sensor: Dict[str, Optional[str]] = {}
    for sid, s in config.stations.items():
        candidates = [x for x in s.available_sensors if x != "cycle_time"]
        primary_sensor[sid] = candidates[0] if candidates else None

    out_rows = []
    for shift_id, shift_grid in grid.groupby("shift_id", sort=False):
        shift_events = events[events.shift_id == shift_id]
        for station_id, rows in shift_grid.groupby("station_id", sort=False):
            rows = rows.sort_values("window_end_time")
            t = rows.window_end_time.to_numpy()

            feats = {}
            # ---- 1. STATION PERFORMANCE ----
            proc = shift_events[(shift_events.event_type == "STATION_PROCESSING_COMPLETED") & (shift_events.station_id == station_id)].sort_values(["simulation_time", "event_id"])
            proc_t, proc_v = proc.simulation_time.to_numpy(), proc.value.to_numpy()
            baseline = config.stations[station_id].baseline_cycle_time_seconds

            feats["last_cycle_time"] = _asof_value(proc_t, proc_v, t)
            feats["cycle_time_mean_1m"] = _agg_in_window(proc_t, proc_v, t, LOOKBACKS["1m"], "mean")
            feats["cycle_time_mean_3m"] = _agg_in_window(proc_t, proc_v, t, LOOKBACKS["3m"], "mean")
            feats["cycle_time_mean_5m"] = _agg_in_window(proc_t, proc_v, t, LOOKBACKS["5m"], "mean")
            feats["cycle_time_std_5m"] = _agg_in_window(proc_t, proc_v, t, LOOKBACKS["5m"], "std")
            feats["cycle_time_dev_from_baseline"] = feats["last_cycle_time"] - baseline
            feats["cycle_time_dev_relative"] = feats["cycle_time_dev_from_baseline"] / baseline
            feats["cycle_time_slope_5m"] = feats["cycle_time_mean_1m"] - feats["cycle_time_mean_5m"]
            feats["completions_1m"] = _count_in_window(proc_t, t, LOOKBACKS["1m"])
            feats["completions_3m"] = _count_in_window(proc_t, t, LOOKBACKS["3m"])
            feats["completions_5m"] = _count_in_window(proc_t, t, LOOKBACKS["5m"])

            ms = shift_events[(shift_events.event_type == "MICRO_STOP_OCCURRED") & (shift_events.station_id == station_id)].sort_values(["simulation_time", "event_id"])
            ms_t, ms_v = ms.simulation_time.to_numpy(), ms.value.to_numpy()
            feats["microstop_count_5m"] = _count_in_window(ms_t, t, LOOKBACKS["5m"])
            feats["microstop_duration_5m"] = _agg_in_window(ms_t, ms_v, t, LOOKBACKS["5m"], "sum")
            feats["microstop_duration_5m"] = np.nan_to_num(feats["microstop_duration_5m"])
            last_ms = _asof_value(ms_t, ms_t, t)
            feats["time_since_last_microstop"] = np.where(np.isnan(last_ms), 9999.0, t - last_ms)

            # ---- 2. BUFFER / WIP ----
            def buffer_series(bid):
                e = shift_events[(shift_events.event_type.isin(["VEHICLE_ENTERED_BUFFER", "VEHICLE_LEFT_BUFFER"])) & (shift_events.buffer_id == bid)].sort_values(["simulation_time", "event_id"])
                return e.simulation_time.to_numpy(), e.occupancy.to_numpy(dtype=float)

            in_bids = inbound_buffers.get(station_id, [])
            if in_bids:
                cur_vals, max5_vals, mean5_vals, g1_vals, g3_vals, g5_vals, full5_vals = [], [], [], [], [], [], []
                for bid in in_bids:
                    bt, bv = buffer_series(bid)
                    cap = capacities[bid]
                    cur = _asof_value(bt, bv, t)
                    cur_vals.append(cur / cap)
                    max5_vals.append(_agg_in_window(bt, bv, t, LOOKBACKS["5m"], "max") / cap)
                    mean5_vals.append(_agg_in_window(bt, bv, t, LOOKBACKS["5m"], "mean") / cap)
                    for lb, store in [("1m", g1_vals), ("3m", g3_vals), ("5m", g5_vals)]:
                        past = _asof_value(bt, bv, t - LOOKBACKS[lb])
                        store.append(np.nan_to_num(cur * cap) - np.nan_to_num(past))
                    full5_vals.append((_agg_in_window(bt, bv, t, LOOKBACKS["5m"], "max") >= cap - 1e-9).astype(float))
                feats["inbound_occupancy_ratio"] = np.nanmax(np.vstack(cur_vals), axis=0)
                feats["inbound_occupancy_max_5m"] = np.nanmax(np.vstack(max5_vals), axis=0)
                feats["inbound_occupancy_mean_5m"] = np.nanmean(np.vstack(mean5_vals), axis=0)
                feats["inbound_growth_1m"] = np.nanmax(np.vstack(g1_vals), axis=0)
                feats["inbound_growth_3m"] = np.nanmax(np.vstack(g3_vals), axis=0)
                feats["inbound_growth_5m"] = np.nanmax(np.vstack(g5_vals), axis=0)
                feats["inbound_recent_full"] = np.nanmax(np.vstack(full5_vals), axis=0)
            else:
                for k in ["inbound_occupancy_ratio", "inbound_occupancy_max_5m", "inbound_occupancy_mean_5m",
                          "inbound_growth_1m", "inbound_growth_3m", "inbound_growth_5m", "inbound_recent_full"]:
                    feats[k] = np.zeros(len(t))

            out_bids = outbound_buffers.get(station_id, [])
            if out_bids:
                cur_vals, g3_vals = [], []
                for bid in out_bids:
                    bt, bv = buffer_series(bid)
                    cap = capacities[bid]
                    cur_vals.append(_asof_value(bt, bv, t) / cap)
                    past = _asof_value(bt, bv, t - LOOKBACKS["3m"])
                    cur_abs = _asof_value(bt, bv, t)
                    g3_vals.append(np.nan_to_num(cur_abs) - np.nan_to_num(past))
                feats["outbound_occupancy_ratio"] = np.nanmax(np.vstack(cur_vals), axis=0)
                feats["outbound_growth_3m"] = np.nanmax(np.vstack(g3_vals), axis=0)
            else:
                feats["outbound_occupancy_ratio"] = np.zeros(len(t))
                feats["outbound_growth_3m"] = np.zeros(len(t))

            # ---- 3. ARRIVAL / DEPARTURE FLOW ----
            arr = shift_events[(shift_events.event_type == "VEHICLE_ENTERED_STATION") & (shift_events.station_id == station_id)].sort_values(["simulation_time", "event_id"])
            arr_t = arr.simulation_time.to_numpy()
            arrivals_3m = _count_in_window(arr_t, t, LOOKBACKS["3m"])
            arrivals_5m = _count_in_window(arr_t, t, LOOKBACKS["5m"])
            arrivals_1m = _count_in_window(arr_t, t, LOOKBACKS["1m"])
            feats["arrivals_3m"] = arrivals_3m
            feats["arrivals_5m"] = arrivals_5m
            feats["arrival_minus_departure_5m"] = arrivals_5m - feats["completions_5m"]
            feats["arrival_rate_trend"] = (arrivals_1m / LOOKBACKS["1m"]) - (arrivals_5m / LOOKBACKS["5m"])

            # ---- 4. VEHICLE MIX (recent arrivals only, never future) ----
            variants = arr.vehicle_variant.to_numpy()
            arr_times_sorted = arr_t
            for variant_name, col in [("ICE_SEDAN", "mix_ice_sedan_5m"), ("ICE_SUV", "mix_ice_suv_5m"), ("EV", "mix_ev_5m")]:
                is_v = (variants == variant_name).astype(float)
                count_v = _agg_in_window(arr_times_sorted, is_v, t, LOOKBACKS["5m"], "sum")
                feats[col] = np.where(arrivals_5m > 0, np.nan_to_num(count_v) / np.maximum(arrivals_5m, 1), np.nan)

            # ---- 5. SENSOR / PROCESS TREND ----
            sensor_name = primary_sensor.get(station_id)
            if sensor_name:
                sr = shift_events[(shift_events.event_type == "SENSOR_READING") & (shift_events.station_id == station_id) & (shift_events.sensor_name == sensor_name)].sort_values(["simulation_time", "event_id"])
                sr_t = sr.simulation_time.to_numpy()
                sr_status = sr.measurement_status.to_numpy()
                sr_v = sr.value.to_numpy(dtype=float)
                avail_mask = sr_status == "available"
                avail_t, avail_v = sr_t[avail_mask], sr_v[avail_mask]
                sm = sensor_models.get((station_id, sensor_name))
                baseline_v = sm.baseline if sm else np.nan

                latest = _asof_value(avail_t, avail_v, t)
                feats["sensor_latest_value_dev"] = latest - baseline_v
                feats["sensor_mean_dev_5m"] = _agg_in_window(avail_t, avail_v - baseline_v, t, LOOKBACKS["5m"], "mean")
                feats["sensor_std_5m"] = _agg_in_window(avail_t, avail_v, t, LOOKBACKS["5m"], "std")
                total_5m = _count_in_window(sr_t, t, LOOKBACKS["5m"])
                avail_5m = _count_in_window(avail_t, t, LOOKBACKS["5m"])
                feats["sensor_missing_ratio_5m"] = np.where(total_5m > 0, 1 - avail_5m / np.maximum(total_5m, 1), 0.0)
                last_avail = _asof_value(avail_t, avail_t, t)
                feats["sensor_time_since_available"] = np.where(np.isnan(last_avail), 9999.0, t - last_avail)
            else:
                for k in ["sensor_latest_value_dev", "sensor_mean_dev_5m", "sensor_std_5m",
                          "sensor_missing_ratio_5m", "sensor_time_since_available"]:
                    feats[k] = np.full(len(t), np.nan)

            # ---- 6. OPERATIONAL STATE ----
            st = shift_events[(shift_events.event_type == "STATION_STATE_CHANGED") & (shift_events.station_id == station_id)].sort_values(["simulation_time", "event_id"])
            st_t = st.simulation_time.to_numpy()
            st_to = st.to_state.to_numpy()
            # state at each historical instant = to_state of the last transition <= that instant
            for state_name, col in [("PROCESSING", "prop_processing_5m"), ("STARVED", "prop_starved_5m"),
                                     ("BLOCKED", "prop_blocked_5m"), ("DOWN", "prop_down_5m")]:
                feats[col] = _time_in_state_over_window(st_t, st_to, t, LOOKBACKS["5m"], state_name)
            # "recent blocked time before now" (Section M.6) — seconds of
            # BLOCKED time in the last 5 minutes; prop_blocked_5m already IS
            # this as a fraction, so express it directly in seconds too since
            # that's a more directly interpretable operational quantity.
            feats["blocked_seconds_5m"] = feats["prop_blocked_5m"] * LOOKBACKS["5m"]

            # ---- 7. STATIC CONTEXT ----
            feats["station_type"] = [config.stations[station_id].station_type] * len(t)
            feats["sensor_maturity"] = [config.stations[station_id].sensor_maturity.value] * len(t)
            feats["zone"] = [_zone_of(station_id)] * len(t)

            chunk = rows.copy()
            for k, v in feats.items():
                chunk[k] = v
            out_rows.append(chunk)

    return pd.concat(out_rows, ignore_index=True)
