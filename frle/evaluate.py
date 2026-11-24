"""Score odometry against the prism ground truth with evo (APE, translation) and block bootstrap
intervals. Protocol: docs/evaluation.md."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from evo.core import metrics, sync
from evo.core.trajectory import PoseTrajectory3D
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from frle.config import Config
from frle.frames import StaticTF, prism_in_body

MAX_DIFF_S = 0.06
BLOCK_S = 10.0
N_BOOT = 2000
SEED = 0
ESTIMATORS = ("dlio_map_odometry", "anymal_state_odometry", "cpt7_ie_tc_odometry", "kiss_icp_livox")


@dataclass
class Score:
    mission: str
    topic: str
    pairs: int
    span_s: float
    rmse_m: float
    rmse_ci_m: tuple[float, float]
    median_m: float
    median_ci_m: tuple[float, float]
    max_m: float
    rmse_horizontal_m: float
    rmse_vertical_m: float
    lever_arm_body_m: tuple[float, float, float]


def prism_trajectory(est: pd.DataFrame, lever_arm: np.ndarray) -> PoseTrajectory3D:
    """Positions of the prism point given the estimator's poses (x, y, z, qx, qy, qz, qw)."""
    q_xyzw = est[["qx", "qy", "qz", "qw"]].to_numpy()
    p = est[["x", "y", "z"]].to_numpy() + Rotation.from_quat(q_xyzw).apply(lever_arm)
    return PoseTrajectory3D(
        positions_xyz=p,
        orientations_quat_wxyz=q_xyzw[:, [3, 0, 1, 2]],
        timestamps=est["t"].to_numpy(),
    )


def reference_trajectory(ref: pd.DataFrame) -> PoseTrajectory3D:
    n = len(ref)
    return PoseTrajectory3D(
        positions_xyz=ref[["x", "y", "z"]].to_numpy(),
        orientations_quat_wxyz=np.tile([1.0, 0.0, 0.0, 0.0], (n, 1)),
        timestamps=ref["t"].to_numpy(),
    )


def associate(
    ref: PoseTrajectory3D, est: PoseTrajectory3D
) -> tuple[PoseTrajectory3D, PoseTrajectory3D]:
    """Keeps the reference stamps that have an estimate pose within MAX_DIFF_S and lie inside the
    estimate's time range, and interpolates the estimate there. The estimate is always the one
    resampled: evo's interpolation sync resamples whichever trajectory has more poses, which would
    interpolate the ground truth when the estimate is sparser."""
    idx_ref, _ = sync.matching_time_indices(ref.timestamps, est.timestamps, MAX_DIFF_S)
    t = ref.timestamps[idx_ref]
    inside = (t >= est.timestamps[0]) & (t <= est.timestamps[-1])
    idx = np.asarray(idx_ref)[inside]
    if len(idx) < 3:
        raise ValueError(f"only {len(idx)} reference stamps overlap the estimate")
    ref_s = copy.deepcopy(ref)
    ref_s.reduce_to_ids(idx)
    return ref_s, est.interpolate(ref_s.timestamps)


def aligned_differences(
    ref: PoseTrajectory3D, est: PoseTrajectory3D
) -> tuple[np.ndarray, np.ndarray]:
    """Per-pair position differences (estimate - reference, m) after association and alignment,
    in the reference frame, and the reference timestamps."""
    ref_s, est_s = associate(ref, est)
    est_s.align(ref_s, correct_scale=False)
    return est_s.positions_xyz - ref_s.positions_xyz, ref_s.timestamps


def ape_errors(ref: PoseTrajectory3D, est: PoseTrajectory3D) -> tuple[np.ndarray, np.ndarray]:
    """Per-pair APE translation errors (m) and their reference timestamps."""
    ref_s, est_s = associate(ref, est)
    est_s.align(ref_s, correct_scale=False)
    ape = metrics.APE(metrics.PoseRelation.translation_part)
    ape.process_data((ref_s, est_s))
    return np.asarray(ape.error), ref_s.timestamps


