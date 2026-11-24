"""Triage and failure attribution. Rules and reasons: docs/triage.md."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from frle import evaluate
from frle.config import Config
from frle.frames import StaticTF, prism_in_body
from frle.qc import GAP_FACTOR, MAX_SPEED_M_S

ESTIMATORS = ("dlio_map_odometry", "anymal_state_odometry")
SHORT = {"dlio_map_odometry": "dlio", "anymal_state_odometry": "leg"}
TOL_ABS_M = 0.3
TOL_REL = 0.05
BAD_ABS_M = 0.10
BAD_REL = 5.0
MERGE_S = 1.0
GT_MARGIN_S = 1.0
WEAK_PATH_M = 50.0
CAUSES = ("ground_truth", "estimate_data", "estimator_jump", "drift")


@dataclass
class Segment:
    mission: str
    estimator: str
    start_s: float  # since the first scored prism stamp of the mission
    duration_s: float
    pairs: int
    max_error_m: float
    cause: str


def mission_table(cfg: Config, mission: str) -> pd.DataFrame:
    """Prism stamps covered by both estimators: positions, aligned errors, step lengths."""
    lake = cfg.lake_dir
    ref_df = pd.read_parquet(lake / "position" / mission / "prism_position.parquet")
    tf = StaticTF(pd.read_parquet(lake / "static_tf" / mission / "tf.parquet"))
    ref = evaluate.reference_trajectory(ref_df)
    cols = []
    for topic in ESTIMATORS:
        est_df = pd.read_parquet(lake / "pose" / mission / f"{topic}.parquet")
        est = evaluate.prism_trajectory(est_df, prism_in_body(tf, topic))
        ref_s, est_s = evaluate.associate(ref, est)
        est_s.align(ref_s, correct_scale=False)
        k = SHORT[topic]
        idx = pd.Index(np.round(ref_s.timestamps, 6), name="t")
        frame = pd.DataFrame(est_s.positions_xyz, index=idx, columns=[f"{k}_x", f"{k}_y", f"{k}_z"])
        frame[f"{k}_err"] = np.linalg.norm(est_s.positions_xyz - ref_s.positions_xyz, axis=1)
        frame[["gt_x", "gt_y", "gt_z"]] = ref_s.positions_xyz
        cols.append(frame)
    table = cols[0].join(cols[1].drop(columns=["gt_x", "gt_y", "gt_z"]), how="inner")
    for k in ("gt", "dlio", "leg"):
        p = table[[f"{k}_x", f"{k}_y", f"{k}_z"]].to_numpy()
        step = np.r_[np.nan, np.linalg.norm(np.diff(p, axis=0), axis=1)]
        table[f"{k}_step"] = step
    return table.reset_index()


def detect_events(table: pd.DataFrame) -> pd.DataFrame:
    sp, sd, sl = table["gt_step"], table["dlio_step"], table["leg_step"]
    tol = TOL_ABS_M + TOL_REL * (sd + sl) / 2
    agree_est = (sd - sl).abs() <= tol
    ev = pd.DataFrame({"t": table["t"]})
    ev["gt_jump"] = ((sp - np.maximum(sd, sl)) > tol) & agree_est
    ev["est_jump_dlio"] = ((sd - sp).abs() > tol) & ((sp - sl).abs() <= tol)
    ev["est_jump_leg"] = ((sl - sp).abs() > tol) & ((sp - sd).abs() <= tol)
    # A jump is a step between two stamps, and either of them can be the wrong one, so both ends
    # are marked (amendment 1 in docs/triage.md).
    for c in ("gt_jump", "est_jump_dlio", "est_jump_leg"):
        ev[c] = ev[c] | ev[c].shift(-1, fill_value=False)
    return ev


def topic_data_events(est_df: pd.DataFrame) -> np.ndarray:
    """Times of QC-type events in an estimator's own topic: gaps and steps faster than 3 m/s."""
    t = est_df["t"].to_numpy()
    p = est_df[["x", "y", "z"]].to_numpy()
    dt = np.diff(t)
    med = np.median(dt[dt > 0])
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = np.linalg.norm(np.diff(p, axis=0), axis=1) / dt
    bad = (dt > GAP_FACTOR * med) | ((dt > 0) & (speed > MAX_SPEED_M_S))
    return t[1:][bad]


