# Regression gate

Written on 2026-11-24, together with `config/gate.yaml`, before the fixture baseline was computed and before any seeded fault was run.

## What it does
`frle gate` copies the committed 10 s fixture (`tests/fixtures/grandtour_10s`, a cut of GrandTour mission 2024-11-04-10-57-34) to a temporary data folder and runs the full pipeline on it: ingest → data quality → evaluation. It then compares the result with `config/gate_baseline.json` and exits with an error if any rule is broken. CI runs it on every push.

The pipeline is deterministic (fixed bootstrap seed), so on unchanged code and data the result equals the baseline exactly. The margins only absorb small numeric changes from library updates.

## Rules and reasons
| Rule | Reason |
|---|---|
| Every topic ingests | A reader or schema change that breaks one topic must not pass silently. |
| No QC fail, no newly failing QC check | Data problems (repeated or backward stamps, NaN, bad quaternions, new gaps, rate changes) must be caught before they reach the scores. |
| Every baseline estimator is still scored | Losing an estimator is a regression even if the others look fine. |
| APE RMSE grows by at most 0.01 m | On the fixture, DLIO's error is a few cm or less. 1 cm is large enough for library noise and small enough for real bugs in time sync, frames or lever arm, which move the prism point by centimetres or more. |
| Scored pairs drop by at most 5 % | Catches lost data or a broken association that a smaller sample would hide. |

## Seeded faults
`scripts/seeded_faults.py` applies a list of faults one at a time (to the fixture data or, through a patch, to the code), runs the gate for each, and writes `reports/seeded_faults.md`: which faults were caught and by which rule. A fault that is not caught is reported as such, not removed from the list.

## Amendments
1. 2026-11-24, after the first seeded-fault run. The first fixture (the 10 s from the first prism sample) had almost no turning (0.05 rad heading change, 1.8 m path). The gate caught 9 of 14 faults; all 5 misses were frame or lever-arm bugs (no lever arm, wrong body frame, ROS reading of the tf, quaternion order, nearest-pose association), because on a straight walk the rigid alignment absorbs a constant lever-arm offset. Change: `scripts/make_fixture.py` now picks, by a fixed rule, the 10 s window with continuous ground truth and the largest DLIO heading change (3.25 rad in this mission, starting 120 s after the first prism sample). The rules in `config/gate.yaml` and the fault list were not changed. The baseline was rebuilt on the new fixture.
