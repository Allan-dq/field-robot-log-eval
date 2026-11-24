"""Cut a 10 s window of every configured topic from one GrandTour mission into tests/fixtures.

The window starts at the first prism sample, so ground truth and all odometry topics overlap.
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


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mission", default="2024-11-04-10-57-34")
    p.add_argument("--seconds", type=float, default=10.0)
    args = p.parse_args()
    cfg = config.load()
    out_dir = REPO / "tests" / "fixtures" / "grandtour_10s" / args.mission
    prism, _ = read_topic_group(archive_path(cfg, args.mission, "prism_position"), "prism_position")
    t0 = float(prism["timestamp"][0])
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
