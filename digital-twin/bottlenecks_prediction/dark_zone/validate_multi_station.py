"""
Multi-Station Block Tracker — Synthetic Validation
========================================================
Real station 7-13 block data doesn't exist yet (pending simulation
engineer). This validates the MECHANISM against synthetic ground-truth
vehicles: we know the true per-station durations (since we generated
them), feed the filter ONLY the block-entry event exactly like the real
scenario will work, and score whether its station-identity and progress
inference matches truth.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from dark_zone_tracker import DwellDistribution
from multi_station_tracker import MultiStationParticleFilter, MultiStationConfig


def make_station_distributions(rng) -> tuple[list[str], dict[str, DwellDistribution]]:
    """7 stations, deliberately different mean/variance to make the block
    non-trivial to track — a real block would look like this (each manual
    station has its own characteristic pace, not a uniform one)."""
    station_sequence = ["S07", "S08", "S09", "S10", "S11", "S12", "S13"]
    true_params = {
        "S07": (45, 15), "S08": (60, 20), "S09": (35, 12), "S10": (70, 25),
        "S11": (50, 18), "S12": (40, 14), "S13": (55, 20),
    }  # (mean_s, std_s)

    dwell_distributions = {}
    for station, (mean, std) in true_params.items():
        shape = (mean / std) ** 2
        scale = (std ** 2) / mean
        dwell_distributions[station] = DwellDistribution(
            station=station, variant="__ALL__", dist_name="gamma",
            params=(shape, 0, scale), n_samples=999, fallback=False,
        )
    return station_sequence, dwell_distributions


def sample_true_vehicle(station_sequence, dwell_distributions, rng):
    """Ground truth: real per-station durations for one vehicle, sampled
    from the SAME distributions the filter's prior uses (clean validation
    of the mechanism itself, no model-mismatch confound)."""
    true_T = np.array([
        dwell_distributions[s].rvs(size=1, random_state=rng)[0] for s in station_sequence
    ])
    true_cum = np.cumsum(true_T)
    return true_T, true_cum


def true_station_and_progress(true_cum, true_T, station_sequence, elapsed_s):
    k = int(np.searchsorted(true_cum, elapsed_s, side="right"))
    k = min(k, len(station_sequence) - 1)
    prev_cum = 0.0 if k == 0 else true_cum[k - 1]
    progress = np.clip((elapsed_s - prev_cum) / true_T[k], 0.0, 1.0)
    return station_sequence[k], progress


# =====================================================================
# 1. SINGLE-VEHICLE TRACE — show the mechanism working, step by step
# =====================================================================
def run_single_trace(seed=1):
    rng = np.random.default_rng(seed)
    station_sequence, dwell_distributions = make_station_distributions(rng)
    true_T, true_cum = sample_true_vehicle(station_sequence, dwell_distributions, rng)
    total_true = true_cum[-1]

    print(f"Ground truth per-station durations (s): "
          f"{dict(zip(station_sequence, true_T.round(1)))}")
    print(f"True total block duration: {total_true:.1f}s\n")

    pf = MultiStationParticleFilter(station_sequence, dwell_distributions,
                                     MultiStationConfig(n_particles=3000), rng=rng)

    checkpoints = np.linspace(5, total_true - 2, 14)
    prev_t = 0.0
    for t in checkpoints:
        pf.predict(t - prev_t)
        prev_t = t
        est = pf.estimate()
        true_station, true_prog = true_station_and_progress(true_cum, true_T, station_sequence, t)
        correct = "✓" if est["most_likely_station"] == true_station else "✗"
        top_probs = sorted(est["station_probs"].items(), key=lambda x: -x[1])[:3]
        top_str = ", ".join(f"{s}:{p:.2f}" for s, p in top_probs)
        print(f"t={t:6.1f}s  true=({true_station},{true_prog:.2f})  "
              f"pred=({est['most_likely_station']},{est['progress_in_station_mean']:.2f}) {correct}  "
              f"conf={est['confidence']:.2f}  entropy_norm={est['entropy_normalized']:.2f}  "
              f"top3=[{top_str}]")


# =====================================================================
# 2. AGGREGATE BACKTEST — accuracy across many synthetic vehicles
# =====================================================================
def run_backtest(n_vehicles=200, seed=42):
    rng = np.random.default_rng(seed)
    station_sequence, dwell_distributions = make_station_distributions(rng)

    query_fractions = [0.15, 0.30, 0.50, 0.70, 0.85]
    results = {f: {"correct": 0, "total": 0, "brier_sum": 0.0, "logloss_sum": 0.0,
                    "confidences": [], "corrects": []} for f in query_fractions}

    for v in range(n_vehicles):
        true_T, true_cum = sample_true_vehicle(station_sequence, dwell_distributions, rng)
        total_true = true_cum[-1]

        pf = MultiStationParticleFilter(station_sequence, dwell_distributions,
                                         MultiStationConfig(n_particles=1500), rng=rng)
        prev_t = 0.0
        for frac in query_fractions:
            t = frac * total_true
            pf.predict(t - prev_t)
            prev_t = t
            est = pf.estimate()
            true_station, _ = true_station_and_progress(true_cum, true_T, station_sequence, t)

            r = results[frac]
            correct = (est["most_likely_station"] == true_station)
            r["correct"] += int(correct)
            r["total"] += 1
            r["confidences"].append(est["confidence"])
            r["corrects"].append(correct)

            # Multi-class Brier score: sum over all stations of (P(s) - 1{s=true})^2
            brier = sum(
                (p - (1.0 if s == true_station else 0.0)) ** 2
                for s, p in est["station_probs"].items()
            )
            r["brier_sum"] += brier

            # Log-loss on the true station's assigned probability
            p_true = max(est["station_probs"].get(true_station, 0.0), 1e-9)
            r["logloss_sum"] += -np.log(p_true)

    print(f"{'fraction':>8} {'top1_acc':>9} {'brier':>8} {'logloss':>9} {'mean_conf':>10}")
    for frac in query_fractions:
        r = results[frac]
        acc = r["correct"] / r["total"]
        brier = r["brier_sum"] / r["total"]
        logloss = r["logloss_sum"] / r["total"]
        mean_conf = np.mean(r["confidences"])
        print(f"{frac:>8.2f} {acc:>9.3f} {brier:>8.3f} {logloss:>9.3f} {mean_conf:>10.3f}")

    print("\n=== Confidence calibration (does stated confidence match real accuracy?) ===")
    all_conf = np.concatenate([results[f]["confidences"] for f in query_fractions])
    all_correct = np.concatenate([results[f]["corrects"] for f in query_fractions]).astype(float)
    bins = [0.0, 0.3, 0.5, 0.7, 0.9, 1.01]
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (all_conf >= lo) & (all_conf < hi)
        if mask.sum() > 0:
            print(f"  confidence [{lo:.1f},{hi:.1f}): n={mask.sum():4d}  "
                  f"mean_stated_conf={all_conf[mask].mean():.3f}  actual_accuracy={all_correct[mask].mean():.3f}")


# =====================================================================
# 3. VALUE-OF-ONE-CHECKPOINT — does a single mid-block checkpoint recover
#    the accuracy lost to compounding uncertainty deep in the block?
# =====================================================================
def run_checkpoint_comparison(n_vehicles=200, seed=42):
    rng = np.random.default_rng(seed)
    station_sequence, dwell_distributions = make_station_distributions(rng)
    eval_fraction = 0.85   # deep in the block, where zero-checkpoint accuracy was worst
    checkpoint_fraction = 0.45  # roughly mid-block

    no_checkpoint_correct, with_checkpoint_correct = 0, 0
    n = 0
    for v in range(n_vehicles):
        true_T, true_cum = sample_true_vehicle(station_sequence, dwell_distributions, rng)
        total_true = true_cum[-1]
        true_station, _ = true_station_and_progress(
            true_cum, true_T, station_sequence, eval_fraction * total_true
        )

        # --- no checkpoint ---
        pf_a = MultiStationParticleFilter(station_sequence, dwell_distributions,
                                           MultiStationConfig(n_particles=1500), rng=rng)
        pf_a.predict(eval_fraction * total_true)
        est_a = pf_a.estimate()
        no_checkpoint_correct += int(est_a["most_likely_station"] == true_station)

        # --- one real checkpoint at the block midpoint ---
        pf_b = MultiStationParticleFilter(station_sequence, dwell_distributions,
                                           MultiStationConfig(n_particles=1500), rng=rng)
        cp_t = checkpoint_fraction * total_true
        cp_station, cp_progress = true_station_and_progress(true_cum, true_T, station_sequence, cp_t)
        pf_b.predict(cp_t)
        pf_b.update_checkpoint(cp_station, cp_progress, sensor_std=0.05)
        pf_b.predict(eval_fraction * total_true - cp_t)
        est_b = pf_b.estimate()
        with_checkpoint_correct += int(est_b["most_likely_station"] == true_station)

        n += 1

    print(f"\n=== Value of ONE mid-block checkpoint (evaluated at {eval_fraction:.0%} through the block) ===")
    print(f"Zero checkpoints:        top-1 station accuracy = {no_checkpoint_correct/n:.3f}")
    print(f"One checkpoint at ~45%:  top-1 station accuracy = {with_checkpoint_correct/n:.3f}")


if __name__ == "__main__":
    print("=" * 70)
    print("SINGLE-VEHICLE TRACE")
    print("=" * 70)
    run_single_trace(seed=7)

    print()
    print("=" * 70)
    print(f"AGGREGATE BACKTEST")
    print("=" * 70)
    run_backtest(n_vehicles=200, seed=42)

    print()
    print("=" * 70)
    print("VALUE OF ONE MID-BLOCK CHECKPOINT")
    print("=" * 70)
    run_checkpoint_comparison(n_vehicles=200, seed=42)
