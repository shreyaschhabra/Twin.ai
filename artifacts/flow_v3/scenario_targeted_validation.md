# Flow-v3 targeted scenario-physics validation

This was a small targeted validation at 102.5s, not a Flow pilot. Each manual/micro condition used 3 seeds; arrival conditions used 5 seeds.

A station-targeted run is positive only when an upstream station enters the observable BLOCKED state against the buffer feeding the target while the scenario is active. Arrival bursts additionally use a one-hour cohort-propagation observation window because demand compressed at line entry reaches downstream constraints later. Occupancy alone is not a positive label.

| Severity | Conditions | Negative/mostly negative | Mixed | Positive | Positive runs | Recovered positive runs |
|---|---:|---:|---:|---:|---:|---:|
| MILD | 23 | 23 | 0 | 0 | 0 | 0 |
| MODERATE | 23 | 23 | 0 | 0 | 4 | 4 |
| SEVERE | 23 | 11 | 5 | 7 | 41 | 41 |

## Per-condition results

| Mechanism | Target | Severity | Profile | Runs | Congested | Mean onset s | Mean max occupancy | Mean blocked s | Recovered positives |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| ARRIVAL_BURST | LINE | MILD | RAMP_BURST | 5 | 0 | — | 0.433 | 0.0 | 0 |
| ARRIVAL_BURST | LINE | MILD | STEP_BURST | 5 | 0 | — | 0.433 | 0.0 | 0 |
| ARRIVAL_BURST | LINE | MODERATE | RAMP_BURST | 5 | 1 | 2909.0 | 0.783 | 16.4 | 1 |
| ARRIVAL_BURST | LINE | MODERATE | STEP_BURST | 5 | 2 | 2460.2 | 0.850 | 65.4 | 2 |
| ARRIVAL_BURST | LINE | SEVERE | RAMP_BURST | 5 | 5 | 1814.3 | 1.000 | 1228.2 | 5 |
| ARRIVAL_BURST | LINE | SEVERE | STEP_BURST | 5 | 5 | 1553.8 | 1.000 | 1804.2 | 5 |
| MANUAL_VARIATION | S11 | MILD | GRADUAL | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S11 | MILD | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S11 | MILD | STEP | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S11 | MODERATE | GRADUAL | 3 | 0 | — | 0.556 | 0.0 | 0 |
| MANUAL_VARIATION | S11 | MODERATE | RECOVERING | 3 | 0 | — | 0.556 | 0.0 | 0 |
| MANUAL_VARIATION | S11 | MODERATE | STEP | 3 | 0 | — | 0.778 | 0.0 | 0 |
| MANUAL_VARIATION | S11 | SEVERE | GRADUAL | 3 | 2 | 2817.7 | 0.889 | 359.1 | 2 |
| MANUAL_VARIATION | S11 | SEVERE | RECOVERING | 3 | 2 | 2092.0 | 0.889 | 407.6 | 2 |
| MANUAL_VARIATION | S11 | SEVERE | STEP | 3 | 3 | 1879.8 | 1.000 | 797.6 | 3 |
| MANUAL_VARIATION | S21 | MILD | GRADUAL | 3 | 0 | — | 0.200 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | MILD | RECOVERING | 3 | 0 | — | 0.200 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | MILD | STEP | 3 | 0 | — | 0.200 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | MODERATE | GRADUAL | 3 | 0 | — | 0.400 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | MODERATE | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | MODERATE | STEP | 3 | 0 | — | 0.400 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | SEVERE | GRADUAL | 3 | 0 | — | 0.867 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | SEVERE | RECOVERING | 3 | 0 | — | 0.667 | 0.0 | 0 |
| MANUAL_VARIATION | S21 | SEVERE | STEP | 3 | 1 | 3562.4 | 0.867 | 29.1 | 1 |
| MANUAL_VARIATION | S24 | MILD | GRADUAL | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S24 | MILD | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S24 | MILD | STEP | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S24 | MODERATE | GRADUAL | 3 | 0 | — | 0.667 | 0.0 | 0 |
| MANUAL_VARIATION | S24 | MODERATE | RECOVERING | 3 | 0 | — | 0.778 | 0.0 | 0 |
| MANUAL_VARIATION | S24 | MODERATE | STEP | 3 | 1 | 1795.2 | 0.778 | 9.8 | 1 |
| MANUAL_VARIATION | S24 | SEVERE | GRADUAL | 3 | 1 | 3336.5 | 0.778 | 53.8 | 1 |
| MANUAL_VARIATION | S24 | SEVERE | RECOVERING | 3 | 1 | 1795.2 | 1.000 | 22.1 | 1 |
| MANUAL_VARIATION | S24 | SEVERE | STEP | 3 | 2 | 1165.4 | 1.000 | 714.3 | 2 |
| MANUAL_VARIATION | S34 | MILD | GRADUAL | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | MILD | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | MILD | STEP | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | MODERATE | GRADUAL | 3 | 0 | — | 0.444 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | MODERATE | RECOVERING | 3 | 0 | — | 0.444 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | MODERATE | STEP | 3 | 0 | — | 0.667 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | SEVERE | GRADUAL | 3 | 0 | — | 0.778 | 0.0 | 0 |
| MANUAL_VARIATION | S34 | SEVERE | RECOVERING | 3 | 1 | 1841.5 | 0.778 | 86.8 | 1 |
| MANUAL_VARIATION | S34 | SEVERE | STEP | 3 | 3 | 1828.3 | 1.000 | 409.9 | 3 |
| MANUAL_VARIATION | S38 | MILD | GRADUAL | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | MILD | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | MILD | STEP | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | MODERATE | GRADUAL | 3 | 0 | — | 0.444 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | MODERATE | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | MODERATE | STEP | 3 | 0 | — | 0.556 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | SEVERE | GRADUAL | 3 | 0 | — | 0.667 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | SEVERE | RECOVERING | 3 | 0 | — | 0.778 | 0.0 | 0 |
| MANUAL_VARIATION | S38 | SEVERE | STEP | 3 | 1 | 1685.2 | 0.889 | 27.1 | 1 |
| MICRO_STOPS | S20 | MILD | GRADUAL | 3 | 0 | — | 0.250 | 0.0 | 0 |
| MICRO_STOPS | S20 | MILD | RECOVERING | 3 | 0 | — | 0.250 | 0.0 | 0 |
| MICRO_STOPS | S20 | MILD | STEP | 3 | 0 | — | 0.250 | 0.0 | 0 |
| MICRO_STOPS | S20 | MODERATE | GRADUAL | 3 | 0 | — | 0.417 | 0.0 | 0 |
| MICRO_STOPS | S20 | MODERATE | RECOVERING | 3 | 0 | — | 0.333 | 0.0 | 0 |
| MICRO_STOPS | S20 | MODERATE | STEP | 3 | 0 | — | 0.500 | 0.0 | 0 |
| MICRO_STOPS | S20 | SEVERE | GRADUAL | 3 | 3 | 3469.3 | 1.000 | 57.2 | 3 |
| MICRO_STOPS | S20 | SEVERE | RECOVERING | 3 | 2 | 2389.5 | 1.000 | 191.2 | 2 |
| MICRO_STOPS | S20 | SEVERE | STEP | 3 | 3 | 2163.4 | 1.000 | 714.8 | 3 |
| MICRO_STOPS | S26 | MILD | GRADUAL | 3 | 0 | — | 0.250 | 0.0 | 0 |
| MICRO_STOPS | S26 | MILD | RECOVERING | 3 | 0 | — | 0.250 | 0.0 | 0 |
| MICRO_STOPS | S26 | MILD | STEP | 3 | 0 | — | 0.250 | 0.0 | 0 |
| MICRO_STOPS | S26 | MODERATE | GRADUAL | 3 | 0 | — | 0.500 | 0.0 | 0 |
| MICRO_STOPS | S26 | MODERATE | RECOVERING | 3 | 0 | — | 0.583 | 0.0 | 0 |
| MICRO_STOPS | S26 | MODERATE | STEP | 3 | 0 | — | 0.750 | 0.0 | 0 |
| MICRO_STOPS | S26 | SEVERE | GRADUAL | 3 | 1 | 3444.0 | 1.000 | 27.9 | 1 |
| MICRO_STOPS | S26 | SEVERE | RECOVERING | 3 | 2 | 2226.7 | 1.000 | 306.3 | 2 |
| MICRO_STOPS | S26 | SEVERE | STEP | 3 | 3 | 2144.2 | 1.000 | 974.8 | 3 |

## Diversity and recovery gate

- Analytic positive-capable supervised stations: S11, S20, S21, S22, S24, S26, S34 (7).
- Analytic positive-capable supervised mechanisms: ARRIVAL_BURST, MANUAL_VARIATION, MICRO_STOPS (3).
- Observed positive target stations: S11, S20, S21, S24, S26, S34, S38 (7).
- Observed positive mechanisms: ARRIVAL_BURST, MANUAL_VARIATION, MICRO_STOPS (3).
- Moderate run-level outcome: 4/73 positive across 2 mechanisms; mixed but deliberately negative-leaning.
- Largest target share of positive runs: 28.9%.
- Healthy 102.5s evidence: 13 comparison/long runs, zero blocking.
- Mild negative-condition share: 100.0%.
- Severe mixed/positive-condition share: 52.2%.

- PASS — at least 6 positive stations
- PASS — at least 3 positive mechanisms
- PASS — not one station dominated
- PASS — healthy line has no chronic congestion
- PASS — mild mostly negative
- PASS — severe often positive
- PASS — positive runs recover
- PASS — preimpact observable exists

No pilot was generated. Any failed gate must be resolved or explicitly justified before pilot authorization.
