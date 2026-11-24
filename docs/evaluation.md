# Evaluation protocol

Written on 2026-11-24, before `frle eval` was first run. Later changes go in the amendments list, with a date and a reason.

Disclosure: while working out the frames (same day), a scratch script fitted a lever arm per estimator together with the alignment and printed the residuals (about 0.07 m for CPT7, 0.02 m for DLIO, 0.4 m for the leg odometry). The protocol below does not fit anything to the scores except the standard rigid alignment.

## What is scored
- **Reference:** `prism_position`, the Leica MS60 total station tracking a prism on the robot. Position only, in the total-station frame. Gaps (lost line of sight) are left out, never filled.
- **Estimates:** `dlio_map_odometry` (LiDAR-inertial), `anymal_state_odometry` (leg-inertial) and `cpt7_ie_tc_odometry` (post-processed GNSS/INS). For each pose, the prism point is computed as `p + R · l`, where `l` is the prism position in the estimator's body frame.

## Frames and lever arm
- Static transforms are stored as `p_child = R p_parent + t` (the inverse of the usual ROS reading). Evidence: the stored `base -> box_base` entry, inverted, equals the URDF joint `cpt7_to_robot_base` to 7 digits. `frle/frames.py` and `tests/test_frames.py`.
- Prism in `box_base`: the calibrated URDF joint `box_base_to_prism` (`boxi_description.yaml` in leggedrobotics/grand_tour_box), (0.309, −0.038, −0.235) m. Taken from the calibration, not fitted on the evaluation data.
- Body frames: DLIO → `hesai_lidar` (GrandTour's own evo config, `evo_evaluations.yaml`), leg odometry → `base`, CPT7 → `cpt7_imu` (at `box_base` in the tf).
- Cross-check, reported but not used: fit the lever arm together with the alignment per estimator and compare it with the URDF value. Only estimators that do not drift give a meaningful fit.

## Association, alignment, metric
- Association: prism stamps that have an estimate pose within `max_diff=0.06` s (evo `matching_time_indices`) and lie inside the estimate's time range; the estimate is interpolated there (evo `PoseTrajectory3D.interpolate`); 0.06 s is just above half the slowest estimator's period (DLIO, 10 Hz). Interpolation avoids the repeated-pose problem of `nearest_time` (evo issue 804).
- Alignment: rigid SE(3) Umeyama over all pairs, no scale (as in GrandTour's config: `n_to_align: -1`, `correct_scale: False`).
- Metric: APE, translation part, in metres: RMSE, median, max, the number of pairs and the time span covered. RMSE is also split into horizontal and vertical parts (axes of the total-station frame, whose z is vertical). Rotation error is not scored, because the prism gives no orientation.
- Difference from GrandTour's own config: no "remove until 10 m of motion" step and no AP20 peak or velocity rejection. The data-quality step found no step faster than 3 m/s in this mission's prism data.

## Uncertainty
- Errors next to each other in time are correlated, so a plain bootstrap over samples would give intervals that are too narrow. Pairs are grouped into 10 s blocks by time, and whole blocks are resampled: 2,000 resamples, seed 0, 95 % percentile intervals for RMSE and median.
- Paired comparison of two estimators: both are scored on the same prism timestamps, and each resample uses the same blocks for both; the interval is for the RMSE difference.
- Limitation: the alignment is computed once and held fixed in the resamples, so the intervals leave out alignment uncertainty.

## Across missions
Written on 2026-11-24, after the one-mission results and before any other mission was downloaded or scored.

- Missions: every public GrandTour mission on Hugging Face with prism ground truth, DLIO, leg odometry and tf (`scripts/list_missions.py`): 42 of 51. CPT7 only for 2024-11-04-10-57-34 (download size limit).
- A mission is scored only if none of the used topics fails a data-quality check (warnings are fine) and the estimator has at least 500 pairs with the prism. Excluded missions are listed with the reason, never dropped silently.
- Per mission: the protocol above (APE, block bootstrap intervals).
- Summary per estimator: median and interquartile range of the per-mission RMSE, and the number of missions.
- Paired comparison DLIO vs leg odometry: per-mission RMSE difference on the same prism timestamps; the number of missions where each one is better; median difference with a 95 % interval from resampling whole missions (2,000 resamples, seed 0).

## Amendments
- 2026-11-24, while building the regression gate: the association no longer calls evo `associate_trajectories` with interpolation, because that resamples whichever trajectory has more poses. In the full mission that is always the estimate (the stated protocol), so the mission results did not change; on the 10 s fixture DLIO has fewer poses than the prism, and evo would have interpolated the ground truth. The estimate is now always the resampled one.
- 2026-11-24, after the first run: added the horizontal/vertical RMSE split to the report, to show where the CPT7 error comes from (mostly vertical). No metric or setting changed.
