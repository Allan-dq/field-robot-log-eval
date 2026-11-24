"""Data-quality checks per mission and topic. The criteria and their reasons are in
docs/data_quality.md; the thresholds below must match that file."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from frle.config import Config
from frle.db import connect

# Thresholds (see docs/data_quality.md for the reason behind each one).
GAP_FACTOR = 5.0  # a gap is an interval longer than GAP_FACTOR x the topic's median interval
REGULAR_BAND = (0.5, 1.5)  # "regular" interval: within this band x the median interval
MIN_REGULAR_SHARE = 0.95
MAX_SPEED_M_S = 3.0  # faster consecutive motion is flagged as a jump
MIN_COVERAGE = 0.9  # topic time span / mission time span
QUAT_NORM_TOL = 1e-3


@dataclass
class Check:
    name: str
    severity: str  # "fail" or "warn" when the check does not pass
    passed: bool
    value: float | int
    limit: str


@dataclass
class TopicQC:
    mission: str
    topic: str
    table: str
    rows: int
    start: float
    end: float
    metrics: dict = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        failed = [c for c in self.checks if not c.passed]
        if any(c.severity == "fail" for c in failed):
            return "fail"
        return "warn" if failed else "pass"


def check_series(df: pd.DataFrame, table: str, mission_span: float) -> tuple[dict, list[Check]]:
    """df holds one topic in file order (not re-sorted, so disorder stays visible)."""
    t = df["t"].to_numpy()
    xyz = df[["x", "y", "z"]].to_numpy()
    checks: list[Check] = []
    m: dict = {"rows": len(df)}
    checks.append(Check("non_empty", "fail", len(df) > 0, len(df), "> 0 rows"))
    if len(df) < 2:
        return m, checks

    value_cols = ["t", "x", "y", "z"] + (["qx", "qy", "qz", "qw"] if table == "pose" else [])
    non_finite = int((~np.isfinite(df[value_cols].to_numpy())).any(axis=1).sum())
    checks.append(
        Check("finite_values", "fail", non_finite == 0, non_finite, "0 rows with NaN/inf")
    )

    dt = np.diff(t)
    backwards = int((dt < 0).sum())
    duplicates = int((dt == 0).sum())
    checks.append(Check("monotonic_time", "fail", backwards == 0, backwards, "0 backward steps"))
    checks.append(Check("unique_time", "fail", duplicates == 0, duplicates, "0 repeated stamps"))

    pos = dt[dt > 0]
    med = float(np.median(pos)) if len(pos) else float("nan")
    m["median_period_s"] = med
    m["median_rate_hz"] = 1.0 / med if med > 0 else float("nan")
    gaps = pos[pos > GAP_FACTOR * med]
    m["gaps"] = len(gaps)
    m["longest_gap_s"] = float(gaps.max()) if len(gaps) else 0.0
    m["gap_time_s"] = float(gaps.sum())
    checks.append(
        Check("no_gaps", "warn", len(gaps) == 0, len(gaps), f"0 intervals > {GAP_FACTOR}x median")
    )
    lo, hi = REGULAR_BAND
    regular = float(((pos >= lo * med) & (pos <= hi * med)).mean()) if len(pos) else 0.0
    m["regular_share"] = regular
    checks.append(
        Check(
            "regular_rate",
            "warn",
            regular >= MIN_REGULAR_SHARE,
            round(regular, 4),
            f">= {MIN_REGULAR_SHARE} of intervals in {lo}-{hi}x median",
        )
    )

    ok = np.isfinite(xyz).all(axis=1) & np.isfinite(t)
    tt, pp = t[ok], xyz[ok]
    step_dt = np.diff(tt)
    step = np.linalg.norm(np.diff(pp, axis=0), axis=1)
    # Steps with zero or negative time are left to the time checks above.
    forward = step_dt > 0
    speed = step[forward] / step_dt[forward]
    jumps = int((speed > MAX_SPEED_M_S).sum())
    m["max_speed_m_s"] = float(speed.max()) if len(speed) else 0.0
    m["path_length_m"] = float(step.sum())
    checks.append(
        Check("no_jumps", "warn", jumps == 0, jumps, f"0 steps faster than {MAX_SPEED_M_S} m/s")
    )

    span = float(np.nanmax(t) - np.nanmin(t))
    coverage = span / mission_span if mission_span > 0 else 1.0
    m["duration_s"] = span
    m["coverage"] = coverage
    checks.append(
        Check(
            "coverage",
            "warn",
            coverage >= MIN_COVERAGE,
            round(coverage, 4),
            f">= {MIN_COVERAGE} of mission span",
        )
    )

    if table == "pose":
        q = df[["qx", "qy", "qz", "qw"]].to_numpy()
        dev = np.abs(np.linalg.norm(q, axis=1) - 1.0)
        bad = int((~(dev <= QUAT_NORM_TOL)).sum())
        m["max_quat_norm_dev"] = float(np.nanmax(dev)) if np.isfinite(dev).any() else float("nan")
        checks.append(
            Check(
                "unit_quaternion", "fail", bad == 0, bad, f"0 rows with | |q|-1 | > {QUAT_NORM_TOL}"
            )
        )
    return m, checks


def run(cfg: Config) -> list[TopicQC]:
    con = connect(cfg)
    results: list[TopicQC] = []
    tables = [t for t in ("position", "pose") if any((cfg.lake_dir / t).glob("*/*.parquet"))]
    if not tables:
        return results
    union = " UNION ALL ".join(f"SELECT mission, t FROM {t}" for t in tables)
    spans = con.execute(
        f"SELECT mission, min(t), max(t) FROM ({union}) WHERE isfinite(t) GROUP BY mission"
    ).fetchall()
    mission_span = {m: hi - lo for m, lo, hi in spans}
    for table in tables:
        keys = con.execute(f"SELECT DISTINCT mission, topic FROM {table} ORDER BY 1, 2").fetchall()
        for mission, topic in keys:
            # file order is kept by reading the partition file directly
            path = cfg.lake_dir / table / mission / f"{topic}.parquet"
            df = pd.read_parquet(path)
            metrics, checks = check_series(df, table, mission_span[mission])
            t = df["t"].to_numpy()
            results.append(
                TopicQC(
                    mission,
                    topic,
                    table,
                    len(df),
                    float(np.nanmin(t)),
                    float(np.nanmax(t)),
                    metrics,
                    checks,
                )
            )
    return results


def write_reports(results: list[TopicQC], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "mission": r.mission,
            "topic": r.topic,
            "table": r.table,
            "rows": r.rows,
            "status": r.status,
            "metrics": r.metrics,
            "checks": [c.__dict__ for c in r.checks],
        }
        for r in results
    ]
    (out_dir / "qc.json").write_text(json.dumps(payload, indent=2) + "\n")
    lines = [
        "# Data-quality report",
        "",
        "Generated by `frle qc`. Criteria: docs/data_quality.md.",
        "",
        "| Mission | Topic | Rows | Rate (Hz) | Duration (s) | Coverage | Gaps | Longest gap (s) | Jumps | Status | Failed checks |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m = r.metrics
        failed = ", ".join(f"{c.name} ({c.value})" for c in r.checks if not c.passed) or "-"
        jumps = next((c.value for c in r.checks if c.name == "no_jumps"), "-")
        lines.append(
            f"| {r.mission} | {r.topic} | {r.rows:,} | {m.get('median_rate_hz', float('nan')):.1f} | "
            f"{m.get('duration_s', 0):.1f} | {m.get('coverage', 0):.3f} | {m.get('gaps', 0)} | "
            f"{m.get('longest_gap_s', 0):.1f} | {jumps} | {r.status} | {failed} |"
        )
    (out_dir / "qc.md").write_text("\n".join(lines) + "\n")
