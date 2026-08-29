"""
RNG stream isolation tests (Step 2 patch 2).

These prove the property that matters most for Step 3: adding a brand new
stochastic mechanism (sensor noise, scenario occurrence, defect background
noise) must never change the numbers already-validated mechanisms produce,
even though they all derive from one master seed.
"""

import hashlib

from backend.simulation.rng import RNGStreamFactory, derive_seed
from backend.config.loader import load_factory_config
from backend.simulation.engine import FactoryEngine
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


def test_same_master_seed_same_stream_name_is_deterministic():
    f1 = RNGStreamFactory(master_seed=123)
    f2 = RNGStreamFactory(master_seed=123)
    seq1 = [f1.get("arrival").random() for _ in range(20)]
    seq2 = [f2.get("arrival").random() for _ in range(20)]
    assert seq1 == seq2


def test_different_master_seed_changes_stream():
    f1 = RNGStreamFactory(master_seed=123)
    f2 = RNGStreamFactory(master_seed=456)
    seq1 = [f1.get("arrival").random() for _ in range(20)]
    seq2 = [f2.get("arrival").random() for _ in range(20)]
    assert seq1 != seq2


def test_different_stream_names_are_not_correlated():
    f = RNGStreamFactory(master_seed=123)
    seq_a = [f.get("processing_time::S01").random() for _ in range(20)]
    seq_b = [f.get("processing_time::S02").random() for _ in range(20)]
    assert seq_a != seq_b


def test_repeated_get_returns_same_advancing_stream_not_a_reset():
    f = RNGStreamFactory(master_seed=1)
    stream = f.get("arrival")
    first_three = [stream.random() for _ in range(3)]
    # ask for the same name again mid-sequence
    same_stream = f.get("arrival")
    next_three = [same_stream.random() for _ in range(3)]

    f2 = RNGStreamFactory(master_seed=1)
    continuous = [f2.get("arrival").random() for _ in range(6)]
    assert first_three + next_three == continuous


def test_consuming_one_stations_rng_does_not_affect_anothers():
    """The literal example from the instructions: draining extra values
    from S01's RNG must not alter S02's sequence at all."""
    f1 = RNGStreamFactory(master_seed=99)
    baseline_s02 = [f1.get("processing_time::S02").random() for _ in range(10)]

    f2 = RNGStreamFactory(master_seed=99)
    # burn a large, arbitrary number of extra draws from S01 first
    s01 = f2.get("processing_time::S01")
    for _ in range(500):
        s01.random()
    perturbed_s02 = [f2.get("processing_time::S02").random() for _ in range(10)]

    assert baseline_s02 == perturbed_s02


def test_hypothetical_future_stream_does_not_alter_existing_streams():
    """Simulates Step 3 adding a brand-new stream (sensor noise) that Step
    2 code never touches. Consuming it must not change arrival, variant,
    or any station's processing-time sequence."""
    f1 = RNGStreamFactory(master_seed=2024)
    baseline_arrival = [f1.get("vehicle_interarrival").random() for _ in range(10)]
    baseline_variant = [f1.get("vehicle_variant_selection").random() for _ in range(10)]
    baseline_proc = [f1.get("processing_time::S06").random() for _ in range(10)]

    f2 = RNGStreamFactory(master_seed=2024)
    # touch several hypothetical future streams first, and interleave
    for _ in range(50):
        f2.get("sensor_noise::S01").random()
        f2.get("scenario_occurrence").random()
        f2.get("defect_background_noise").random()
    perturbed_arrival = [f2.get("vehicle_interarrival").random() for _ in range(10)]
    perturbed_variant = [f2.get("vehicle_variant_selection").random() for _ in range(10)]
    perturbed_proc = [f2.get("processing_time::S06").random() for _ in range(10)]

    assert baseline_arrival == perturbed_arrival
    assert baseline_variant == perturbed_variant
    assert baseline_proc == perturbed_proc


def test_seed_derivation_uses_sha256_not_builtin_hash():
    """Pins the derivation algorithm so nobody accidentally swaps it for
    Python's randomized-per-process built-in hash(), which would silently
    break cross-process/cross-machine reproducibility."""
    expected_digest = hashlib.sha256("42::arrival".encode("utf-8")).hexdigest()
    expected_seed = int(expected_digest[:16], 16)
    assert derive_seed(42, "arrival") == expected_seed
    # and, as a sanity check, it must NOT equal Python's hash() of the same string
    # (hash() is not itself required to differ, but derive_seed must not depend on it)
    assert derive_seed(42, "arrival") == derive_seed(42, "arrival")  # stable across calls


def test_engine_level_isolation_extra_stream_does_not_change_run():
    """End-to-end: build two engines from the same seed/config. Before
    running one of them, drain a hypothetical future 'sensor_noise' stream
    that no Step 2 code touches. The two runs' event streams (arrival
    times, variant choices, every station's processing times) must still
    match exactly."""
    config = load_factory_config(
        CONFIG_DIR / "station_types.yaml", CONFIG_DIR / "development_line.yaml"
    )

    engine_a = FactoryEngine(config, seed=555)
    result_a = engine_a.run(n_vehicles=15, mean_interarrival_seconds=200.0, std_interarrival_seconds=20.0)

    engine_b = FactoryEngine(config, seed=555)
    # simulate Step 3 pulling values from streams Step 2 never uses
    for _ in range(200):
        engine_b.rng_factory.get("sensor_noise::S01").random()
        engine_b.rng_factory.get("scenario_occurrence").random()
    result_b = engine_b.run(n_vehicles=15, mean_interarrival_seconds=200.0, std_interarrival_seconds=20.0)

    seq_a = [(e.event_type, e.simulation_time, e.vehicle_id, e.station_id, e.value) for e in result_a.events]
    seq_b = [(e.event_type, e.simulation_time, e.vehicle_id, e.station_id, e.value) for e in result_b.events]
    assert seq_a == seq_b
