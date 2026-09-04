# Runtime parity status

The runtime draft was checked against the finalized offline V5 feature generator.

The audit caught one runtime-only mismatch before deployment:
`queue_history_mean` / `queue_history_std` were initially collecting
`queue_length_after` from every station event. The V5 training generator uses
queue observations only from `UNIT_ARRIVED`.

That runtime-only issue is fixed in this V2 bundle.

After the fix, replay of validation run
`validation_001_intermittent_late_4p0pct` produced:

- offline rows: 14,214
- runtime rows: 14,214
- key alignment mismatches: 0
- mismatches across all 30 features: 0
- maximum numeric feature absolute difference: 0.0
- probability mismatches: 0
- maximum probability absolute difference: 0.0

The trained V5 model itself was not changed.
