from __future__ import annotations

import argparse
from dark_zone_ml_bridge import run_feature_bridge


def main():
    ap = argparse.ArgumentParser(
        description="Run the existing Dark Zone engine and reconstruct the frozen 28 bottleneck-model features."
    )
    ap.add_argument("--stations", required=True)
    ap.add_argument("--station-events", "--events", dest="station_events", required=True)
    ap.add_argument("--units", required=True)
    ap.add_argument("--historical-dwell", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--manual-checks", default=None)
    ap.add_argument("--checkpoint-events", default=None)
    ap.add_argument("--station-checkpoints", default=None)
    ap.add_argument("--prediction-interval-s", type=float, default=60.0)
    ap.add_argument("--dwell-dist", choices=["gamma", "weibull_min"], default="gamma")
    ap.add_argument("--run-id", default="UNKNOWN")
    ap.add_argument("--config-prior-scale", type=float, default=1.0,
                    help="Explicit fallback scale for stations missing historical dwell calibration. Default 1.0; never estimated from future evaluation data.")
    ap.add_argument("--corridor-particles", type=int, default=3000)
    ap.add_argument("--corridor-residence", default=None,
                    help="Optional historical load-conditioned corridor residence calibration CSV. Strongly recommended for multi-station dark corridors.")
    a = ap.parse_args()

    ml, dash, prov, audit, quality = run_feature_bridge(
        stations_csv=a.stations,
        station_events_csv=a.station_events,
        units_csv=a.units,
        historical_dwell_csv=a.historical_dwell,
        output_dir=a.output_dir,
        manual_checks_csv=a.manual_checks,
        checkpoint_events_csv=a.checkpoint_events,
        station_checkpoints_csv=a.station_checkpoints,
        prediction_interval_s=a.prediction_interval_s,
        dwell_dist=a.dwell_dist,
        run_id=a.run_id,
        config_prior_scale=a.config_prior_scale,
        corridor_particles=a.corridor_particles,
        corridor_residence_csv=a.corridor_residence,
    )
    print(f"Rows written: {len(ml)}")
    print(f"Model-ready: {quality['ready']}")
    print(f"Evidence routed through existing orchestrator: {audit['orchestrator_evidence_events_routed']}")
    print(f"Output: {a.output_dir}/dark_zone_bottleneck_features_28.csv")


if __name__ == "__main__":
    main()