def segments_for(table: pd.DataFrame, k: str) -> list[tuple[int, int]]:
    err = table[f"{k}_err"].to_numpy()
    limit = max(BAD_ABS_M, BAD_REL * float(np.median(err)))
    bad = np.flatnonzero(err > limit)
    if not len(bad):
        return []
    t = table["t"].to_numpy()
    out, start, prev = [], bad[0], bad[0]
    for i in bad[1:]:
        if t[i] - t[prev] >= MERGE_S:
            out.append((start, prev))
            start = i
        prev = i
    out.append((start, prev))
    return out


def attribute(t0: float, t1: float, gt_times, data_times, jump_times) -> str:
    def near(times, margin=0.0):
        return bool(len(times)) and bool(np.any((times >= t0 - margin) & (times <= t1 + margin)))

    if near(gt_times, GT_MARGIN_S):
        return "ground_truth"
    if near(data_times):
        return "estimate_data"
    if near(jump_times):
        return "estimator_jump"
    return "drift"


def triage_mission(cfg: Config, mission: str) -> dict:
    table = mission_table(cfg, mission)
    ev = detect_events(table)
    gt_times = ev.loc[ev["gt_jump"], "t"].to_numpy()
    path = float(np.nansum(table["gt_step"]))
    segs: list[Segment] = []
    filtered = {}
    t = table["t"].to_numpy()
    for topic in ESTIMATORS:
        k = SHORT[topic]
        est_df = pd.read_parquet(cfg.lake_dir / "pose" / mission / f"{topic}.parquet")
        data_times = topic_data_events(est_df)
        jump_times = ev.loc[ev[f"est_jump_{k}"], "t"].to_numpy()
        keep = np.ones(len(table), bool)
        for a, b in segments_for(table, k):
            cause = attribute(t[a], t[b], gt_times, data_times, jump_times)
            err = table[f"{k}_err"].to_numpy()[a : b + 1]
            segs.append(
                Segment(
                    mission,
                    topic,
                    float(t[a] - t[0]),
                    float(t[b] - t[a]),
                    int(b - a + 1),
                    float(err.max()),
                    cause,
                )
            )
            if cause == "ground_truth":
                keep[a : b + 1] = False
        err = table[f"{k}_err"].to_numpy()
        filtered[topic] = {
            "rmse_m": evaluate.rmse(err),
            "rmse_without_ground_truth_m": evaluate.rmse(err[keep]),
            "pairs_removed": int((~keep).sum()),
        }
    return {
        "mission": mission,
        "pairs": len(table),
        "prism_path_m": path,
        "weak_alignment": bool(path < WEAK_PATH_M),
        "events": {c: int(ev[c].sum()) for c in ("gt_jump", "est_jump_dlio", "est_jump_leg")},
        "segments": [asdict(s) for s in segs],
        "filtered": filtered,
        "_table": table,
        "_events": ev,
    }


