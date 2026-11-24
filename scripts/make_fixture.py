"""Cut a 10 s window of every configured topic from one GrandTour mission into tests/fixtures.

Window choice: among windows starting every 2 s that have prism ground truth without a gap longer
than 0.2 s, the one where the DLIO heading changes most. Turning makes lever-arm and frame errors
visible; on a straight walk the rigid alignment absorbs them (docs/regression_gate.md, amendment 1).
Run: python scripts/make_fixture.py [--mission 2024-11-04-10-57-34] [--seconds 10]
"""

from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np

from frle import config
from frle.archive import read_topic_group, write_topic_archive
from frle.config import REPO
from frle.download import archive_path

KEEP = {"timestamp", "sequence_id", "point", "pose_pos", "pose_orien"}


def pick_window(t_gt, t_est, q_xyzw, seconds, step=2.0, max_gap=0.2):
    x, y, z, w = q_xyzw.T
    yaw = np.unwrap(np.arctan2(2 * (w * z + x * y), 1 - 2 * (y**2 + z**2)))
    best, best_turn = None, -1.0
    for start in np.arange(t_gt[0], t_gt[-1] - seconds, step):
        g = t_gt[(t_gt >= start) & (t_gt < start + seconds)]
        if len(g) < 2 or g[0] - start > max_gap or start + seconds - g[-1] > max_gap:
            continue
        if np.diff(g).max() > max_gap:
            continue
        sel = (t_est >= start) & (t_est < start + seconds)
        turn = float(yaw[sel].max() - yaw[sel].min()) if sel.any() else -1.0
        if turn > best_turn:
            best, best_turn = float(start), turn
    if best is None:
        raise SystemExit("no window with continuous ground truth")
    print(f"heading change in window: {best_turn:.2f} rad")
    return best


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mission", default="2024-11-04-10-57-34")
    p.add_argument("--seconds", type=float, default=10.0)
    args = p.parse_args()
    cfg = config.load()
    out_dir = REPO / "tests" / "fixtures" / "grandtour_10s" / args.mission
    prism, _ = read_topic_group(archive_path(cfg, args.mission, "prism_position"), "prism_position")
    dlio, _ = read_topic_group(
        archive_path(cfg, args.mission, "dlio_map_odometry"), "dlio_map_odometry"
    )
    t0 = pick_window(prism["timestamp"], dlio["timestamp"], dlio["pose_orien"], args.seconds)
    print(f"window starts {t0 - prism['timestamp'][0]:.1f} s after the first prism sample")
    manifest = {"source": cfg.repo, "missions": {args.mission: {}}}
    for topic in cfg.topics:
        arrays, attrs = read_topic_group(archive_path(cfg, args.mission, topic), topic)
        if "timestamp" in arrays:
            t = arrays["timestamp"]
            sel = (t >= t0) & (t < t0 + args.seconds)
            arrays = {k: v[sel] for k, v in arrays.items() if k in KEEP}
        else:
            arrays = {}
        dest = out_dir / f"{topic}.tar"
        write_topic_archive(dest, topic, arrays, attrs)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        manifest["missions"][args.mission][topic] = {
            "path": f"{args.mission}/{topic}.tar",
            "size": dest.stat().st_size,
            "sha256": digest,
        }
        n = len(arrays.get("timestamp", np.empty(0)))
        print(f"{topic}: {n} rows, {dest.stat().st_size} bytes")
    (out_dir.parent / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
