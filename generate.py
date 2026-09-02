from __future__ import annotations

import argparse
import functools
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path

from config import load_factory_config
from historical import (
    BOTTLENECK_CAPABLE_FAMILIES,
    DEGRADATION_OPPORTUNITY_COUNT,
    DEFAULT_STD_INTERARRIVAL_SECONDS,
    DEFAULT_VEHICLES_PER_SHIFT,
    FLOW_OPPORTUNITY_RANGE,
    MICRO_STOPS_CALIBRATION,
    REJECTED_CANDIDATES,
    SEVERITY_STRATA,
    STATION_CANDIDATES,
    build_flow_enrichment_plan,
    build_shift_schedule_enriched,
    generate_and_write_dataset_streaming,
    plan_by_shift,
    save_plan,
)
from models import QCParameters, load_batch_relevant_stations, load_sensor_models

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / 'factory.yaml'
GENERATOR_VERSION = 'step4-v1-minimal-structure'


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _git_state(repo_root: Path):
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_root, stderr=subprocess.DEVNULL).decode().strip()
        status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo_root, stderr=subprocess.DEVNULL).decode()
        dirty_files = [line[3:] for line in status.splitlines() if line.strip()]
        return commit, bool(dirty_files), dirty_files, True
    except Exception:
        return 'unknown', False, [], False


def main():
    parser = argparse.ArgumentParser(description='Generate DigitalTwin.ai synthetic production data.')
    parser.add_argument('--mode', choices=['standard', 'calibrated'], default='standard')
    parser.add_argument('--shifts', type=int, default=100)
    parser.add_argument('--vehicles', type=int, default=DEFAULT_VEHICLES_PER_SHIFT)
    parser.add_argument('--seed', type=int, default=20240002)
    parser.add_argument('--batch-size', type=int, default=10)
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--allow-dirty', action='store_true')
    args = parser.parse_args()

    if args.shifts < 1 or args.vehicles < 1 or args.batch_size < 1:
        parser.error('--shifts, --vehicles and --batch-size must be >= 1')
    if args.mode == 'calibrated' and args.shifts != 100:
        parser.error('calibrated mode uses the locked 70/15/15 plan and therefore requires --shifts 100')

    commit, is_dirty, dirty_files, git_available = _git_state(ROOT)
    if git_available and is_dirty and not args.allow_dirty:
        print('REFUSING to generate a frozen dataset from a dirty working tree.')
        for f in dirty_files:
            print(f'  {f}')
        print('\nCommit first, or pass --allow-dirty.')
        raise SystemExit(1)

    config = load_factory_config(CONFIG_PATH)
    sensor_models = load_sensor_models(CONFIG_PATH)
    batch_relevant_stations = load_batch_relevant_stations(CONFIG_PATH)
    qc_params = QCParameters()

    default_name = 'historical_100' if args.mode == 'standard' else 'historical_100_flow_calibrated'
    out_base = args.output or (ROOT / 'data' / 'generated' / default_name)
    observable_dir = out_base / 'observable'
    latent_dir = out_base / 'latent'

    schedule_fn = None
    plan_summary = None
    schedule_plan_path = None
    if args.mode == 'calibrated':
        plan = build_flow_enrichment_plan(args.seed, n_shifts=args.shifts)
        schedule_plan_path = out_base / 'flow_calibrated_schedule.json'
        save_plan(plan, schedule_plan_path)
        by_shift = plan_by_shift(plan)
        schedule_fn = functools.partial(build_shift_schedule_enriched, plan_by_shift=by_shift)
        known = [o for o in plan if o.kind == 'known_flow_enrichment']
        degradation = [o for o in plan if o.kind == 'unseen_degradation_opportunity']
        plan_summary = {
            'total_known_flow_opportunities': len(known),
            'total_degradation_opportunities': len(degradation),
            'known_by_partition': dict(Counter(o.partition for o in known)),
            'known_by_family': dict(Counter(o.family for o in known)),
            'known_by_severity_stratum': dict(Counter(o.severity_stratum for o in known)),
            'known_by_bottleneck_capable': {str(k): v for k, v in Counter(o.expected_bottleneck_capable for o in known).items()},
            'known_station_usage': dict(Counter(o.station_id for o in known if o.station_id)),
            'degradation_by_partition': dict(Counter(o.partition for o in degradation)),
            'degradation_station_usage': dict(Counter(o.station_id for o in degradation)),
        }

    kwargs = dict(
        n_shifts=args.shifts,
        dataset_master_seed=args.seed,
        observable_dir=observable_dir,
        latent_dir=latent_dir,
        vehicles_per_shift=args.vehicles,
        qc_params=qc_params,
        batch_size=args.batch_size,
    )
    if schedule_fn is not None:
        kwargs['schedule_fn'] = schedule_fn

    t0 = time.time()
    shift_metadata, stats = generate_and_write_dataset_streaming(
        config, sensor_models, batch_relevant_stations, **kwargs
    )
    generation_seconds = time.time() - t0

    import pandas as pd
    qc_df = pd.read_parquet(observable_dir / 'qc_results.parquet')
    defect_rate = float((qc_df.qc_result == 'DEFECT').mean())
    n_abnormal = sum(1 for m in shift_metadata if m['is_abnormal'])

    manifest = {
        'mode': args.mode,
        'generator_version': GENERATOR_VERSION,
        'git_commit': commit,
        'git_dirty': is_dirty if git_available else None,
        'git_dirty_files': dirty_files if is_dirty else [],
        'dataset_master_seed': args.seed,
        'n_shifts': args.shifts,
        'vehicles_per_shift': args.vehicles,
        'total_vehicles': len(qc_df),
        'n_abnormal_shifts': n_abnormal,
        'shift_seeds': {m['shift_id']: m['shift_seed'] for m in shift_metadata},
        'mean_interarrival_seconds': config.production_plan.nominal_interarrival_seconds,
        'std_interarrival_seconds': DEFAULT_STD_INTERARRIVAL_SECONDS,
        'variant_mix': dict(config.production_plan.baseline_variant_mix),
        'qc_parameters': qc_params.__dict__,
        'config_hash': _file_hash(CONFIG_PATH),
        'factory_config_hash': config.factory_config_hash,
        'overall_defect_rate': defect_rate,
        'generation_seconds': generation_seconds,
        'output_stats': stats,
    }
    if args.mode == 'calibrated':
        manifest.update({
            'station_candidates': {sid: info['family'].value for sid, info in STATION_CANDIDATES.items()},
            'rejected_candidates': REJECTED_CANDIDATES,
            'micro_stops_calibration': MICRO_STOPS_CALIBRATION,
            'bottleneck_capable_families': [f.value for f in BOTTLENECK_CAPABLE_FAMILIES],
            'severity_strata': SEVERITY_STRATA,
            'flow_opportunity_range': FLOW_OPPORTUNITY_RANGE,
            'degradation_opportunity_count': DEGRADATION_OPPORTUNITY_COUNT,
            'schedule_plan_path': str(schedule_plan_path),
            'schedule_plan_hash': _file_hash(schedule_plan_path),
            'schedule_plan_summary': plan_summary,
        })

    out_base.mkdir(parents=True, exist_ok=True)
    manifest_path = out_base / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f'Generated {args.shifts} shifts, {len(qc_df)} vehicles in {generation_seconds:.1f}s')
    print(f'Mode: {args.mode}')
    print(f'Output: {out_base}')
    print(f'Abnormal shifts: {n_abnormal}/{args.shifts}')
    print(f'Overall defect rate: {defect_rate*100:.3f}%')
    print(f'Manifest: {manifest_path}')


if __name__ == '__main__':
    main()