def rmse(e: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(e))))


def block_ids(t: np.ndarray, block_s: float = BLOCK_S) -> np.ndarray:
    return np.floor((t - t.min()) / block_s).astype(int)


def block_bootstrap(
    errors: list[np.ndarray], blocks: np.ndarray, stats, n_boot: int = N_BOOT, seed: int = SEED
) -> np.ndarray:
    """Resamples whole blocks with replacement. `errors` are aligned arrays (same pairs), so a
    paired statistic sees the same resampled blocks for every array. Returns (n_boot, ...)."""
    rng = np.random.default_rng(seed)
    ids = np.unique(blocks)
    index = {b: np.flatnonzero(blocks == b) for b in ids}
    out = []
    for _ in range(n_boot):
        pick = np.concatenate([index[b] for b in rng.choice(ids, size=len(ids), replace=True)])
        out.append(stats(*[e[pick] for e in errors]))
    return np.asarray(out)


def ci(samples: np.ndarray) -> tuple[float, float]:
    lo, hi = np.percentile(samples, [2.5, 97.5])
    return float(lo), float(hi)


def fit_lever_arm(ref: pd.DataFrame, est: pd.DataFrame) -> tuple[np.ndarray, float]:
    """Cross-check only: fits the lever arm together with a rigid alignment by least squares."""
    t_ref = ref["t"].to_numpy()
    inside = (t_ref > est["t"].iloc[0]) & (t_ref < est["t"].iloc[-1])
    t = t_ref[inside]
    g = ref[["x", "y", "z"]].to_numpy()[inside]
    te = est["t"].to_numpy()
    p = np.column_stack([np.interp(t, te, est[c]) for c in "xyz"])
    from scipy.spatial.transform import Slerp

    rot = Slerp(te, Rotation.from_quat(est[["qx", "qy", "qz", "qw"]].to_numpy()))(t)

    def residual(x):
        return (Rotation.from_rotvec(x[:3]).apply(rot.apply(x[6:]) + p) + x[3:6] - g).ravel()

    mp, mg = p.mean(0), g.mean(0)
    u, _, vt = np.linalg.svd((p - mp).T @ (g - mg))
    d = np.diag([1.0, 1.0, np.sign(np.linalg.det(vt.T @ u.T))])
    r0 = vt.T @ d @ u.T
    x0 = np.r_[Rotation.from_matrix(r0).as_rotvec(), mg - r0 @ mp, np.zeros(3)]
    sol = least_squares(residual, x0)
    return sol.x[6:], rmse(np.linalg.norm(sol.fun.reshape(-1, 3), axis=1))


