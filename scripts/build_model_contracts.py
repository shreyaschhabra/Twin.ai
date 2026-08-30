"""Consolidated model contracts (Section 32): one file recording everything
needed to detect a stale/incompatible deployment for both Flow-v3 and
Quality. Reads the artifacts each training script already saved and adds
config/dataset/feature hashes -- does not retrain anything.

Usage:
    python scripts/build_model_contracts.py
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "artifacts" / "final_submission"


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def _hash_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        if path.exists():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def build_flow_v3_contract() -> dict:
    artifact_dir = ROOT / "artifacts" / "flow_v3"
    with (artifact_dir / "flow_v3_model_contract.json").open() as f:
        contract = json.load(f)
    operational_path = artifact_dir / "flow_v3_operational_evaluation.json"
    operational = json.loads(operational_path.read_text()) if operational_path.exists() else None

    contract["factory_config_hash"] = _hash_files([
        ROOT / "configs" / "station_types.yaml", ROOT / "configs" / "full_line.yaml",
        ROOT / "configs" / "flow_v3_rebalance.yaml",
    ])
    contract["dataset_manifest_hash"] = _hash_file(ROOT / "data" / "processed" / "flow_v3" / "run_manifest.csv")
    contract["feature_manifest_hash"] = _hash_file(artifact_dir / "feature_selection_report.json")
    if operational is not None:
        contract["actionable_warning_policy"] = {
            "threshold_crossed_ratio": operational["frozen_ratio_threshold"],
            "definition": "predicted_service_rate_vph / baseline_service_rate_vph < threshold",
            "actionable_warning_requires": "threshold_crossed AND NOT already inside an active congestion regime",
            "selected_on": "validation only; test read once",
        }
        contract["operational_metrics"] = operational["test"]
    return contract


def build_quality_contract() -> dict:
    artifact_dir = ROOT / "artifacts" / "quality"
    with (artifact_dir / "training_metadata.json").open() as f:
        meta = json.load(f)
    with (artifact_dir / "feature_list.json").open() as f:
        feature_list = json.load(f)
    with (artifact_dir / "threshold.json").open() as f:
        threshold = json.load(f)
    quality_metrics_path = OUT_DIR / "quality_metrics.json"
    revalidation = json.loads(quality_metrics_path.read_text()) if quality_metrics_path.exists() else None

    return {
        "model_id": "quality_lightgbm_v1",
        "git_commit": meta.get("code_commit"),
        "current_git_commit": git_commit(),
        "factory_config_hash": _hash_files([ROOT / "configs" / "station_types.yaml", ROOT / "configs" / "full_line.yaml"]),
        "dataset_manifest_hash": _hash_file(ROOT / "data" / "processed" / "quality_v1" / "dataset_manifest.json"),
        "feature_manifest_hash": _hash_file(ROOT / "data" / "processed" / "quality_v1" / "feature_manifest.json"),
        "feature_order": feature_list["numeric_features"] + feature_list["categorical_features"],
        "categorical_features": feature_list["categorical_features"],
        "categorical_levels": feature_list["categorical_levels"],
        "target": "target (defect at final QC, Dataset A naturalistic corpus)",
        "split_definition": meta["split_definition"],
        "params": meta["hyperparameters"],
        "scale_pos_weight": meta["scale_pos_weight"],
        "threshold_policy": threshold,
        "metrics": {"validation": meta["validation_metrics"], "test": meta["test_metrics"]},
        "early_detection": meta.get("early_detection"),
        "revalidation_summary": (
            None if revalidation is None else {
                "per_checkpoint_metrics": revalidation["per_checkpoint_metrics"],
                "cohort_ablation": revalidation["cohort_ablation"],
                "production_weighting": revalidation["production_weighting"],
            }
        ),
        "known_limitations": meta.get("known_limitations"),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contracts = {
        "flow_v3": build_flow_v3_contract(),
        "quality": build_quality_contract(),
        "current_git_commit": git_commit(),
        "generated_at": __import__("pandas").Timestamp.now(tz="UTC").isoformat(),
    }
    with (OUT_DIR / "model_contracts.json").open("w") as f:
        json.dump(contracts, f, indent=2, default=str)
    print(f"Saved {OUT_DIR / 'model_contracts.json'}")


if __name__ == "__main__":
    main()
