# Flow-v3 scenario distribution audit

This audit uses the frozen 219 targeted validation definitions and seeds. No scenario parameter was changed.

## Exact positive distribution

There are exactly 45 empirically positive runs.

| First physically impacted station | Positives | Share |
|---|---:|---:|
| S11 | 17 | 37.8% |
| S20 | 8 | 17.8% |
| S26 | 6 | 13.3% |
| S24 | 5 | 11.1% |
| S34 | 4 | 8.9% |
| S22 | 3 | 6.7% |
| S21 | 1 | 2.2% |
| S38 | 1 | 2.2% |

| Mechanism | Positives | Share |
|---|---:|---:|
| MANUAL_VARIATION | 18 | 40.0% |
| MICRO_STOPS | 14 | 31.1% |
| ARRIVAL_BURST | 13 | 28.9% |

Severity distribution: {'SEVERE': 41, 'MODERATE': 4}. Profile distribution: {'STEP': 17, 'GRADUAL': 7, 'RECOVERING': 8, 'STEP_BURST': 7, 'RAMP_BURST': 6}.

## Analytic versus empirical station review

Targeted runs count direct station-targeted experiments. Arrival bursts are line-level, while empirical impact is attributed to the downstream station whose inbound buffer first caused BLOCKED.

| Station | Targeted runs | Direct positives | Empirical impacts | Analytic status | Empirical status | Positive mechanisms | Severities | Profiles | Median impact s | Median congestion s |
|---|---:|---:|---:|---|---|---|---|---|---:|---:|
| S11 | 27 | 7 | 17 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | ARRIVAL_BURST;MANUAL_VARIATION | SEVERE | GRADUAL;RAMP_BURST;RECOVERING;STEP;STEP_BURST | 1832.4 | 928.9 |
| S20 | 27 | 8 | 8 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | MICRO_STOPS | SEVERE | GRADUAL;RECOVERING;STEP | 2496.5 | 275.1 |
| S21 | 27 | 1 | 1 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | MANUAL_VARIATION | SEVERE | STEP | 3562.4 | 87.3 |
| S22 | 0 | 0 | 3 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | ARRIVAL_BURST | MODERATE | RAMP_BURST;STEP_BURST | 2590.0 | 135.5 |
| S24 | 27 | 5 | 5 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | MANUAL_VARIATION | MODERATE;SEVERE | GRADUAL;RECOVERING;STEP | 1795.2 | 161.5 |
| S26 | 27 | 6 | 6 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | MICRO_STOPS | SEVERE | GRADUAL;RECOVERING;STEP | 2542.2 | 641.0 |
| S34 | 27 | 4 | 4 | ANALYTIC_POSITIVE_CAPABLE | EMPIRICALLY_POSITIVE | MANUAL_VARIATION | SEVERE | RECOVERING;STEP | 1492.2 | 160.3 |

## Moderate-severity behavior

Moderate positives remain 4/73. Maximum buffer occupancy has min/p25/median/p75/p90/max 0.200/0.333/0.500/0.667/1.000/1.000.

- >=50% occupancy: 46/73 (63.0%)
- >=75% occupancy: 16/73 (21.9%)
- >=90% occupancy: 10/73 (13.7%)
- Minimum peak capacity headroom: -0.179 (negative means peak rho exceeds 1)
- Maximum sustained expected arrival/service deficit: 7.112 vehicles/hour
- Genuine pre-impact deterioration that recovered without blocking: 42/73 (57.5%)

The moderate set is not completely uneventful: a majority reaches at least 50% occupancy and then drains. These are valuable near-capacity hard negatives, so no physics adjustment is recommended.

## Review warnings

- WARNING — largest station share is 37.8%; S11 crosses the lower ~35% review threshold but remains below 40%.
- PASS — largest mechanism share is 40.0%, below the 60% threshold.
- PASS — moderate positives span 3 station/profile pairs, so they are not entirely concentrated in one pair.

## Decision

Scenario physics remain frozen. The S11 concentration is retained as a review warning, not treated as an automatic tuning target.
