# Data-quality criteria

Written on 2026-11-24, before `frle qc` was first run. Changes after that go in the amendments list at the end, with a date and a reason. Thresholds are constants at the top of `frle/qc.py` and must match this file.

Disclosure: one timing summary of mission 2024-11-04-10-57-34 (sample counts, median periods, one 87.6 s prism gap) was seen on 2026-11-16 during the evo work, before these criteria were written. The criteria are relative to each topic's own median interval, so they do not depend on knowing nominal sensor rates.

Each check runs per mission and topic, on the rows in the order they are stored (not re-sorted, so disorder stays visible). A **fail** means the topic must not be used for evaluation until fixed; a **warn** means it can be used, but the evaluation has to account for it (for example, by masking the gap).

| Check | Severity | Passes when | Reason |
|---|---|---|---|
| `non_empty` | fail | at least 1 row | An empty topic means a recording or export problem. |
| `finite_values` | fail | no row has NaN or inf in time, position or orientation | Non-finite values break alignment and metrics silently. |
| `monotonic_time` | fail | no timestamp is earlier than the one before it | Out-of-order stamps point to merged chunks or a clock reset; time-based matching assumes order. |
| `unique_time` | fail | no timestamp equals the one before it | Repeated stamps make nearest-time matching ambiguous (see evo issue 468 / 804). |
| `unit_quaternion` (pose only) | fail | every quaternion has \|‖q‖ − 1\| ≤ 1e-3 | A non-unit quaternion is not a rotation; 1e-3 tolerates float32 round-trips. |
| `no_gaps` | warn | no interval is longer than 5 × the topic's median interval | 5× is far outside normal jitter but catches dropouts and lost line of sight. Gaps are expected for the prism (the total station loses the robot), so this is a warning that the evaluation must mask, not a failure. |
| `regular_rate` | warn | at least 95 % of intervals lie within 0.5–1.5 × the median interval | Flags topics whose rate drifts or alternates, which affects RPE with a fixed frame delta. |
| `no_jumps` | warn | no step between consecutive samples is faster than 3 m/s | Legged robots walk well below 3 m/s, so faster steps are localization resets or outliers rather than motion. Engineering judgement, not a vendor limit. |
| `coverage` | warn | the topic spans at least 90 % of the mission's time span (union of all time-series topics) | Ground truth that covers only part of a mission limits which segments can be scored. |

Reported metrics (no pass/fail): median rate, number of gaps, longest gap, total gap time, share of regular intervals, maximum speed, path length, duration.

## Amendments
(none yet)
