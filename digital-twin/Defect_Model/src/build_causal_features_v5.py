from __future__ import annotations

import argparse
import json
import math
import re
import zipfile
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from feature_schema import DEFECT_FEATURES, META_COLUMNS, RECENT_MS, TARGET_COLUMN

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / 'factory_defect_prediction_v2_pack'
DEFAULT_OUT = ROOT / 'generated_features_v5'
ST_RE = re.compile(r'^S(\d+)', re.I)

REQUIRED_FILES = [
    'stations.csv',
    'station_events.csv',
    'sensor_readings.csv',
    'manual_checks.csv',
    'inspection_results.csv',
    'units.csv',
]

SENSOR_SIGNALS = ('TORQUE', 'VIBRATION', 'TEMPERATURE', 'CURRENT')
MIN_SENSOR_ASSIGNMENT_RATE = 0.05  # hard-stop only if assignment is essentially broken
WARN_SENSOR_ASSIGNMENT_RATE = 0.50


def station_number(x) -> int:
    m = ST_RE.match(str(x))
    if not m:
        raise ValueError(f'Invalid station id: {x!r}')
    return int(m.group(1))


@dataclass
class CausalNumericIndex:
    """
    Numeric observations belonging to one unit.

    station_index:
        Source station of each observation.
    timestamp_ms:
        Timestamp of the actual numeric observation.
    available_time_ms:
        Earliest time at which the observation/assignment is fully available.
        For unit-linked sensors this is the PROCESSING_COMPLETED time of the
        source interval. For queue observations it is the queue event time.
    """
    timestamp_ms: np.ndarray
    value: np.ndarray
    station_index: np.ndarray
    available_time_ms: np.ndarray

    @classmethod
    def make(cls, timestamp_ms, value, station_index, available_time_ms=None):
        t = np.asarray(timestamp_ms, dtype=np.int64)
        v = np.asarray(value, dtype=float)
        s = np.asarray(station_index, dtype=np.int32)
        a = t.copy() if available_time_ms is None else np.asarray(
            available_time_ms, dtype=np.int64
        )

        if not (len(t) == len(v) == len(s) == len(a)):
            raise ValueError('CausalNumericIndex arrays have inconsistent lengths')

        if len(t) == 0:
            return cls(
                np.array([], dtype=np.int64),
                np.array([], dtype=float),
                np.array([], dtype=np.int32),
                np.array([], dtype=np.int64),
            )

        order = np.lexsort((s, t))
        return cls(
            timestamp_ms=t[order],
            value=v[order],
            station_index=s[order],
            available_time_ms=a[order],
        )

    def query(
        self,
        prediction_station_index: int,
        prediction_time: int,
        window_ms: int | None = None,
    ) -> dict:
        if len(self.timestamp_ms) == 0:
            return {'mean': np.nan, 'max': np.nan, 'std': np.nan, 'count': 0}

        # STRICT CAUSALITY:
        # 1) source station is upstream;
        # 2) observation itself is strictly in the past;
        # 3) the source interval/event was fully available strictly in the past.
        mask = (
            (self.station_index < int(prediction_station_index))
            & (self.timestamp_ms < int(prediction_time))
            & (self.available_time_ms < int(prediction_time))
        )

        if window_ms is not None:
            mask &= self.timestamp_ms >= int(prediction_time) - int(window_ms)

        vals = self.value[mask]
        vals = vals[np.isfinite(vals)]
        count = int(len(vals))
        if count == 0:
            return {'mean': np.nan, 'max': np.nan, 'std': np.nan, 'count': 0}

        return {
            'mean': float(np.mean(vals)),
            'max': float(np.max(vals)),
            'std': float(np.std(vals, ddof=1)) if count > 1 else np.nan,
            'count': count,
        }


def read_run_zip(zip_path: Path) -> dict[str, pd.DataFrame]:
    out = {}
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = {Path(n).name: n for n in zf.namelist() if not n.endswith('/')}
        missing = [f for f in REQUIRED_FILES if f not in names]
        if missing:
            raise RuntimeError(f'{zip_path.name}: missing raw files {missing}')
        for filename in REQUIRED_FILES:
            with zf.open(names[filename]) as f:
                out[filename] = pd.read_csv(f)
    return out


