# Our own odometry run: KISS-ICP on the Livox LiDAR

Written on 2026-11-24, before KISS-ICP was run on any GrandTour data.

## Why
Everything scored so far was produced onboard by GrandTour's own estimators. This run produces an odometry of our own from raw sensor data and scores it with the same protocol (`docs/evaluation.md`), so the comparison with DLIO is like for like.

## Setup
- Data: `livox_points` of mission 2024-11-04-10-57-34 (777 MB, CC BY-SA 4.0). The raw topic, not `livox_points_undistorted`: the undistorted clouds were motion-compensated with another estimator's motion, which would leak that estimator into ours.
- Odometry: KISS-ICP 1.3.0 (PRBonn, MIT license), Python API, LiDAR only (no IMU). DLIO, the comparison, uses a different LiDAR (Hesai XT32) plus an IMU, so this compares two pipelines, not two algorithms on the same input.
- Configuration: all KISS-ICP defaults (max range 100 m, voxel size 1.0 m, adaptive threshold). Deskewing on when the clouds carry per-point times; the times are scaled to [0, 1] within each scan.
- Output: the pose of the `livox_lidar` frame for every scan, stored as pose topic `kiss_icp_livox` in the lake (frame `kiss_icp_map`), stamped with the scan's timestamp from the dataset. Body frame for the prism lever arm: `livox_lidar` (from the static tf).

## Rules
- No tuning against the ground truth. One run with the defaults. If it fails (diverges or loses track), the failure is reported as the result; at most one documented change based on the sensor (for example range or voxel size for its field of view), never on the scores, and the failed run stays in the report.
- Scored exactly like the other estimators: APE translation against the prism, rigid alignment, 10 s block bootstrap, paired comparison with DLIO on the same prism stamps, and the triage rules.
- Run time is reported (single Mac, M1 Pro).

## Notes added after the run (2026-11-24)
- Pose stamp: KISS-ICP 1.3.0 deskews every point to the end of its scan (`Preprocessing.cpp`: `exp((stamp - 1.0) * omega)` on normalized point times), so each pose is stamped with the latest point time of its scan. The dataset's scan stamp is the scan start, 0.1 s earlier. This was decided from the source code, not from the scores.
- The run used the defaults and was not repeated or tuned. Results: `reports/eval.md` (mission 2024-11-04-10-57-34) and `reports/kiss_icp_run_2024-11-04-10-57-34.json`.
