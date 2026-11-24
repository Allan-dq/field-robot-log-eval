# Triage and failure attribution

Written on 2026-11-24, before `frle triage` was first run. Known before writing: the 42-mission summary (`reports/summary.md`) and a look at the four worst DLIO missions (QC warnings `no_jumps` with prism speeds of 190 and 286 m/s in two of them, a 70.8 m maximum error with a 0.096 m median in a third, and 23 m of prism path in the fourth). Changes after the first run go in the amendments list.

Triage does not change the evaluation. The unfiltered scores in `reports/summary.md` stay the headline; triage adds, next to them, why the bad parts are bad.

## Inputs per mission
The prism stamps that DLIO and the leg odometry both cover (the evaluation association), with:
- the APE error of each estimator at each stamp (after the evaluation's alignment);
- the step length between consecutive stamps, `|Δp|`, for the prism and for each estimator. Step lengths do not depend on the frame, so no alignment is needed for them. Over a short step, both odometries are locally accurate even when they drift over the mission.

## Events
| Event | Rule | Reason |
|---|---|---|
| `gt_jump` | the prism step is longer than both estimators' steps by more than 0.3 m + 5 % of the estimators' step, and the two estimators agree with each other within the same tolerance | LiDAR and legs/IMU are independent sensors. If both agree and the total station alone moves, the total station is wrong (lost lock, reflection). Works across gaps too, where a speed check does not see a jump. |
| `est_jump` (per estimator) | the estimator's step differs from the prism step by more than the tolerance, and the prism and the other estimator agree | Localization jump or reset in that estimator. |
| `est_data` (per estimator) | the estimator's own topic has a data-quality event in the segment: a gap or a step faster than 3 m/s (the QC rules) | Missing or broken input to the estimate rather than a wrong estimate. |
| `weak_alignment` (per mission) | the prism path in the scored stamps is shorter than 50 m | The rigid alignment is poorly constrained over a short path, so the APE says more about the alignment than about the estimator. |

The tolerance 0.3 m + 5 % is far above the per-step noise (prism steps are about 5 cm at 20 Hz) and leaves room for leg-odometry drift across long gaps.

## Bad segments and attribution
- A pair is **bad** for an estimator when its APE error is above max(0.10 m, 5 × that estimator's median error in the mission). Bad pairs closer than 1 s are merged into one segment.
- Each segment gets one cause, checked in this order:
  1. `ground_truth` if a `gt_jump` event lies in the segment or within 1 s of its ends;
  2. `estimate_data` if the estimator has an `est_data` event in it;
  3. `estimator_jump` if the estimator has an `est_jump` event in it;
  4. `drift` otherwise (the estimate is wrong without a visible jump).
- Missions with `weak_alignment` are flagged as a whole; their segments keep their causes.

## Reported
- Per mission and estimator: the bad segments with start time, duration, number of pairs, maximum error and cause.
- Counts of segments and of bad pairs per cause, per estimator, across missions.
- Next to the unfiltered RMSE, an RMSE with the `ground_truth` pairs removed (per mission and the median across missions). This is a diagnostic, not a replacement score.
- An error-over-time plot, with events marked, for every mission where DLIO has a bad segment.

## Amendments
1. 2026-11-24, after the first run. A jump event now marks both stamps of the jump step, not only the later one. Reason: in mission 2024-11-11-12-07-40 the first scored prism sample is 70.8 m off (a single bad sample that makes DLIO's RMSE 1.22 m). The jump was detected on the step to the next sample, but that sample comes after a gap of about 20 s, so the event was outside the 1 s margin and the segment was labelled `drift`. Either stamp of a jump step can be the wrong one, so both are marked. Thresholds unchanged.
