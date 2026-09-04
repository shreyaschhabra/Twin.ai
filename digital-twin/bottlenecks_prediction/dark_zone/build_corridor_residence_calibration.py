from __future__ import annotations

"""Build historical multi-station corridor *residence* calibration.

This is deliberately separate from ordinary processing-cycle calibration.
For corridor occupancy inference, a station residence interval should include
waiting/queue time as well as processing time.

Correct corridor boundary
-------------------------
For a corridor S12,S13,S14 with upstream LIGHT station S11, a vehicle enters the
DARK corridor when S11 PROCESSING_COMPLETED is observed. In the simulator this
is the causal boundary at which the vehicle reaches the S12 waiting buffer.
Therefore S12 residence is:

    upstream S11 PROCESSING_COMPLETED -> S12 PROCESSING_COMPLETED

Internal DARK stations still begin at UNIT_ARRIVED and end at
PROCESSING_COMPLETED. If no upstream station can be inferred (for example a
corridor beginning at the physical line entrance), first-station UNIT_ARRIVED is
used when available, with PROCESSING_STARTED retained only as a last-resort
historical fallback.

The output also records the number of vehicles already inside the corridor at
the vehicle's entry boundary. That load is observable causally in live use and
is used only to choose a historical prior; no future/current hidden queue value
is read by the bridge.
"""

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def infer_upstream_station(run_dir: Path, first_station: str) -> Optional[str]:
    """Infer the physical station immediately before ``first_station``.

    stations.csv row order is the same topology convention used by the runtime
    controller. Returning None is valid when the corridor begins at line start.
    """
    stations_path = run_dir / "stations.csv"
    if not stations_path.is_file():
        return None
    stations = pd.read_csv(stations_path)
    if "station_id" not in stations.columns:
        return None
    order = stations["station_id"].astype(str).str.strip().tolist()
    try:
        i = order.index(str(first_station))
    except ValueError:
        return None
    return order[i - 1] if i > 0 else None