def plot(result: dict, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    table, ev = result["_table"], result["_events"]
    t = table["t"] - table["t"].iloc[0]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.plot(t, table["dlio_err"], lw=0.8, label="DLIO APE")
    ax.plot(t, table["leg_err"], lw=0.8, alpha=0.6, label="leg odometry APE")
    for name, color in (("gt_jump", "red"), ("est_jump_dlio", "black")):
        for x in t[ev[name].to_numpy()]:
            ax.axvline(x, color=color, lw=0.6, alpha=0.5)
    ax.set_yscale("log")
    ax.set_xlabel("time since first scored prism sample (s)")
    ax.set_ylabel("error (m)")
    ax.set_title(f"{result['mission']}  (red: ground-truth jump, black: DLIO jump)")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    plt.close(fig)


def _json(o):
    if isinstance(o, np.generic):
        return o.item()
    raise TypeError(type(o))


def run(cfg: Config, out_dir: Path) -> dict:
    results = [triage_mission(cfg, m) for m in cfg.missions]
    for r in results:
        if any(s["estimator"] == "dlio_map_odometry" for s in r["segments"]):
            plot(r, out_dir / "triage" / f"{r['mission']}.png")
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
    counts = {}
    for topic in ESTIMATORS:
        segs = [s for r in clean for s in r["segments"] if s["estimator"] == topic]
        counts[topic] = {
            c: {
                "segments": sum(s["cause"] == c for s in segs),
                "pairs": sum(s["pairs"] for s in segs if s["cause"] == c),
            }
            for c in CAUSES
        }
    medians = {
        topic: {
            "median_rmse_m": float(np.median([r["filtered"][topic]["rmse_m"] for r in clean])),
            "median_rmse_without_ground_truth_m": float(
                np.median([r["filtered"][topic]["rmse_without_ground_truth_m"] for r in clean])
            ),
        }
        for topic in ESTIMATORS
    }
    report = {"missions": clean, "counts": counts, "medians": medians}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "triage.json").write_text(json.dumps(report, indent=2, default=_json) + "\n")
    write_markdown(report, out_dir / "triage.md")
    return report


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Triage",
        "",
        "Generated by `frle triage`. Rules: docs/triage.md. Unfiltered scores: summary.md.",
        "",
    ]
    lines += [
        "## Bad segments by cause",
        "",
        "| Estimator | Cause | Segments | Pairs |",
        "|---|---|---|---|",
    ]
    for topic, by in report["counts"].items():
        for cause, c in by.items():
            lines.append(f"| {topic} | {cause} | {c['segments']} | {c['pairs']:,} |")
    lines += [
        "",
        "## RMSE with and without ground-truth segments (median across missions, m)",
        "",
        "| Estimator | Unfiltered | Without ground-truth segments |",
        "|---|---|---|",
    ]
    for topic, m in report["medians"].items():
        lines.append(
            f"| {topic} | {m['median_rmse_m']:.3f} | {m['median_rmse_without_ground_truth_m']:.3f} |"
        )
    lines += [
        "",
        "## Per mission",
        "",
        "| Mission | Prism path (m) | Weak alignment | GT jumps | DLIO jumps | DLIO RMSE | DLIO without GT | Leg RMSE | Leg without GT |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["missions"]:
        d, g = r["filtered"]["dlio_map_odometry"], r["filtered"]["anymal_state_odometry"]
        lines.append(
            f"| {r['mission']} | {r['prism_path_m']:.0f} | {'yes' if r['weak_alignment'] else ''} | "
            f"{r['events']['gt_jump']} | {r['events']['est_jump_dlio']} | {d['rmse_m']:.3f} | "
            f"{d['rmse_without_ground_truth_m']:.3f} | {g['rmse_m']:.3f} | {g['rmse_without_ground_truth_m']:.3f} |"
        )
    lines += [
        "",
        "## DLIO bad segments",
        "",
        "| Mission | Start (s after first scored stamp) | Duration (s) | Pairs | Max error (m) | Cause | Plot |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["missions"]:
        for s in r["segments"]:
            if s["estimator"] != "dlio_map_odometry":
                continue
            lines.append(
                f"| {r['mission']} | {s['start_s']:.1f} | {s['duration_s']:.1f} | {s['pairs']} | {s['max_error_m']:.3f} | "
                f"{s['cause']} | [plot](triage/{r['mission']}.png) |"
            )
    path.write_text("\n".join(lines) + "\n")