def build_final_qa_index(inspections: pd.DataFrame, final_station: str):
    q = inspections[inspections['station_id'].astype(str).eq(final_station)].copy()
    q['timestamp_ms'] = pd.to_numeric(q['timestamp_ms'], errors='coerce')
    q['result'] = q['result'].astype(str).str.strip().str.upper()
    q = q[q['result'].isin(['PASS', 'FAIL']) & q['timestamp_ms'].notna()]

    out = {}
    for uid, g in q.groupby('unit_id', sort=False):
        g = g.sort_values('timestamp_ms', kind='stable')
        times = g['timestamp_ms'].to_numpy(dtype=np.int64)
        fails = g['result'].eq('FAIL').to_numpy(dtype=bool)
        future_fail = np.maximum.accumulate(fails[::-1])[::-1]
        out[str(uid)] = (times, future_fail)
    return out


def build_processing_intervals(events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Pair PROCESSING_STARTED -> PROCESSING_COMPLETED for each (unit, station).

    Pairing is performed in timestamp/event_sequence order and supports repeated
    visits. Only strictly positive-duration completed intervals are kept.
    """
    relevant = events[
        events['event_type'].isin(['PROCESSING_STARTED', 'PROCESSING_COMPLETED'])
        & events['unit_id'].notna()
        & events['station_index'].notna()
        & events['timestamp_ms'].notna()
    ].copy()

    relevant = relevant.sort_values(
        ['unit_id', 'station_index', 'timestamp_ms', 'event_sequence'],
        kind='stable',
    )

    records = []
    unmatched_starts = 0
    unmatched_completions = 0
    invalid_intervals = 0

    for (uid, station_id, sidx), g in relevant.groupby(
        ['unit_id', 'station_id', 'station_index'],
        sort=False,
    ):
        starts = deque()
        for r in g.itertuples(index=False):
            event_type = str(r.event_type)
            t = int(r.timestamp_ms)
            seq = int(r.event_sequence)

            if event_type == 'PROCESSING_STARTED':
                starts.append((t, seq))
                continue

            # PROCESSING_COMPLETED
            while starts and starts[0][0] > t:
                starts.popleft()
                unmatched_starts += 1

            if not starts:
                unmatched_completions += 1
                continue

            start_t, start_seq = starts.popleft()
            if start_t >= t:
                invalid_intervals += 1
                continue

            records.append(
                {
                    'unit_id': str(uid),
                    'station_id': str(station_id),
                    'station_index': int(sidx),
                    'processing_start': int(start_t),
                    'processing_end': int(t),
                    'start_event_sequence': int(start_seq),
                    'end_event_sequence': int(seq),
                }
            )

        unmatched_starts += len(starts)

    intervals = pd.DataFrame.from_records(records)
    if intervals.empty:
        intervals = pd.DataFrame(
            columns=[
                'unit_id',
                'station_id',
                'station_index',
                'processing_start',
                'processing_end',
                'start_event_sequence',
                'end_event_sequence',
            ]
        )

    overlap_count = 0
    if not intervals.empty:
        for _, g in intervals.groupby('station_id', sort=False):
            g = g.sort_values(['processing_start', 'processing_end'], kind='stable')
            starts = g['processing_start'].to_numpy(dtype=np.int64)
            ends = g['processing_end'].to_numpy(dtype=np.int64)
            if len(g) > 1:
                overlap_count += int(np.sum(starts[1:] < ends[:-1]))

    diagnostics = {
        'valid_processing_intervals': int(len(intervals)),
        'unmatched_processing_starts': int(unmatched_starts),
        'unmatched_processing_completions': int(unmatched_completions),
        'invalid_processing_intervals': int(invalid_intervals),
        'overlapping_station_intervals': int(overlap_count),
    }
    return intervals, diagnostics


def assign_sensors_to_units(
    sensors: pd.DataFrame,
    intervals: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    Assign sensor readings to the unit actively processed at the same station.

    We use a station-local merge_asof from sensor timestamp to the latest
    processing_start, then require timestamp <= processing_end. This is
    efficient and avoids any unit x sensor Cartesian join.
    """
    candidate = sensors[
        sensors['station_index'].notna()
        & sensors['timestamp_ms'].notna()
        & sensors['value'].notna()
        & sensors['sensor_type'].isin(SENSOR_SIGNALS)
    ].copy()

    assigned_parts = []
    for station_id, sd in candidate.groupby('station_id', sort=False):
        ints = intervals[intervals['station_id'].astype(str).eq(str(station_id))].copy()
        if ints.empty:
            continue

        sd = sd.sort_values('timestamp_ms', kind='stable').copy()
        ints = ints.sort_values(
            ['processing_start', 'processing_end', 'start_event_sequence'],
            kind='stable',
        ).copy()

        # Rename before merge to avoid accidental collisions.
        right = ints[
            [
                'unit_id',
                'station_index',
                'processing_start',
                'processing_end',
                'start_event_sequence',
                'end_event_sequence',
            ]
        ].rename(
            columns={
                'unit_id': '_assigned_unit_id',
                'station_index': '_interval_station_index',
            }
        )

        merged = pd.merge_asof(
            sd,
            right,
            left_on='timestamp_ms',
            right_on='processing_start',
            direction='backward',
            allow_exact_matches=True,
        )

        legal = (
            merged['_assigned_unit_id'].notna()
            & merged['processing_end'].notna()
            & (merged['timestamp_ms'] >= merged['processing_start'])
            & (merged['timestamp_ms'] <= merged['processing_end'])
            & (
                merged['station_index'].astype('Int64')
                == merged['_interval_station_index'].astype('Int64')
            )
        )
        merged = merged.loc[legal].copy()
        if merged.empty:
            continue

        merged['unit_id'] = merged['_assigned_unit_id'].astype(str)
        merged['interval_end_time'] = merged['processing_end'].astype(np.int64)
        assigned_parts.append(
            merged[
                [
                    'unit_id',
                    'station_id',
                    'station_index',
                    'timestamp_ms',
                    'interval_end_time',
                    'sensor_type',
                    'value',
                ]
            ]
        )

    if assigned_parts:
        assigned = pd.concat(assigned_parts, ignore_index=True)
    else:
        assigned = pd.DataFrame(
            columns=[
                'unit_id',
                'station_id',
                'station_index',
                'timestamp_ms',
                'interval_end_time',
                'sensor_type',
                'value',
            ]
        )

    candidate_count = int(len(candidate))
    assigned_count = int(len(assigned))
    assignment_rate = (
        float(assigned_count / candidate_count) if candidate_count else None
    )

    diagnostics = {
        'candidate_sensor_rows': candidate_count,
        'assigned_sensor_rows': assigned_count,
        'sensor_assignment_rate': assignment_rate,
    }

    if candidate_count > 0:
        if assigned_count == 0 or assignment_rate < MIN_SENSOR_ASSIGNMENT_RATE:
            raise RuntimeError(
                f'Unit-specific sensor assignment appears broken: '
                f'{assigned_count}/{candidate_count} rows assigned '
                f'({100 * assignment_rate:.2f}%).'
            )

    return assigned, diagnostics


def build_sensor_indexes(assigned_sensors: pd.DataFrame):
    by_unit: dict[str, dict[str, CausalNumericIndex]] = defaultdict(dict)
    if assigned_sensors.empty:
        return dict(by_unit)

    for (uid, signal), g in assigned_sensors.groupby(
        ['unit_id', 'sensor_type'],
        sort=False,
    ):
        by_unit[str(uid)][str(signal)] = CausalNumericIndex.make(
            g['timestamp_ms'].to_numpy(dtype=np.int64),
            g['value'].to_numpy(dtype=float),
            g['station_index'].to_numpy(dtype=np.int32),
            g['interval_end_time'].to_numpy(dtype=np.int64),
        )
    return dict(by_unit)


def build_queue_indexes(events: pd.DataFrame):
    """
    Unit-specific queue exposure.

    Queue state at UNIT_ARRIVED represents the queue encountered by that unit.
    Only past, upstream arrivals can enter a later prediction.
    """
    q = events[
        events['event_type'].eq('UNIT_ARRIVED')
        & events['unit_id'].notna()
        & events['station_index'].notna()
        & events['timestamp_ms'].notna()
        & events['queue_length_after'].notna()
    ].copy()

    out = {}
    for uid, g in q.groupby('unit_id', sort=False):
        out[str(uid)] = CausalNumericIndex.make(
            g['timestamp_ms'].to_numpy(dtype=np.int64),
            g['queue_length_after'].to_numpy(dtype=float),
            g['station_index'].to_numpy(dtype=np.int32),
            g['timestamp_ms'].to_numpy(dtype=np.int64),
        )
    return out, int(len(q))


def generate_run(zip_path: str, split: str):
    zip_path = Path(zip_path)
    run_id = zip_path.stem
    raw = read_run_zip(zip_path)

    stations = raw['stations.csv'].copy()
    stations['station_id'] = stations['station_id'].astype(str)
    stations['station_index'] = stations['station_id'].map(station_number) - 1
    station_map = dict(
        zip(stations['station_id'], stations['station_index'].astype(int))
    )

    if 'archetype' not in stations.columns:
        raise RuntimeError(f'{run_id}: stations.csv has no archetype column')

    inspection_stations = stations[
        stations['archetype'].astype(str).str.strip().str.upper().eq('INSPECTION')
    ].sort_values('station_index')
    if inspection_stations.empty:
        raise RuntimeError(f'{run_id}: no INSPECTION station found')

    final_station = str(inspection_stations.iloc[-1]['station_id'])
    final_station_index = int(inspection_stations.iloc[-1]['station_index'])
    total_stations = int(len(stations))

    units = raw['units.csv'].copy()
    units['unit_id'] = units['unit_id'].astype(str)
    unit_map = units.set_index('unit_id')

    events = raw['station_events.csv'].copy()
    events['event_sequence'] = np.arange(len(events), dtype=np.int64)
    events['unit_id'] = events['unit_id'].astype('string')
    events['station_id'] = events['station_id'].astype(str)
    events['event_type'] = events['event_type'].astype(str).str.strip().str.upper()
    events['station_index'] = events['station_id'].map(station_map)
    events['timestamp_ms'] = pd.to_numeric(events['timestamp_ms'], errors='coerce')
    events['cycle_time_ms'] = pd.to_numeric(events['cycle_time_ms'], errors='coerce')
    events['queue_length_after'] = pd.to_numeric(
        events['queue_length_after'], errors='coerce'
    )

    predictions = events[
        events['event_type'].eq('UNIT_ARRIVED')
        & events['station_index'].notna()
        & events['unit_id'].notna()
        & events['timestamp_ms'].notna()
        & (events['station_index'] <= final_station_index)
    ].copy()
    assert (predictions['station_index'] <= final_station_index).all()

    sensors = raw['sensor_readings.csv'].copy()
    sensors['station_id'] = sensors['station_id'].astype(str)
    sensors['station_index'] = sensors['station_id'].map(station_map)
    sensors['timestamp_ms'] = pd.to_numeric(sensors['timestamp_ms'], errors='coerce')
    sensors['value'] = pd.to_numeric(sensors['value'], errors='coerce')
    sensors['sensor_type'] = sensors['sensor_type'].astype(str).str.strip().str.upper()

    intervals, interval_diag = build_processing_intervals(events)
    assigned_sensors, sensor_diag = assign_sensors_to_units(sensors, intervals)
    sensor_by_unit = build_sensor_indexes(assigned_sensors)

    queue_by_unit, queue_observation_count = build_queue_indexes(events)

    manual = raw['manual_checks.csv'].copy()
    manual['unit_id'] = manual['unit_id'].astype(str)
    manual['station_id'] = manual['station_id'].astype(str)
    manual['station_index'] = manual['station_id'].map(station_map)
    manual['timestamp_ms'] = pd.to_numeric(manual['timestamp_ms'], errors='coerce')
    manual['result'] = manual['result'].astype(str).str.strip().str.upper()
    manual_by_unit = {
        str(uid): g.sort_values('timestamp_ms', kind='stable')
        for uid, g in manual.groupby('unit_id', sort=False)
    }

    qa_index = build_final_qa_index(raw['inspection_results.csv'], final_station)

    completed = events[
        events['event_type'].eq('PROCESSING_COMPLETED')
        & events['unit_id'].notna()
        & events['station_index'].notna()
        & events['timestamp_ms'].notna()
        & events['cycle_time_ms'].notna()
    ].copy()
    cycles_by_unit = {
        str(uid): g.sort_values(['timestamp_ms', 'event_sequence'], kind='stable')
        for uid, g in completed.groupby('unit_id', sort=False)
    }

    rows = []
    history_coverage = {signal: 0 for signal in SENSOR_SIGNALS}
    recent_coverage = {signal: 0 for signal in SENSOR_SIGNALS}

    predictions = predictions.sort_values(
        ['timestamp_ms', 'event_sequence'],
        kind='stable',
    )

    for r in predictions.itertuples(index=False):
        uid = str(r.unit_id)
        station_id = str(r.station_id)
        sidx = int(r.station_index)
        prediction_time = int(r.timestamp_ms)

        if uid not in unit_map.index:
            raise RuntimeError(f'{run_id}: unit {uid} missing from units.csv')

        # Target is FUTURE final-QA result only.
        qa = qa_index.get(uid)
        if qa is None:
            y = np.nan
            completeness = 'censored'
        else:
            qa_times, future_fail = qa
            j = int(np.searchsorted(qa_times, prediction_time, side='right'))
            if j >= len(qa_times):
                y = np.nan
                completeness = 'censored'
            else:
                y = float(bool(future_fail[j]))
                completeness = 'complete'

        unit_sensor_indexes = sensor_by_unit.get(uid, {})
        sf = {}
        for signal, prefix in [
            ('TORQUE', 'torque'),
            ('VIBRATION', 'vibration'),
            ('TEMPERATURE', 'temperature'),
            ('CURRENT', 'current'),
        ]:
            idx = unit_sensor_indexes.get(signal)
            if idx is None:
                hist = {'mean': np.nan, 'max': np.nan, 'std': np.nan, 'count': 0}
                recent = {'mean': np.nan, 'max': np.nan, 'std': np.nan, 'count': 0}
            else:
                hist = idx.query(sidx, prediction_time)
                recent = idx.query(sidx, prediction_time, RECENT_MS)

            sf[f'{prefix}_mean_history'] = hist['mean']
            sf[f'{prefix}_max_history'] = hist['max']
            sf[f'{prefix}_std_history'] = hist['std']
            sf[f'{prefix}_mean_recent'] = recent['mean']
            sf[f'{prefix}_max_recent'] = recent['max']

            if hist['count'] > 0:
                history_coverage[signal] += 1
            if recent['count'] > 0:
                recent_coverage[signal] += 1

        qidx = queue_by_unit.get(uid)
        if qidx is None:
            qhist = {'mean': np.nan, 'max': np.nan, 'std': np.nan, 'count': 0}
        else:
            qhist = qidx.query(sidx, prediction_time)

        # Unit-specific manual checks: upstream and strictly before prediction.
        mg = manual_by_unit.get(uid)
        if mg is None:
            legal_manual = None
        else:
            legal_manual = mg[
                (mg['station_index'] < sidx)
                & (mg['timestamp_ms'] < prediction_time)
            ]

        if legal_manual is None or legal_manual.empty:
            manual_fail_count = 0.0
            manual_check_count = 0.0
            last_manual_fail = np.nan
            stations_since_last_manual_fail = np.nan
        else:
            manual_check_count = float(len(legal_manual))
            manual_fail_count = float(legal_manual['result'].eq('FAIL').sum())
            last_manual_fail = (
                1.0 if str(legal_manual.iloc[-1]['result']).upper() == 'FAIL' else 0.0
            )
            fails = legal_manual[legal_manual['result'].eq('FAIL')]
            stations_since_last_manual_fail = (
                float(sidx - int(fails.iloc[-1]['station_index']))
                if not fails.empty
                else np.nan
            )

        # Unit-specific completed upstream cycles, strictly in the past.
        cg = cycles_by_unit.get(uid)
        if cg is None:
            legal_cycles = None
        else:
            legal_cycles = cg[
                (cg['station_index'] < sidx)
                & (cg['timestamp_ms'] < prediction_time)
            ]

        if legal_cycles is None or legal_cycles.empty:
            cycle_history_max = np.nan
            cycle_history_std = np.nan
        else:
            cv = legal_cycles['cycle_time_ms'].to_numpy(dtype=float)
            finite_cv = cv[np.isfinite(cv)]
            cycle_history_max = (
                float(np.max(finite_cv)) if len(finite_cv) else np.nan
            )
            cycle_history_std = (
                float(np.std(finite_cv, ddof=1)) if len(finite_cv) > 1 else np.nan
            )

        ui = unit_map.loc[uid]

        torque_delta = (
            sf['torque_mean_recent'] - sf['torque_mean_history']
            if np.isfinite(sf['torque_mean_recent'])
            and np.isfinite(sf['torque_mean_history'])
            else np.nan
        )
        vibration_delta = (
            sf['vibration_mean_recent'] - sf['vibration_mean_history']
            if np.isfinite(sf['vibration_mean_recent'])
            and np.isfinite(sf['vibration_mean_history'])
            else np.nan
        )

        row = {
            'split': split,
            'run_id': run_id,
            'unit_id': uid,
            'prediction_station': station_id,
            'prediction_time': prediction_time,
            'prediction_event_sequence': int(r.event_sequence),
            'label_completeness_status': completeness,
            'final_station_index': final_station_index,
            'torque_delta_recent_vs_history': torque_delta,
            'manual_fail_count_cum': manual_fail_count,
            'prediction_station_index': sidx,
            'torque_mean_history': sf['torque_mean_history'],
            'line_fraction': sidx / max(1, total_stations - 1),
            'last_manual_fail': last_manual_fail,
            'manual_check_count_cum': manual_check_count,
            'torque_mean_recent': sf['torque_mean_recent'],
            'queue_history_mean': qhist['mean'],
            'current_mean_recent': sf['current_mean_recent'],
            'current_missing_recent': (
                0.0 if np.isfinite(sf['current_mean_recent']) else 1.0
            ),
            'vibration_delta_recent_vs_history': vibration_delta,
            'current_mean_history': sf['current_mean_history'],
            'torque_max_recent': sf['torque_max_recent'],
            'temperature_mean_history': sf['temperature_mean_history'],
            'torque_max_history': sf['torque_max_history'],
            'supplier_batch': ui['supplier_batch'],
            'current_max_history': sf['current_max_history'],
            'cycle_history_max': cycle_history_max,
            'temperature_max_recent': sf['temperature_max_recent'],
            'vibration_mean_history': sf['vibration_mean_history'],
            'temperature_max_history': sf['temperature_max_history'],
            'stations_since_last_manual_fail': stations_since_last_manual_fail,
            'vehicle_model': ui['vehicle_model'],
            'vibration_max_history': sf['vibration_max_history'],
            'vibration_max_recent': sf['vibration_max_recent'],
            'temperature_mean_recent': sf['temperature_mean_recent'],
            'torque_std_history': sf['torque_std_history'],
            'queue_history_std': qhist['std'],
            'cycle_history_std': cycle_history_std,
            TARGET_COLUMN: y,
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    missing_features = [c for c in DEFECT_FEATURES if c not in df.columns]
    if missing_features:
        raise RuntimeError(f'{run_id}: missing generated features {missing_features}')
    if len(DEFECT_FEATURES) != 30 or len(set(DEFECT_FEATURES)) != 30:
        raise RuntimeError('Feature contract is not exactly 30 unique features')
    if TARGET_COLUMN in DEFECT_FEATURES:
        raise RuntimeError('Target leaked into feature list')

    # Diagnostics / sanity checks.
    prediction_rows = max(1, len(df))
    sensor_history_coverage_rate = {
        signal: float(history_coverage[signal] / prediction_rows)
        for signal in SENSOR_SIGNALS
    }
    sensor_recent_coverage_rate = {
        signal: float(recent_coverage[signal] / prediction_rows)
        for signal in SENSOR_SIGNALS
    }

    assignment_rate = sensor_diag['sensor_assignment_rate']
    if assignment_rate is not None and assignment_rate < WARN_SENSOR_ASSIGNMENT_RATE:
        print(
            f'WARNING {run_id}: only {100 * assignment_rate:.2f}% of candidate '
            f'sensor rows were assigned to a processing interval.',
            flush=True,
        )

    labelled = df[TARGET_COLUMN].notna()
    report = {
        'split': split,
        'run_id': run_id,
        'rows': int(len(df)),
        'labelled_rows': int(labelled.sum()),
        'positive_rows': int((df[TARGET_COLUMN] == 1).sum()),
        'row_positive_rate': (
            float(df.loc[labelled, TARGET_COLUMN].mean()) if labelled.any() else None
        ),
        'units': int(df['unit_id'].nunique()),
        'final_inspection_station': final_station,
        'final_station_index': final_station_index,
        'feature_count': 30,
        **interval_diag,
        **sensor_diag,
        'unit_queue_observations': int(queue_observation_count),
        'sensor_history_prediction_row_coverage': sensor_history_coverage_rate,
        'sensor_recent_prediction_row_coverage': sensor_recent_coverage_rate,
    }
    return df, report


def _run_files(split: str):
    outputs = DATA_ROOT / split / 'outputs'
    if not outputs.exists():
        raise FileNotFoundError(f'Missing folder: {outputs}')
    files = sorted(outputs.glob('*.zip'))
    if not files:
        raise FileNotFoundError(f'No run ZIPs found in {outputs}')
    return files


def summarize_split(full: pd.DataFrame, split: str):
    labelled = full[TARGET_COLUMN].notna()
    print('\n' + '=' * 80)
    print(f'{split.upper()} - V5 CORRECTED FEATURES')
    print('=' * 80)
    print(f'Rows: {len(full)}')
    print(f'Labelled rows: {int(labelled.sum())}')
    print(f'Positive rows: {int((full[TARGET_COLUMN] == 1).sum())}')
    if labelled.any():
        print(
            f'Row positive rate: '
            f'{100 * full.loc[labelled, TARGET_COLUMN].mean():.3f}%'
        )
    print(f'Units: {full.unit_id.nunique()}')
    print(f'Runs: {full.run_id.nunique()}')
    print(f'Feature count: {len(DEFECT_FEATURES)}')

    sensor_columns = [
        'torque_mean_history',
        'vibration_mean_history',
        'temperature_mean_history',
        'current_mean_history',
    ]
    for col in sensor_columns:
        print(f'{col} non-null coverage: {100 * full[col].notna().mean():.2f}%')
    print(
        f'queue_history_mean non-null coverage: '
        f'{100 * full["queue_history_mean"].notna().mean():.2f}%'
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    # Safety: default and intended output is a NEW V5 folder.
    args.out.mkdir(parents=True, exist_ok=True)

    jobs = []
    for split in ['train', 'validation']:
        jobs.extend((split, p) for p in _run_files(split))

    print('=' * 90)
    print('V5 FEATURE FIX: SAME 30 FEATURES, UNIT-SPECIFIC SENSORS + QUEUES')
    print('=' * 90)
    print(f'Generating features for {len(jobs)} train/validation runs...')
    print(f'Output folder: {args.out}')
    print('TEST SPLIT WILL NOT BE ACCESSED.')

    per_split = {'train': [], 'validation': []}
    reports = []

    if args.workers <= 1:
        for split, path in jobs:
            df, rep = generate_run(str(path), split)
            per_split[split].append(df)
            reports.append(rep)
            print(rep, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {
                ex.submit(generate_run, str(path), split): (split, path)
                for split, path in jobs
            }
            for future in as_completed(futures):
                split, path = futures[future]
                df, rep = future.result()
                per_split[split].append(df)
                reports.append(rep)
                print(rep, flush=True)

    full_frames = {}
    for split, frames in per_split.items():
        full = pd.concat(frames, ignore_index=True)
        cols = META_COLUMNS + DEFECT_FEATURES + [TARGET_COLUMN]
        missing = [c for c in cols if c not in full.columns]
        if missing:
            raise RuntimeError(f'{split}: missing output columns {missing}')
        full = full[cols]

        if len(DEFECT_FEATURES) != 30:
            raise RuntimeError('Expected exactly 30 model features')
        if TARGET_COLUMN in DEFECT_FEATURES:
            raise RuntimeError('Target appears in DEFECT_FEATURES')

        out_path = args.out / f'{split}.pkl'
        full.to_pickle(out_path)
        full_frames[split] = full

        summarize_split(full, split)
        print(f'Saved: {out_path}')

    train_runs = set(full_frames['train']['run_id'].astype(str).unique())
    val_runs = set(full_frames['validation']['run_id'].astype(str).unique())
    overlap = train_runs & val_runs
    if overlap:
        raise RuntimeError(f'Train/validation run overlap detected: {sorted(overlap)}')

    report_path = args.out / 'generation_report.json'
    report_path.write_text(json.dumps(reports, indent=2))
    print(f'\nSaved generation report: {report_path}')
    print('TRAIN / VALIDATION RUN IDS ARE DISJOINT.')
    print('TEST SPLIT WAS NOT ACCESSED.')
    print('V5 FEATURE GENERATION COMPLETE.')


if __name__ == '__main__':
    main()