def _first_station_entry_rows(
    ev: pd.DataFrame,
    first: str,
    upstream_station: Optional[str],
) -> tuple[pd.DataFrame, str]:
    """Return unit_id/entry_ms rows for the causal corridor boundary."""
    if upstream_station is not None:
        upstream = ev[
            ev.station_id.eq(str(upstream_station))
            & ev.event_type.eq("PROCESSING_COMPLETED")
        ][["unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "entry_ms"})
        if not upstream.empty:
            return upstream, f"{upstream_station}:PROCESSING_COMPLETED"

    # Historical fallback when no upstream topology/event is available. Arrival
    # includes waiting time and therefore remains preferable to processing start.
    arrived = ev[
        ev.station_id.eq(first) & ev.event_type.eq("UNIT_ARRIVED")
    ][["unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "entry_ms"})
    if not arrived.empty:
        return arrived, f"{first}:UNIT_ARRIVED"

    started = ev[
        ev.station_id.eq(first) & ev.event_type.eq("PROCESSING_STARTED")
    ][["unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "entry_ms"})
    return started, f"{first}:PROCESSING_STARTED_FALLBACK"


def build_one_run(
    run_dir: Path,
    sequence: list[str],
    upstream_station: Optional[str] = None,
) -> list[dict]:
    ev_path = run_dir / "station_events.csv"
    units_path = run_dir / "units.csv"
    if not ev_path.exists() or not units_path.exists():
        return []

    ev = pd.read_csv(ev_path)
    units = pd.read_csv(units_path)
    required = {"station_id", "unit_id", "timestamp_ms", "event_type"}
    missing = sorted(required - set(ev.columns))
    if missing:
        raise ValueError(f"{ev_path} missing columns: {missing}")
    if not {"unit_id", "vehicle_model"}.issubset(units.columns):
        raise ValueError(f"{units_path} must contain unit_id, vehicle_model")

    ev = ev.copy()
    ev["station_id"] = ev["station_id"].astype(str).str.strip()
    ev["unit_id"] = ev["unit_id"].astype(str)
    ev["event_type"] = ev["event_type"].astype(str).str.strip().str.upper()
    ev["timestamp_ms"] = pd.to_numeric(ev["timestamp_ms"], errors="raise").astype(np.int64)
    variants = dict(zip(units["unit_id"].astype(str), units["vehicle_model"].astype(str)))

    first, last = str(sequence[0]), str(sequence[-1])
    if upstream_station is None:
        upstream_station = infer_upstream_station(run_dir, first)

    first_entry, boundary_source = _first_station_entry_rows(ev, first, upstream_station)
    corridor_entry = first_entry.rename(columns={"entry_ms": "corridor_entry_ms"})
    corridor_exit = ev[
        ev.station_id.eq(last) & ev.event_type.eq("PROCESSING_COMPLETED")
    ][["unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "corridor_exit_ms"})

    boundaries = corridor_entry.merge(corridor_exit, on="unit_id", how="inner")
    boundaries = boundaries[
        boundaries.corridor_exit_ms > boundaries.corridor_entry_ms
    ].copy()
    if boundaries.empty:
        return []

    entry_times = np.sort(boundaries.corridor_entry_ms.to_numpy(dtype=np.int64))
    exit_times = np.sort(boundaries.corridor_exit_ms.to_numpy(dtype=np.int64))
    entry_load = {
        str(r.unit_id): int(
            np.searchsorted(entry_times, int(r.corridor_entry_ms), side="left")
            - np.searchsorted(exit_times, int(r.corridor_entry_ms), side="left")
        )
        for r in boundaries.itertuples(index=False)
    }

    rows: list[dict] = []
    for sid in map(str, sequence):
        if sid == first:
            a = first_entry.copy()
        else:
            a = ev[
                ev.station_id.eq(sid) & ev.event_type.eq("UNIT_ARRIVED")
            ][["unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "entry_ms"})

        b = ev[
            ev.station_id.eq(sid) & ev.event_type.eq("PROCESSING_COMPLETED")
        ][["unit_id", "timestamp_ms"]].rename(columns={"timestamp_ms": "exit_ms"})
        m = a.merge(b, on="unit_id", how="inner")
        m = m[(m.exit_ms > m.entry_ms) & m.unit_id.astype(str).isin(entry_load)]
        for r in m.itertuples(index=False):
            vid = str(r.unit_id)
            rows.append(
                {
                    "station_id": sid,
                    "variant": variants.get(vid, "__UNKNOWN__"),
                    "entry_ts": pd.to_datetime(
                        int(r.entry_ms), unit="ms", utc=True
                    ).isoformat(),
                    "exit_ts": pd.to_datetime(
                        int(r.exit_ms), unit="ms", utc=True
                    ).isoformat(),
                    "corridor_load": entry_load[vid],
                    "source_run": run_dir.name,
                    "corridor_first_station": first,
                    "corridor_upstream_station": upstream_station or "",
                    "boundary_source": boundary_source,
                }
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build causal historical corridor residence calibration."
    )
    ap.add_argument(
        "--historical-root",
        type=Path,
        required=True,
        help="Directory containing prior run_* folders with station_events.csv and units.csv",
    )
    ap.add_argument(
        "--sequence",
        required=True,
        help="Comma-separated corridor station sequence, e.g. S12,S13,S14,S15",
    )
    ap.add_argument(
        "--upstream-station",
        default=None,
        help="Optional LIGHT station immediately before the corridor. Inferred from stations.csv when omitted.",
    )
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--run-glob", default="run_*", help="Folder glob under historical-root; default run_*"
    )
    ap.add_argument("--summary", type=Path, default=None)
    a = ap.parse_args()

    sequence = [x.strip() for x in a.sequence.split(",") if x.strip()]
    if len(sequence) < 2:
        raise ValueError("--sequence must contain at least two stations")

    run_dirs = sorted(p for p in a.historical_root.glob(a.run_glob) if p.is_dir())
    if not run_dirs:
        raise FileNotFoundError(
            f"No historical run folders matched {a.run_glob!r} under {a.historical_root}"
        )

    rows = []
    used_runs = []
    for run_dir in run_dirs:
        part = build_one_run(run_dir, sequence, upstream_station=a.upstream_station)
        if part:
            rows.extend(part)
            used_runs.append(run_dir.name)
    if not rows:
        raise ValueError("No complete historical corridor residence intervals were found")

    out = pd.DataFrame(rows)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.output, index=False)

    summary = {
        "rows": int(len(out)),
        "runs": used_runs,
        "sequence": sequence,
        "upstream_station": a.upstream_station,
        "corridor_load_min": int(out.corridor_load.min()),
        "corridor_load_max": int(out.corridor_load.max()),
        "rows_per_station": {
            str(k): int(v) for k, v in out.station_id.value_counts().sort_index().items()
        },
        "boundary_sources": {
            str(k): int(v) for k, v in out.boundary_source.value_counts().items()
        },
        "note": "Historical calibration only. Do not include the evaluation/deployment future in this file.",
    }
    summary_path = a.summary or a.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote: {a.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
