# Flow-v3 buffer design audit

Buffer capacity is treated only as time/space available to absorb a deficit. It is never used to classify service-capacity capability.

| Buffer | Upstream | Downstream | Old | New | Rationale |
|---|---|---|---:|---:|---|
| B10 | S10 | S11 | 4 | 3 | Selected constrained manual finishing queue feeding S11; three staged bodies is plausible and no capacity deficit is inferred from this change. |
| B23 | S23 | S24 | 4 | 3 | Manual HVAC/interior-module installation has limited safe kit/body staging immediately upstream. |
| B33 | S33 | S34 | 4 | 3 | Manual electrical connection/check area has constrained staging and handling space. |
| B38 | S37 | S38 | 4 | 3 | Final manual trim/inspection uses a constrained presentation queue rather than a true accumulator. |
| B43 | S42 | S43 | 4 | 3 | The dynamic/roll-test approach is a controlled test-bay queue with limited staging. |

## Resulting heterogeneity

- Capacity 3 constrained/manual/test-bay buffers: 5
- Capacity 4 ordinary buffers: 31
- Capacity 5 accumulators/zone or branch buffers: 9
- No capacity-2 buffer is introduced because the current topology does not justify such a tight staging limit before nominal stability is established.
- B20 remains 5 and B21 remains 4; S22 is not made more dominant through artificial upstream-buffer tightening.
