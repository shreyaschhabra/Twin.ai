from pathlib import Path
import zipfile
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / 'factory_defect_prediction_v2_pack'
RESULTS_DIR = ROOT / 'results'
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_csv_from_zip(zip_path: Path, filename: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path, 'r') as zf:
        names = {Path(n).name: n for n in zf.namelist() if not n.endswith('/')}
        if filename not in names:
            raise FileNotFoundError(f'{filename} not found inside {zip_path.name}')
        with zf.open(names[filename]) as f:
            return pd.read_csv(f)


def _station_number(station_id: str) -> int:
    s = ''.join(ch for ch in str(station_id) if ch.isdigit())
    if not s:
        raise ValueError(f'Cannot parse station number from {station_id!r}')
    return int(s)


def detect_final_inspection_station(zip_path: Path) -> str:
    stations = _read_csv_from_zip(zip_path, 'stations.csv')
    if 'station_id' not in stations.columns or 'archetype' not in stations.columns:
        raise ValueError(
            f'{zip_path.name}: stations.csv must contain station_id and archetype; '
            f'found {stations.columns.tolist()}'
        )

    inspection = stations[
        stations['archetype'].astype(str).str.strip().str.upper().eq('INSPECTION')
    ].copy()
    if inspection.empty:
        raise ValueError(f'{zip_path.name}: no INSPECTION station found')

    inspection['_station_num'] = inspection['station_id'].map(_station_number)
    inspection = inspection.sort_values('_station_num')
    return str(inspection.iloc[-1]['station_id'])


def inspect_run(zip_path: Path, split: str) -> dict:
    final_station = detect_final_inspection_station(zip_path)
    inspections = _read_csv_from_zip(zip_path, 'inspection_results.csv')

    required = {'station_id', 'unit_id', 'result'}
    missing = required - set(inspections.columns)
    if missing:
        raise ValueError(f'{zip_path.name}: inspection_results.csv missing {sorted(missing)}')

    q = inspections[inspections['station_id'].astype(str).eq(final_station)].copy()
    if q.empty:
        raise ValueError(f'{zip_path.name}: no final inspection rows at {final_station}')

    # One final outcome per unit: use the last result in time if duplicates exist.
    if 'timestamp_ms' in q.columns:
        q['timestamp_ms'] = pd.to_numeric(q['timestamp_ms'], errors='coerce')
        q = q.sort_values(['unit_id', 'timestamp_ms'], kind='stable')
    q = q.groupby('unit_id', as_index=False, sort=False).tail(1)

    result = q['result'].astype(str).str.strip().str.upper()
    pass_units = int((result == 'PASS').sum())
    fail_units = int((result == 'FAIL').sum())
    total_units = pass_units + fail_units
    if total_units == 0:
        raise ValueError(f'{zip_path.name}: no PASS/FAIL labels at {final_station}')

    return {
        'split': split,
        'run_id': zip_path.stem,
        'total_units': total_units,
        'pass_units': pass_units,
        'defective_units': fail_units,
        'actual_defect_rate': fail_units / total_units,
        'actual_defect_percent': 100.0 * fail_units / total_units,
        'final_station': final_station,
    }


def main():
    rows = []
    # Intentionally exclude test. final_test.py is the first script allowed to access it.
    for split in ['train', 'validation']:
        outputs = DATA_ROOT / split / 'outputs'
        if not outputs.exists():
            raise FileNotFoundError(f'Missing folder: {outputs}')
        zips = sorted(outputs.glob('*.zip'))
        if not zips:
            raise FileNotFoundError(f'No run ZIPs found in {outputs}')

        print('\n' + '=' * 80)
        print(f'{split.upper()} RUNS')
        print('=' * 80)
        for zp in zips:
            r = inspect_run(zp, split)
            rows.append(r)
            print(
                f"{r['run_id']}: {r['defective_units']}/{r['total_units']} defects "
                f"({r['actual_defect_percent']:.2f}%) | final station = {r['final_station']}"
            )

    df = pd.DataFrame(rows)
    out = RESULTS_DIR / 'observed_defect_rates.csv'
    df.to_csv(out, index=False)

    print('\n' + '=' * 80)
    print('SUMMARY')
    print('=' * 80)
    for split in ['train', 'validation']:
        d = df[df['split'].eq(split)]
        total = int(d['total_units'].sum())
        defects = int(d['defective_units'].sum())
        print(
            f'{split.upper()}: {defects}/{total} defects '
            f'({100.0 * defects / total:.2f}%) across {len(d)} runs'
        )
    print(f'\nSaved audit to:\n{out}')
    print('\nTEST SPLIT WAS NOT ACCESSED.')


if __name__ == '__main__':
    main()
