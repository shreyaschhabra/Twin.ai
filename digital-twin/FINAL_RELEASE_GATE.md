# Final Release Reliability Gate

**Release status:** FINAL PROTOTYPE / REVIEW CANDIDATE  
**Validation date:** 2026-08-30  
**Primary objective of this gate:** prevent runtime/integration failure during a company prototype review. Prediction quality is reported separately and is not treated as a release blocker.

## Executive verdict

The packaged project passed the final reliability gate. Both prediction subsystems run together from one causal public event bus, LIGHT and DARK routing execute, model outputs remain valid, SHAP reconstruction remains numerically consistent, protected production model assets remain unchanged, and malformed input is rejected safely instead of corrupting runtime state.

The known weak area remains DARK-zone **defect accuracy**. This is an accepted prototype limitation; it is not a runtime-stability failure.

## Final checks

- ZIP integrity: PASS.
- Python compile/import scan: PASS.
- Permanent regression suite: **69/69 PASS**.
- Protected XGBoost/CatBoost artifact SHA-256 checks: PASS.
- CLI parser/help smoke tests: PASS.
- Fresh C++ simulator-core run from current source: PASS.
- Fresh 45-minute simulation: **25,314 public records** generated successfully.
- Fresh bounded 10-minute review simulation: **5,217 public records**.
- Root dual-consumer prescribed replay on the fresh 10-minute run at **3000 DARK particles**: PASS.
- Bottleneck output: **258 predictions** = 252 LIGHT + 6 DARK_CORRIDOR.
- Defect output: **94 predictions** = 90 LIGHT + 4 DARK_INFERRED.
- Root coordinator lifecycle: bottleneck return code 0; defect return code 0; `overall_status=PASS`.
- Same run ID / same simulator clock synchronization: PASS.
- Bottleneck SHAP: 258 explanations; maximum additivity error `2.2877222283224086e-07`.
- Defect warning SHAP: maximum reconstruction error `1.942890293094024e-16`.
- JSONL parse integrity: PASS; no malformed output rows.
- Prediction timestamps monotonic: PASS.
- Probability range `[0,1]`: PASS.
- Inspection leakage into defect inference: NONE.
- Current-run bottleneck calibration leakage: NONE.
- Re-run protection: existing output is refused with an actionable `--force` message.
- Forced re-run: PASS.
- Missing run directory/files: rejected with explicit missing-file diagnostics.
- Deliberately out-of-order runtime bus: rejected immediately with timestamp regression diagnostic.
- Previous sparse-DARK stress validation: retrospective DARK transitions are recovered without moving the causal feature clock backward.

## Reviewer-safe demo

A compact validated completed run is included at:

`simulation/demo_run/`

After installing Python requirements, a reviewer can exercise the full dual ML runtime without compiling the simulator:

```text
python cli.py system run prescribed --run-dir simulation/demo_run --output-dir runtime_output/reviewer_demo --run-id REVIEWER_DEMO --particles 3000 --explain-mode warnings
```

On Windows, use `py cli.py ...` if `python` is not the configured launcher.

Expected high-level outcome: both consumers return code 0 and `system_health.json` reports `overall_status: PASS`.

## Accepted prototype limitations

1. **DARK defect accuracy is weak.** The DARK defect path can remain under-confident and may miss true defects. This is accepted for this prototype release; the runtime itself remains operational.
2. **Initial simulator CMake build has an external dependency.** `simulation/CMakeLists.txt` currently obtains `nlohmann/json` through CMake `FetchContent`. A completely offline machine without that dependency already present cannot perform the initial generic simulator build. The packaged reviewer demo avoids this dependency because it is a completed simulator run and exercises the entire Python dual-runtime path directly.
3. No finite test suite can guarantee failure is impossible on every machine/input. The release gate establishes that the shipped package is internally consistent and survives the tested normal, DARK, repeated-run, and malformed-input cases.

## Release decision

**APPROVED AS FINAL PROTOTYPE / COMPANY REVIEW CANDIDATE.**

Do not make further model or runtime changes unless a new requirement is introduced. If accuracy enhancement is resumed later, treat DARK defect modeling as a separate V2 improvement rather than modifying this validated release.
