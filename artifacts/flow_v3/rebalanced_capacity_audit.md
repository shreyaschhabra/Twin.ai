# Flow-v3 rebalanced capacity audit

This is a pre-pilot, physics-only review. S22 is unchanged. The proposal does not attempt to hit an exact station-count target.

## Cycle-time changes

| Station | Operation | Old s | New s | Change | rho before @100 | rho after @100 | @102.5 | @105 | Process rationale |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| S11 | Body Finishing / Manual Inspection | 65.0 | 72.0 | 10.8% | 0.650 | 0.720 | 0.702 | 0.686 | Manual weld-seam finishing includes a more complete tactile/visual confirmation; +10.8% remains within a plausible manual inspection cycle. |
| S20 | Paint Cure + Paint Inspection | 66.0 | 73.0 | 10.6% | 0.660 | 0.730 | 0.712 | 0.695 | The effective paint-cure exit service includes the in-line paint inspection and handling allowance; +10.6% preserves the effective-headway abstraction. |
| S21 | Trim Preparation | 70.0 | 75.0 | 7.1% | 0.700 | 0.750 | 0.732 | 0.714 | Trim preparation includes manual staging and verification before the constrained wiring operation; +7.1% is a modest manual-work-content correction without changing S22. |

## Resulting utilization spread

| Headway | <50% | 50–65% | 65–75% | 75–85% | 85–95% | >=95% | Max rho/station |
|---:|---:|---:|---:|---:|---:|---:|---|
| 100.0 | 27 | 11 | 3 | 3 | 1 | 0 | 0.906/S22 |
| 102.5 | 30 | 8 | 5 | 1 | 1 | 0 | 0.884/S22 |
| 105.0 | 31 | 8 | 5 | 0 | 1 | 0 | 0.863/S22 |

## Zone rationale

- Body: S11 is a modestly corrected manual finishing/inspection candidate; faster welding and dimensional stations remain comfortable.
- Paint: S20 is the credible effective-service candidate because it combines cure exit and in-line inspection; the remaining paint stations retain headroom.
- General/final assembly: S21 receives a small work-content correction. S22 is unchanged, while S24/S26/S34 already supply useful near-capacity behavior.
- Inspection/EOL: S43 remains at its original 55s. The abandoned 64s proposal did not establish an independent supervised EOL mechanism, so Inspection/EOL is documented as a healthy limitation rather than forced toward capacity.

## Pre-pilot scenario-capability interpretation at 102.5s

- Body: S11 manual variation is POSITIVE-CAPABLE. This supplies a supervised mechanism outside Final Assembly without changing fast body automation.
- Paint: S20 micro-stops are BORDERLINE at representative severe settings; degradation is POSITIVE-CAPABLE but remains the unseen holdout. Paint is not overstated as a strong supervised-positive source yet.
- General/final assembly: S21/S22/S24 manual variation are POSITIVE-CAPABLE; S26 micro-stops are BORDERLINE. S22 remains unchanged.
- Inspection/EOL: S43 is not classified as supervised POSITIVE-CAPABLE. Forcing it higher would require a less defensible cycle increase, so this zone remains a documented limitation; its degradation response is unseen-holdout evidence only.
- The legacy matrix below preserves the pre-redesign equations for traceability. The implemented temporal scenario physics is audited separately in scenario_capability_matrix_v2.csv.

Classification rule: severe rho <0.90 = INCAPABLE; 0.90–<1.00 = HARD_NEGATIVE; 1.00–<1.05 = BORDERLINE; >=1.05 = POSITIVE-CAPABLE. Non-applicable pairs are INCAPABLE. Buffer capacity is never part of this rule.

No cycle-time adjustment exceeds 20%, and no station is structurally overloaded at any finalist headway.
