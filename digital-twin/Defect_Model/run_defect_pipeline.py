#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_PROJECT_PATHS = [
    ROOT / "defect_main.py",
    ROOT / "saved_models" / "defect_v5_models.joblib",
    ROOT / "saved_models" / "defect_v5_config.json",
    ROOT / "saved_models" / "defect_v5_calibrator.joblib",
    ROOT / "runtime" / "defect_feature_runtime.py",
    ROOT / "runtime" / "defect_pipeline.py",
    ROOT / "ml" / "defect_model_runtime.py",
    ROOT / "ml" / "defect_explainer.py",
    ROOT / "output" / "defect_prediction_output.py",
]
REQUIRED_RUN_FILES = [
    "stations.csv", "units.csv", "station_events.csv",
    "sensor_readings.csv", "manual_checks.csv",
]

def ensure_project_ready():
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_PROJECT_PATHS if not p.is_file()]
    if missing:
        raise FileNotFoundError("Missing project files:\n  - " + "\n  - ".join(missing))

def validate_run_dir(run_dir: Path):
    missing = [n for n in REQUIRED_RUN_FILES if not (run_dir / n).is_file()]
    if missing:
        raise FileNotFoundError(f"Run folder missing files:\n  - " + "\n  - ".join(missing))

def newest_zip():
    folders = [
        ROOT / "factory_defect_prediction_v2_pack" / "validation" / "outputs",
        ROOT / "factory_defect_prediction_v2_pack" / "test" / "outputs",
        ROOT / "factory_defect_prediction_v2_pack" / "train" / "outputs",
    ]
    files = []
    for f in folders:
        if f.is_dir():
            files.extend(f.glob("*.zip"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None

def extract_run(zp: Path):
    dest = ROOT / ".runtime" / "current_run"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zp) as z:
        z.extractall(dest)
    if (dest / "stations.csv").is_file():
        return dest
    dirs = [p for p in dest.iterdir() if p.is_dir()]
    if len(dirs) == 1 and (dirs[0] / "stations.csv").is_file():
        return dirs[0]
    return dest

def summarize(path: Path):
    total = warnings = explained = 0
    max_risk = 0.0
    warned_units = set()
    with path.open() as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            total += 1
            max_risk = max(max_risk, float(r.get("defect_probability", 0)))
            if r.get("warning"):
                warnings += 1
                warned_units.add(str(r.get("unit_id")))
            if r.get("explanation_available"):
                explained += 1
    return {
        "predictions": total,
        "warning_events": warnings,
        "warned_units": len(warned_units),
        "predictions_with_shap": explained,
        "max_defect_probability": max_risk,
    }

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--run-zip", type=Path)
    g.add_argument("--run-dir", type=Path)
    ap.add_argument("--run-id")
    ap.add_argument("--explain-mode", choices=["off","warnings","all"], default="warnings")
    ap.add_argument("--shap-top-k", type=int, default=3)
    args = ap.parse_args()

    ensure_project_ready()

    if args.run_dir:
        run_dir = args.run_dir.expanduser().resolve()
        source_name = run_dir.name
    else:
        zp = args.run_zip.expanduser().resolve() if args.run_zip else newest_zip()
        if zp is None:
            raise FileNotFoundError("No existing run ZIP found. Use --run-zip or --run-dir.")
        print("Using run ZIP:", zp)
        run_dir = extract_run(zp)
        source_name = zp.stem

    validate_run_dir(run_dir)
    run_id = args.run_id or source_name

    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = results / f"defect_predictions_{stamp}.jsonl"

    cmd = [
        sys.executable, str(ROOT / "defect_main.py"), "replay",
        "--run-dir", str(run_dir),
        "--run-id", run_id,
        "--output-jsonl", str(output),
        "--explain-mode", args.explain_mode,
        "--shap-top-k", str(args.shap_top_k),
        "--print-summary",
    ]

    print("\n" + "="*80)
    print("RUNNING FINAL V5 DEFECT PIPELINE")
    print("="*80 + "\n")
    subprocess.run(cmd, cwd=ROOT, check=True)

    latest = results / "latest_defect_predictions.jsonl"
    shutil.copy2(output, latest)

    stats = summarize(output)
    stats.update({
        "run_id": run_id,
        "model_version": "v5",
        "alert_policy": "raw",
        "alert_threshold": 0.1421320160758933,
        "explain_mode": args.explain_mode,
        "shap_top_k": args.shap_top_k,
        "dark_zone_used": False,
        "status": "PASS",
        "output_file": str(output),
    })
    (results / "latest_defect_run_summary.json").write_text(json.dumps(stats, indent=2) + "\n")

    print("\n" + "="*80)
    print("PIPELINE COMPLETE")
    print("="*80)
    print("Predictions      :", stats["predictions"])
    print("Warning events   :", stats["warning_events"])
    print("Warned units     :", stats["warned_units"])
    print("SHAP explanations:", stats["predictions_with_shap"])
    print(f"Maximum risk     : {100*stats['max_defect_probability']:.2f}%")
    print("\nLatest output:")
    print(latest)
    print("\nONE-CLICK DEFECT PIPELINE PASSED")

if __name__ == "__main__":
    main()
