"""Triage rules on a synthetic walk with one ground-truth outlier run and one DLIO jump."""

import numpy as np
import pandas as pd

from frle import triage


def table(n=600, rate=20.0, seed=0):
    rng = np.random.default_rng(seed)
    t = 1000 + np.arange(n) / rate
    gt = np.column_stack([0.5 * (t - t[0]), np.zeros(n), np.zeros(n)])  # 0.5 m/s straight walk
    dlio = gt + rng.normal(0, 0.01, gt.shape)
    leg = gt + np.column_stack([0.01 * (t - t[0]), np.zeros(n), np.zeros(n)])  # slow drift
    gt_meas = gt.copy()
    gt_meas[100:121] += [0.0, 2.0, 0.0]  # total station locks on something else for 1 s
    dlio[400:] += [0.0, 1.0, 0.0]  # DLIO jumps by 1 m and stays off
    df = pd.DataFrame({"t": t})
    for k, p in (("gt", gt_meas), ("dlio", dlio), ("leg", leg)):
        df[[f"{k}_x", f"{k}_y", f"{k}_z"]] = p
        df[f"{k}_step"] = np.r_[np.nan, np.linalg.norm(np.diff(p, axis=0), axis=1)]
    df["dlio_err"] = np.linalg.norm(dlio - gt_meas, axis=1)
    df["leg_err"] = np.linalg.norm(leg - gt_meas, axis=1)
    return df


def test_events():
    ev = triage.detect_events(table())
    assert ev.index[ev["gt_jump"]].tolist() == [99, 100, 120, 121]  # both ends of both jumps
    assert {399, 400} <= set(ev.index[ev["est_jump_dlio"]])
    assert not ev["est_jump_leg"].any()


def test_segments_are_attributed():
    df = table()
    ev = triage.detect_events(df)
    t = df["t"].to_numpy()
    gt_times = ev.loc[ev["gt_jump"], "t"].to_numpy()
    jumps = ev.loc[ev["est_jump_dlio"], "t"].to_numpy()
    causes = [
        triage.attribute(t[a], t[b], gt_times, np.array([]), jumps)
        for a, b in triage.segments_for(df, "dlio")
    ]
    assert causes == ["ground_truth", "estimator_jump"]


def test_data_event_wins_over_jump():
    est = pd.DataFrame(
        {"t": [0.0, 0.1, 0.2, 2.0, 2.1], "x": [0, 0.05, 0.1, 0.15, 5.0], "y": 0.0, "z": 0.0}
    )
    times = triage.topic_data_events(est)
    assert times.tolist() == [2.0, 2.1]  # a gap, then a 49 m/s step
    assert triage.attribute(1.9, 2.2, np.array([]), times, np.array([2.1])) == "estimate_data"


def test_no_segments_on_clean_walk():
    df = table()
    df["dlio_err"] = 0.01
    assert triage.segments_for(df, "dlio") == []


def test_outlier_at_first_stamp_before_a_gap_is_ground_truth():
    df = table()
    df = df.iloc[[0] + list(range(300, 600))].reset_index(drop=True)  # 15 s gap after row 0
    df.loc[0, ["gt_x", "gt_y"]] = [df.loc[0, "gt_x"] + 50, 50.0]
    for k in ("gt", "dlio", "leg"):
        p = df[[f"{k}_x", f"{k}_y", f"{k}_z"]].to_numpy()
        df[f"{k}_step"] = np.r_[np.nan, np.linalg.norm(np.diff(p, axis=0), axis=1)]
    df["dlio_err"] = np.hypot(df["dlio_x"] - df["gt_x"], df["dlio_y"] - df["gt_y"])
    ev = triage.detect_events(df)
    t = df["t"].to_numpy()
    a, b = triage.segments_for(df, "dlio")[0]
    assert a == 0
    assert (
        triage.attribute(
            t[a], t[b], ev.loc[ev["gt_jump"], "t"].to_numpy(), np.array([]), np.array([])
        )
        == "ground_truth"
    )
