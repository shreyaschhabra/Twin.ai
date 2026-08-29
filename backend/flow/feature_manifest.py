"""
Flow feature manifest (Step 5, Section Q). Documents every feature's
name, description, source, lookback, and type — not derived from the
data itself, so it stays correct even if a feature happens to be
constant/missing in one particular dataset draw.
"""

from __future__ import annotations

FEATURE_MANIFEST = [
    # ---- 1. Station performance ----
    {"name": "last_cycle_time", "description": "Most recent observed processing time at this station", "source": "STATION_PROCESSING_COMPLETED", "lookback": "asof", "type": "numeric"},
    {"name": "cycle_time_mean_1m", "description": "Mean cycle time, last 1 minute", "source": "STATION_PROCESSING_COMPLETED", "lookback": "1m", "type": "numeric"},
    {"name": "cycle_time_mean_3m", "description": "Mean cycle time, last 3 minutes", "source": "STATION_PROCESSING_COMPLETED", "lookback": "3m", "type": "numeric"},
    {"name": "cycle_time_mean_5m", "description": "Mean cycle time, last 5 minutes", "source": "STATION_PROCESSING_COMPLETED", "lookback": "5m", "type": "numeric"},
    {"name": "cycle_time_std_5m", "description": "Std dev of cycle time, last 5 minutes", "source": "STATION_PROCESSING_COMPLETED", "lookback": "5m", "type": "numeric"},
    {"name": "cycle_time_dev_from_baseline", "description": "last_cycle_time minus configured healthy baseline", "source": "STATION_PROCESSING_COMPLETED + config", "lookback": "asof", "type": "numeric"},
    {"name": "cycle_time_dev_relative", "description": "cycle_time_dev_from_baseline / baseline", "source": "derived", "lookback": "asof", "type": "numeric"},
    {"name": "cycle_time_slope_5m", "description": "cycle_time_mean_1m - cycle_time_mean_5m (simple trend proxy)", "source": "derived", "lookback": "1m,5m", "type": "numeric"},
    {"name": "completions_1m", "description": "Count of completed vehicles, last 1 minute", "source": "STATION_PROCESSING_COMPLETED", "lookback": "1m", "type": "numeric"},
    {"name": "completions_3m", "description": "Count of completed vehicles, last 3 minutes", "source": "STATION_PROCESSING_COMPLETED", "lookback": "3m", "type": "numeric"},
    {"name": "completions_5m", "description": "Count of completed vehicles, last 5 minutes", "source": "STATION_PROCESSING_COMPLETED", "lookback": "5m", "type": "numeric"},
    {"name": "microstop_count_5m", "description": "Micro-stop count, last 5 minutes", "source": "MICRO_STOP_OCCURRED", "lookback": "5m", "type": "numeric"},
    {"name": "microstop_duration_5m", "description": "Total micro-stop duration, last 5 minutes", "source": "MICRO_STOP_OCCURRED", "lookback": "5m", "type": "numeric"},
    {"name": "time_since_last_microstop", "description": "Seconds since last micro-stop (9999 sentinel if none)", "source": "MICRO_STOP_OCCURRED", "lookback": "asof", "type": "numeric"},

    # ---- 2. Buffer / WIP ----
    {"name": "inbound_occupancy_ratio", "description": "Current inbound-buffer occupancy / capacity (max across multiple inbound buffers)", "source": "VEHICLE_ENTERED/LEFT_BUFFER", "lookback": "asof", "type": "numeric"},
    {"name": "inbound_occupancy_max_5m", "description": "Max inbound occupancy ratio, last 5 minutes", "source": "VEHICLE_ENTERED/LEFT_BUFFER", "lookback": "5m", "type": "numeric"},
    {"name": "inbound_occupancy_mean_5m", "description": "Mean inbound occupancy ratio, last 5 minutes", "source": "VEHICLE_ENTERED/LEFT_BUFFER", "lookback": "5m", "type": "numeric"},
    {"name": "inbound_growth_1m", "description": "Inbound occupancy change over last 1 minute", "source": "derived", "lookback": "1m", "type": "numeric"},
    {"name": "inbound_growth_3m", "description": "Inbound occupancy change over last 3 minutes", "source": "derived", "lookback": "3m", "type": "numeric"},
    {"name": "inbound_growth_5m", "description": "Inbound occupancy change over last 5 minutes", "source": "derived", "lookback": "5m", "type": "numeric"},
    {"name": "inbound_recent_full", "description": "1 if any inbound buffer hit capacity in last 5 minutes", "source": "derived", "lookback": "5m", "type": "numeric"},
    {"name": "outbound_occupancy_ratio", "description": "Current outbound-buffer occupancy / capacity", "source": "VEHICLE_ENTERED/LEFT_BUFFER", "lookback": "asof", "type": "numeric"},
    {"name": "outbound_growth_3m", "description": "Outbound occupancy change over last 3 minutes", "source": "derived", "lookback": "3m", "type": "numeric"},

    # ---- 3. Arrival / departure flow ----
    {"name": "arrivals_3m", "description": "Vehicles entering this station, last 3 minutes", "source": "VEHICLE_ENTERED_STATION", "lookback": "3m", "type": "numeric"},
    {"name": "arrivals_5m", "description": "Vehicles entering this station, last 5 minutes", "source": "VEHICLE_ENTERED_STATION", "lookback": "5m", "type": "numeric"},
    {"name": "arrival_minus_departure_5m", "description": "arrivals_5m - completions_5m (rate-mismatch signal)", "source": "derived", "lookback": "5m", "type": "numeric"},
    {"name": "arrival_rate_trend", "description": "1m arrival rate minus 5m arrival rate", "source": "derived", "lookback": "1m,5m", "type": "numeric"},

    # ---- 4. Vehicle mix ----
    {"name": "mix_ice_sedan_5m", "description": "Proportion of ICE Sedan among arrivals, last 5 minutes", "source": "VEHICLE_ENTERED_STATION", "lookback": "5m", "type": "numeric"},
    {"name": "mix_ice_suv_5m", "description": "Proportion of ICE SUV among arrivals, last 5 minutes", "source": "VEHICLE_ENTERED_STATION", "lookback": "5m", "type": "numeric"},
    {"name": "mix_ev_5m", "description": "Proportion of EV among arrivals, last 5 minutes", "source": "VEHICLE_ENTERED_STATION", "lookback": "5m", "type": "numeric"},

    # ---- 5. Sensor / process trend ----
    {"name": "sensor_latest_value_dev", "description": "Latest available primary-sensor value minus its configured baseline", "source": "SENSOR_READING + config", "lookback": "asof", "type": "numeric", "expected_missingness": "high at poor-maturity stations (no applicable sensor)"},
    {"name": "sensor_mean_dev_5m", "description": "Mean sensor deviation from baseline, last 5 minutes", "source": "SENSOR_READING", "lookback": "5m", "type": "numeric"},
    {"name": "sensor_std_5m", "description": "Std dev of sensor value, last 5 minutes", "source": "SENSOR_READING", "lookback": "5m", "type": "numeric"},
    {"name": "sensor_missing_ratio_5m", "description": "Fraction of sensor readings missing/degraded, last 5 minutes", "source": "SENSOR_READING", "lookback": "5m", "type": "numeric"},
    {"name": "sensor_time_since_available", "description": "Seconds since last available reading (9999 sentinel if none)", "source": "SENSOR_READING", "lookback": "asof", "type": "numeric"},

    # ---- 6. Operational state ----
    {"name": "prop_processing_5m", "description": "Fraction of last 5 minutes spent PROCESSING", "source": "STATION_STATE_CHANGED", "lookback": "5m", "type": "numeric"},
    {"name": "prop_starved_5m", "description": "Fraction of last 5 minutes spent STARVED", "source": "STATION_STATE_CHANGED", "lookback": "5m", "type": "numeric"},
    {"name": "prop_blocked_5m", "description": "Fraction of last 5 minutes spent BLOCKED (past history only — active bottleneck rows are excluded from the target)", "source": "STATION_STATE_CHANGED", "lookback": "5m", "type": "numeric"},
    {"name": "prop_down_5m", "description": "Fraction of last 5 minutes spent DOWN (micro-stops)", "source": "STATION_STATE_CHANGED", "lookback": "5m", "type": "numeric"},
    {"name": "blocked_seconds_5m", "description": "Seconds spent BLOCKED in the last 5 minutes", "source": "derived", "lookback": "5m", "type": "numeric"},

    # ---- 7. Static context ----
    {"name": "station_type", "description": "Reusable station-type template (e.g. WELDING_BODY_JOINING)", "source": "config", "lookback": "static", "type": "categorical"},
    {"name": "sensor_maturity", "description": "rich / partial / poor", "source": "config", "lookback": "static", "type": "categorical"},
    {"name": "zone", "description": "body_joining / paint_surface / final_assembly / inspection_eol", "source": "derived from station_id", "lookback": "static", "type": "categorical"},
]

METADATA_ONLY_COLUMNS = ["shift_id", "station_id", "window_end_time", "label", "target",
                          "lead_time_s", "target_onset_time", "partition"]