def evaluate_mission(cfg: Config, mission: str) -> dict:
    lake = cfg.lake_dir
    ref_df = pd.read_parquet(lake / "position" / mission / "prism_position.parquet")
    tf = StaticTF(pd.read_parquet(lake / "static_tf" / mission / "tf.parquet"))
    ref = reference_trajectory(ref_df)
    scores, per_pair, cross = [], {}, {}
    for topic in ESTIMATORS:
        path = lake / "pose" / mission / f"{topic}.parquet"
        if not path.exists():
            continue
        est_df = pd.read_parquet(path)
        arm = prism_in_body(tf, topic)
        est = prism_trajectory(est_df, arm)
        err, t = ape_errors(ref, est)
        diff, _ = aligned_differences(ref, est)
        blocks = block_ids(t)
        boot = block_bootstrap([err], blocks, lambda e: (rmse(e), float(np.median(e))))
        scores.append(
            Score(
                mission,
                topic,
                len(err),
                float(t.max() - t.min()),
                rmse(err),
                ci(boot[:, 0]),
                float(np.median(err)),
                ci(boot[:, 1]),
                float(err.max()),
                rmse(np.linalg.norm(diff[:, :2], axis=1)),
                rmse(diff[:, 2]),
                tuple(arm.round(4)),
            )
        )
        per_pair[topic] = pd.Series(err, index=np.round(t, 6))
        fitted, fit_rmse = fit_lever_arm(ref_df, est_df)
        cross[topic] = {
            "fitted_lever_arm_body_m": fitted.round(4).tolist(),
            "urdf_lever_arm_body_m": arm.round(4).tolist(),
            "difference_m": float(np.linalg.norm(fitted - arm)),
            "fit_rmse_m": fit_rmse,
        }
    paired = []
    names = list(per_pair)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            joined = pd.concat([per_pair[a], per_pair[b]], axis=1, join="inner").dropna()
            ea, eb = joined.iloc[:, 0].to_numpy(), joined.iloc[:, 1].to_numpy()
            blocks = block_ids(joined.index.to_numpy())
            diff = block_bootstrap([ea, eb], blocks, lambda x, y: rmse(x) - rmse(y))
            paired.append(
                {
                    "a": a,
                    "b": b,
                    "pairs": len(ea),
                    "rmse_diff_m": rmse(ea) - rmse(eb),
                    "ci_m": ci(diff),
                }
            )
    return {
        "mission": mission,
        "settings": {"max_diff_s": MAX_DIFF_S, "block_s": BLOCK_S, "n_boot": N_BOOT, "seed": SEED},
        "scores": [asdict(s) for s in scores],
        "paired": paired,
        "lever_arm_cross_check": cross,
    }


HEADER = (
    "| Estimator | Pairs | Span (s) | RMSE | RMSE 95 % CI | Median | Median 95 % CI | Max "
    "| RMSE horizontal | RMSE vertical |"
)


def write_reports(results: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval.json").write_text(json.dumps(results, indent=2) + "\n")
    lines = [
        "# Evaluation report",
        "",
        "Generated by `frle eval`. Protocol: docs/evaluation.md.",
        "",
    ]
    for res in results:
        lines += [
            f"## Mission {res['mission']}",
            "",
            "APE, translation, against the prism (m). 95 % block bootstrap intervals (10 s blocks).",
            "",
            HEADER,
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in res["scores"]:
            lines.append(
                f"| {s['topic']} | {s['pairs']:,} | {s['span_s']:.1f} | {s['rmse_m']:.3f} | "
                f"{s['rmse_ci_m'][0]:.3f}–{s['rmse_ci_m'][1]:.3f} | {s['median_m']:.3f} | "
                f"{s['median_ci_m'][0]:.3f}–{s['median_ci_m'][1]:.3f} | {s['max_m']:.3f} | "
                f"{s['rmse_horizontal_m']:.3f} | {s['rmse_vertical_m']:.3f} |"
            )
        lines += [
            "",
            "Paired RMSE difference (a − b) on the same prism timestamps:",
            "",
            "| a | b | Pairs | Difference | 95 % CI |",
            "|---|---|---|---|---|",
        ]
        for p in res["paired"]:
            lines.append(
                f"| {p['a']} | {p['b']} | {p['pairs']:,} | {p['rmse_diff_m']:+.3f} | "
                f"{p['ci_m'][0]:+.3f} to {p['ci_m'][1]:+.3f} |"
            )
        lines += [
            "",
            "Lever-arm cross-check (fitted with the alignment vs URDF, body frame, m):",
            "",
            "| Estimator | URDF | Fitted | Difference | Fit RMSE |",
            "|---|---|---|---|---|",
        ]
        for topic, c in res["lever_arm_cross_check"].items():
            lines.append(
                f"| {topic} | {c['urdf_lever_arm_body_m']} | {c['fitted_lever_arm_body_m']} | "
                f"{c['difference_m']:.3f} | {c['fit_rmse_m']:.3f} |"
            )
        lines.append("")
    (out_dir / "eval.md").write_text("\n".join(lines) + "\n")
