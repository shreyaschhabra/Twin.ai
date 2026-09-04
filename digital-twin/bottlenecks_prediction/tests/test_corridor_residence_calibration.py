from __future__ import annotations

from pathlib import Path
import sys

# Dark Zone modules intentionally retain their legacy flat-import layout.
# Match the production main.py/runtime shim so this test also passes in a
# completely clean pytest process.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dark_zone"))

import pandas as pd

from dark_zone.build_corridor_residence_calibration import build_one_run


def test_first_corridor_station_residence_starts_at_upstream_completion(tmp_path: Path) -> None:
    run_dir = tmp_path / "run_001"
    run_dir.mkdir()

    pd.DataFrame([
        {"station_id": "S02"},
        {"station_id": "S03"},
        {"station_id": "S04"},
        {"station_id": "S05"},
    ]).to_csv(run_dir / "stations.csv", index=False)
    pd.DataFrame([
        {"unit_id": "U1", "vehicle_model": "A"},
    ]).to_csv(run_dir / "units.csv", index=False)
    pd.DataFrame([
        {"station_id": "S02", "unit_id": "U1", "timestamp_ms": 1_000, "event_type": "PROCESSING_COMPLETED"},
        {"station_id": "S03", "unit_id": "U1", "timestamp_ms": 1_000, "event_type": "UNIT_ARRIVED"},
        {"station_id": "S03", "unit_id": "U1", "timestamp_ms": 5_000, "event_type": "PROCESSING_STARTED"},
        {"station_id": "S03", "unit_id": "U1", "timestamp_ms": 15_000, "event_type": "PROCESSING_COMPLETED"},
        {"station_id": "S04", "unit_id": "U1", "timestamp_ms": 15_000, "event_type": "UNIT_ARRIVED"},
        {"station_id": "S04", "unit_id": "U1", "timestamp_ms": 25_000, "event_type": "PROCESSING_COMPLETED"},
    ]).to_csv(run_dir / "station_events.csv", index=False)

    rows = build_one_run(run_dir, ["S03", "S04"])
    first = next(r for r in rows if r["station_id"] == "S03")

    assert first["boundary_source"] == "S02:PROCESSING_COMPLETED"
    assert pd.Timestamp(first["entry_ts"]) == pd.Timestamp(1_000, unit="ms", tz="UTC")
    assert pd.Timestamp(first["exit_ts"]) == pd.Timestamp(15_000, unit="ms", tz="UTC")


def test_first_station_residence_fit_preserves_fast_and_queued_modes(tmp_path: Path) -> None:
    """Valid short first-station residence is not trimmed as an outlier.

    A congested first DARK station can legitimately contain a minority of
    pass-through vehicles and a majority of queued vehicles. The calibration
    must preserve both regimes or queue occupancy is biased upward.
    """
    from dark_zone.dark_zone_ml_bridge import load_corridor_residence_models

    rows = []
    # Eight legitimate no-wait observations around 40 s.
    durations = [38, 39, 40, 41, 42, 39, 40, 41]
    # Thirty-two legitimate queued observations around 700 s. Small spread keeps
    # MAD non-zero, so the old generic outlier trim would delete the fast mode.
    durations += [680 + (i % 9) * 5 for i in range(32)]
    for i, duration_s in enumerate(durations):
        entry = pd.Timestamp("2026-01-01T00:00:00Z") + pd.Timedelta(seconds=i * 1000)
        rows.append({
            "station_id": "S12",
            "variant": "A",
            "entry_ts": entry.isoformat(),
            "exit_ts": (entry + pd.Timedelta(seconds=duration_s)).isoformat(),
            "corridor_load": 12,
            "corridor_first_station": "S12",
        })

    path = tmp_path / "corridor_residence.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    bundle = load_corridor_residence_models(str(path))
    model = bundle["conditional"][("S12", "__ALL__", "load_11_plus")]

    raw_mean = float(pd.Series(durations).mean())
    # Gamma MLE with loc fixed to zero preserves the sample mean. This would be
    # near ~700 s if the short physical mode had been incorrectly trimmed away.
    assert abs(model.mean() - raw_mean) < 1.0
    assert model.n_samples == len(durations)

def test_first_corridor_station_uses_local_observable_load_not_broad_11_plus(tmp_path: Path) -> None:
    """High corridor loads must not all collapse into one first-station prior.

    This deliberately uses a non-S12 station ID to prove the behaviour is role-
    based (first station of the corridor), not hard-coded to a specific station.
    """
    from dark_zone.dark_zone_ml_bridge import (
        _corridor_residence_for,
        load_corridor_residence_models,
    )

    base = pd.Timestamp("2026-01-01T00:00:00Z")
    rows = []
    # Moderate corridor load: short first-station residence.
    for i in range(30):
        entry = base + pd.Timedelta(minutes=i)
        rows.append({
            "station_id": "S77",
            "variant": "A",
            "entry_ts": entry,
            "exit_ts": entry + pd.Timedelta(seconds=120 + (i % 3)),
            "corridor_load": 11,
            "corridor_first_station": "S77",
        })
    # Heavy corridor load: much longer residence, and deliberately more rows so
    # the old load_11_plus bucket would have been dominated by this regime.
    for i in range(90):
        entry = base + pd.Timedelta(hours=2, minutes=i)
        rows.append({
            "station_id": "S77",
            "variant": "A",
            "entry_ts": entry,
            "exit_ts": entry + pd.Timedelta(seconds=700 + (i % 5)),
            "corridor_load": 23,
            "corridor_first_station": "S77",
        })

    path = tmp_path / "corridor.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    bundle = load_corridor_residence_models(str(path))

    moderate, _, source_m = _corridor_residence_for(
        bundle, "S77", "A", 11, {}, is_first_station=True
    )
    heavy, _, source_h = _corridor_residence_for(
        bundle, "S77", "A", 23, {}, is_first_station=True
    )

    assert moderate is not None and heavy is not None
    assert moderate.mean() < 200.0
    assert heavy.mean() > 600.0
    assert heavy.mean() - moderate.mean() > 400.0
    assert source_m.startswith("first_station_local_load:")
    assert source_h.startswith("first_station_local_load:")

