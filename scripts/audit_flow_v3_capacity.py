"""Generate the Phase-A Flow-v3 physical operating-point audit."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config.loader import load_factory_config
from backend.flow_v3.capacity_audit import (
    DEFAULT_MEAN_INTERARRIVAL_SECONDS,
    build_capacity_audit,
    summarize_utilization,
    write_capacity_audit,
)


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headway", type=float, default=DEFAULT_MEAN_INTERARRIVAL_SECONDS)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "flow_v3")
    args = parser.parse_args()

    config = load_factory_config(ROOT / "configs" / "station_types.yaml", ROOT / "configs" / "full_line.yaml")
    rows = build_capacity_audit(config, mean_interarrival_seconds=args.headway)
    csv_path, markdown_path = write_capacity_audit(
        rows,
        args.output_dir,
        starting_commit=_git_commit(),
        mean_interarrival_seconds=args.headway,
    )
    print(f"Wrote {len(rows)} station records to {csv_path}")
    print(f"Wrote summary to {markdown_path}")
    for band in summarize_utilization(rows):
        print(f"{band['band']:>7}: {band['station_count']:2d} stations ({band['percentage']:.1f}%)")


if __name__ == "__main__":
    main()
