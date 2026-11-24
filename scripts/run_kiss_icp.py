"""Run KISS-ICP on the raw Livox clouds of one mission and store the poses as a lake topic.

Rules: docs/kiss_icp.md. Pose stamp: the latest point time of each scan, because KISS-ICP 1.3.0
deskews every point to the end of the scan (Preprocessing.cpp: exp((stamp - 1.0) * omega) on
normalized point times), so the registered pose belongs to that instant.
Run: python scripts/run_kiss_icp.py [--mission 2024-11-04-10-57-34]
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import tarfile
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zarr
from kiss_icp.config import load_config
from kiss_icp.kiss_icp import KissICP
from scipy.spatial.transform import Rotation

from frle import config, schema
from frle.config import REPO
from frle.download import archive_path
from frle.ingest import parquet_path

TOPIC = "kiss_icp_livox"
SOURCE = "livox_points"


def open_clouds(cfg, mission):
    work = cfg.data_dir / "work" / mission
    group_dir = work / SOURCE
    if not group_dir.exists():
        work.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path(cfg, mission, SOURCE)) as tar:
            tar.extractall(work, filter="data")
    return zarr.open_group(str(group_dir), mode="r")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mission", default="2024-11-04-10-57-34")
    args = p.parse_args()
    cfg = config.load()
    g = open_clouds(cfg, args.mission)
    valid = np.asarray(g["valid"])[:, 0]
    n_scans = len(valid)
    kiss_cfg = load_config(None)  # all defaults
    odom = KissICP(kiss_cfg)
    stamps, poses = np.empty(n_scans), np.empty((n_scans, 4, 4))
    block = 512
    t0 = time.perf_counter()
    for start in range(0, n_scans, block):
        pts_block = np.asarray(g["points"][start : start + block])
        time_block = np.asarray(g["time"][start : start + block])
        for j in range(len(pts_block)):
            i = start + j
            n = int(valid[i])
            pts = pts_block[j, :n].astype(np.float64)
            t_ns = time_block[j, :n]
            rel = (t_ns - t_ns.min()) * 1e-9
            odom.register_frame(pts, rel)
            poses[i] = odom.last_pose
            stamps[i] = t_ns.max() * 1e-9
    runtime = time.perf_counter() - t0

    q = Rotation.from_matrix(poses[:, :3, :3]).as_quat()
    xyz = poses[:, :3, 3]
    table = pa.table(
        {
            "mission": [args.mission] * n_scans,
            "topic": [TOPIC] * n_scans,
            "frame_id": ["kiss_icp_map"] * n_scans,
            "seq": np.arange(n_scans, dtype=np.int64),
            "t": stamps,
            "x": xyz[:, 0],
            "y": xyz[:, 1],
            "z": xyz[:, 2],
            "qx": q[:, 0],
            "qy": q[:, 1],
            "qz": q[:, 2],
            "qw": q[:, 3],
        }
    )
    out = parquet_path(cfg, "pose", args.mission, TOPIC)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(schema.conform("pose", table), out)
    meta = {
        "mission": args.mission,
        "kiss_icp_version": importlib.metadata.version("kiss-icp"),
        "config": kiss_cfg.model_dump(),
        "scans": n_scans,
        "points_per_scan_median": float(np.median(valid)),
        "runtime_s": round(runtime, 1),
        "scans_per_s": round(n_scans / runtime, 1),
        "path_length_m": float(np.linalg.norm(np.diff(xyz, axis=0), axis=1).sum()),
    }
    (REPO / "reports" / f"kiss_icp_run_{args.mission}.json").write_text(
        json.dumps(meta, indent=2) + "\n"
    )
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
