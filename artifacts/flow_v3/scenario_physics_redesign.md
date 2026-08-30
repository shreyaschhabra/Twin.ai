# Flow-v3 scenario-physics redesign

This is a pre-pilot physics package. It creates no pilot partitions, labels, manifests, or ML artifacts.

## Frozen nominal basis

- Provisional headway: 102.5s.
- S22 remains unchanged.
- S43 is reverted to 55s. The proposed 64s cycle did not create an independent EOL supervised mechanism; a realistic line-entry burst encounters the upstream S22 constraint first.
- B43 remains capacity 3 as a test-bay staging decision, not as evidence of service deficit.

## Implemented supervised physics

- Manual variation: STEP, GRADUAL, and RECOVERING profiles; GRADUAL develops over the first half and then persists; station-aware multipliers; 25/40/60 minute mild/moderate/severe durations.
- Micro-stops: a processing-time Poisson process permits zero, one, or multiple interruptions per visit, with resumable work; STEP, GRADUAL, and RECOVERING profiles; 20/35/60 minute durations.
- Arrival burst: genuine demand-side headway compression with STEP_BURST and RAMP_BURST profiles; 15/25/40 minute durations; arrival variability scales with the headway so its coefficient of variation remains stable.
- Vehicle-mix overload is retained as HARD_NEGATIVE wherever actual variant work content cannot cross capacity.
- Equipment degradation is temporal but UNSEEN_ONLY and is excluded from supervised validation.

## Severity mapping

| Family | Mild | Moderate | Severe |
|---|---|---|---|
| Manual variation | station-aware peak remains safely below capacity (multiplier capped at 1.12) | peak rho target 1.02, multiplier capped at 1.45 | peak rho target 1.12, multiplier capped at 1.65 |
| Micro-stops | 0.20 stops/work-minute, U(3,9)s | 1.25 stops/work-minute, U(8,24)s | 1.80 stops/work-minute, U(10,30)s |
| Arrival burst | headway x0.90 for 15 min | headway x0.75 for 25 min | headway x0.60 for 40 min |
| Equipment degradation (unseen only) | peak cycle x1.25 for 30 min | peak cycle x1.50 for 60 min | peak cycle x1.85 for 90 min |

Manual candidates are S11, S21, S22, S24, S33, S34, and S38. Micro-stop candidates are S20 and S26. Candidate selection follows operation semantics; it is not applied to every station.

## Capability rule

Expected demand is compared with expected service capacity. Buffer capacity is reported only to estimate fill time after a positive deficit exists; it is never used to assign capability. POSITIVE_CAPABLE requires expected rho >=1.05 and peak rho >=1.0; near-breakeven cases are BORDERLINE.

The analytic matrix contains positive-capable supervised combinations for 7 stations, 3 mechanisms (ARRIVAL_BURST, MANUAL_VARIATION, MICRO_STOPS), and zones body_joining, final_assembly, paint_surface.

## Pre-impact observables

All congestion labels in targeted validation come from observable BLOCKED transitions. The pre-impact interval can contain buffer entries/occupancy growth, completed-cycle duration changes, arrival events, and rolling micro-stop count, seconds, mean duration, rate, and rate trend. Scenario identity remains latent simulator truth.
