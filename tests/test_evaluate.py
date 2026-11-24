"""Checks the evaluation on a synthetic walk where the true error is known. These numbers are test
inputs, not results."""

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

from frle import evaluate

LEVER = np.array([0.3, -0.04, 0.25])
NOISE = 0.01


def synthetic(seed=1, n=3000, rate=20.0):
    rng = np.random.default_rng(seed)
    t = 1000.0 + np.arange(n) / rate
    yaw = 0.05 * (t - t[0])  # keeps turning, so the lever arm is observable
    p = np.column_stack([np.cos(yaw) * 5, np.sin(yaw) * 5, 0.1 * np.sin(0.3 * t)])
    rot = Rotation.from_euler("zyx", np.column_stack([yaw, 0.05 * np.sin(t), 0.05 * np.cos(t)]))
    q = rot.as_quat()
    est = pd.DataFrame(
        {
            "t": t,
            "x": p[:, 0],
            "y": p[:, 1],
            "z": p[:, 2],
            "qx": q[:, 0],
            "qy": q[:, 1],
            "qz": q[:, 2],
            "qw": q[:, 3],
        }
    )
    world = Rotation.from_euler("z", 0.7)
    truth = world.apply(p + rot.apply(LEVER)) + [10.0, -3.0, 1.0]
    g = truth + rng.normal(0, NOISE, truth.shape)
    ref = pd.DataFrame({"t": t + 0.013, "x": g[:, 0], "y": g[:, 1], "z": g[:, 2]})
    return ref, est


def test_correct_lever_arm_gives_noise_level_error():
    ref, est = synthetic()
    err, _ = evaluate.ape_errors(
        evaluate.reference_trajectory(ref), evaluate.prism_trajectory(est, LEVER)
    )
    expected = NOISE * np.sqrt(3)  # 3-D noise
    assert abs(evaluate.rmse(err) - expected) < 0.25 * expected


def test_missing_lever_arm_inflates_error():
    ref, est = synthetic()
    ref_t = evaluate.reference_trajectory(ref)
    good, _ = evaluate.ape_errors(ref_t, evaluate.prism_trajectory(est, LEVER))
    bad, _ = evaluate.ape_errors(ref_t, evaluate.prism_trajectory(est, np.zeros(3)))
    assert evaluate.rmse(bad) > 5 * evaluate.rmse(good)


def test_fit_recovers_lever_arm():
    ref, est = synthetic()
    fitted, fit_rmse = evaluate.fit_lever_arm(ref, est)
    assert np.linalg.norm(fitted - LEVER) < 0.02
    assert fit_rmse < 3 * NOISE


def test_block_bootstrap_interval_contains_estimate():
    rng = np.random.default_rng(0)
    e = np.abs(rng.normal(0, 0.05, 2000))
    blocks = evaluate.block_ids(np.arange(2000) / 20.0)
    boot = evaluate.block_bootstrap([e], blocks, evaluate.rmse, n_boot=300)
    lo, hi = evaluate.ci(boot)
    assert lo < evaluate.rmse(e) < hi


def test_paired_bootstrap_of_identical_errors_is_zero():
    e = np.linspace(0.01, 0.1, 500)
    blocks = evaluate.block_ids(np.arange(500) / 10.0)
    diff = evaluate.block_bootstrap(
        [e, e], blocks, lambda a, b: evaluate.rmse(a) - evaluate.rmse(b), n_boot=100
    )
    assert np.allclose(diff, 0)


def test_blocks_follow_time():
    assert evaluate.block_ids(np.array([0.0, 9.9, 10.0, 25.0])).tolist() == [0, 0, 1, 2]


def test_differences_match_errors():
    ref, est = synthetic()
    r, e = evaluate.reference_trajectory(ref), evaluate.prism_trajectory(est, LEVER)
    err, _ = evaluate.ape_errors(r, e)
    diff, _ = evaluate.aligned_differences(r, e)
    assert np.allclose(np.linalg.norm(diff, axis=1), err)


def test_sparser_estimate_is_interpolated_not_the_reference():
    """evo's interpolation sync would resample the reference here (it has more poses)."""
    ref, est = synthetic()
    sparse = est.iloc[::2].reset_index(drop=True)  # 10 Hz estimate, 20 Hz reference
    r = evaluate.reference_trajectory(ref)
    ref_s, est_s = evaluate.associate(r, evaluate.prism_trajectory(sparse, LEVER))
    assert np.isin(ref_s.timestamps, r.timestamps).all()
    assert np.allclose(est_s.timestamps, ref_s.timestamps)
    assert ref_s.num_poses > 0.9 * len(ref)
