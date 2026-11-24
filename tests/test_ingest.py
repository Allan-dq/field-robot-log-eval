import json

import numpy as np
import pyarrow.parquet as pq
import pytest

from conftest import MISSION, refresh_checksum
from frle import schema
from frle.archive import read_topic_group, write_topic_archive
from frle.db import connect
from frle.download import archive_path
from frle.ingest import ingest_mission, parquet_path


def by_topic(results):
    return {r.topic: r for r in results}


def test_ingest_fixture(cfg):
    res = by_topic(ingest_mission(cfg, MISSION))
    assert {r.status for r in res.values()} == {"ingested"}
    assert res["prism_position"].rows == 199
    assert res["cpt7_ie_tc_odometry"].rows == 2000
    assert res["tf"].rows == 29
    table = pq.read_table(parquet_path(cfg, "pose", MISSION, "dlio_map_odometry"))
    assert table.schema.equals(schema.TABLES["pose"])
    assert set(table.column("frame_id").to_pylist()) == {"dlio_map"}


def test_duckdb_views(cfg):
    ingest_mission(cfg, MISSION)
    con = connect(cfg)
    rows = dict(con.execute("SELECT topic, count(*) FROM pose GROUP BY topic").fetchall())
    assert rows == {
        "cpt7_ie_tc_odometry": 2000,
        "dlio_map_odometry": 100,
        "anymal_state_odometry": 199,
    }
    parents = con.execute("SELECT DISTINCT parent FROM static_tf ORDER BY 1").fetchall()
    assert ("box_base",) in parents


def test_rerun_is_idempotent(cfg):
    ingest_mission(cfg, MISSION)
    before = parquet_path(cfg, "position", MISSION, "prism_position").stat().st_mtime_ns
    res = by_topic(ingest_mission(cfg, MISSION))
    assert {r.status for r in res.values()} == {"skipped"}
    assert parquet_path(cfg, "position", MISSION, "prism_position").stat().st_mtime_ns == before
    assert {r.status for r in ingest_mission(cfg, MISSION, force=True)} == {"ingested"}


def test_quaternion_order_is_xyzw(cfg):
    """The robot stands upright, so the body z axis of the leg odometry must point up.
    With the wrong component order this fails."""
    ingest_mission(cfg, MISSION)
    q = pq.read_table(parquet_path(cfg, "pose", MISSION, "anymal_state_odometry")).to_pandas()
    x, y, w = q["qx"], q["qy"], q["qw"]
    body_z_up = 1 - 2 * (x**2 + y**2)  # z component of the rotated z axis
    assert (body_z_up > 0.9).all()
    assert np.allclose(np.linalg.norm(q[["qx", "qy", "qz", "qw"]], axis=1), 1, atol=1e-6)
    assert (w.abs() <= 1).all()


def test_truncated_archive_fails_only_its_topic(cfg):
    path = archive_path(cfg, MISSION, "dlio_map_odometry")
    data = path.read_bytes()
    path.write_bytes(data[: len(data) // 3])
    refresh_checksum(cfg, MISSION, "dlio_map_odometry")
    res = by_topic(ingest_mission(cfg, MISSION))
    assert res["dlio_map_odometry"].status == "failed"
    assert "archive" in res["dlio_map_odometry"].error or "array" in res["dlio_map_odometry"].error
    assert all(r.status == "ingested" for t, r in res.items() if t != "dlio_map_odometry")
    log = cfg.lake_dir / "_ingest_log" / MISSION / "dlio_map_odometry.json"
    assert json.loads(log.read_text())["status"] == "failed"


def test_checksum_mismatch_is_rejected(cfg):
    path = archive_path(cfg, MISSION, "prism_position")
    path.write_bytes(path.read_bytes() + b"\0")
    res = by_topic(ingest_mission(cfg, MISSION))
    assert res["prism_position"].status == "failed"
    assert "checksum" in res["prism_position"].error


def test_missing_array_is_reported(cfg):
    path = archive_path(cfg, MISSION, "anymal_state_odometry")
    arrays, attrs = read_topic_group(path, "anymal_state_odometry")
    del arrays["pose_orien"]
    write_topic_archive(path, "anymal_state_odometry", arrays, attrs)
    refresh_checksum(cfg, MISSION, "anymal_state_odometry")
    res = by_topic(ingest_mission(cfg, MISSION))
    assert res["anymal_state_odometry"].status == "failed"
    assert "pose_orien" in res["anymal_state_odometry"].error


def test_length_mismatch_is_reported(cfg):
    path = archive_path(cfg, MISSION, "prism_position")
    arrays, attrs = read_topic_group(path, "prism_position")
    arrays["point"] = arrays["point"][:-5]
    write_topic_archive(path, "prism_position", arrays, attrs)
    refresh_checksum(cfg, MISSION, "prism_position")
    res = by_topic(ingest_mission(cfg, MISSION))
    assert res["prism_position"].status == "failed"
    assert "different lengths" in res["prism_position"].error


def test_backfill_one_mission_leaves_others(cfg):
    ingest_mission(cfg, MISSION)
    other = cfg.lake_dir / "pose" / "other-mission"
    other.mkdir(parents=True)
    (other / "x.parquet").write_bytes(b"keep")
    ingest_mission(cfg, MISSION, force=True)
    assert (other / "x.parquet").read_bytes() == b"keep"


def test_schema_rejects_wrong_columns():
    import pyarrow as pa

    with pytest.raises(schema.SchemaError):
        schema.conform("position", pa.table({"t": [1.0]}))
