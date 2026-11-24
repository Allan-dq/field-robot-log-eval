from unittest import mock

from conftest import MISSION
from frle import summary
from frle.ingest import ingest_mission


def test_short_mission_is_excluded_with_reason(cfg):
    ingest_mission(cfg, MISSION)
    res = summary.run(cfg)
    assert res["summary"] == {}
    assert {e["estimator"] for e in res["excluded"]} == {
        "dlio_map_odometry",
        "anymal_state_odometry",
        "cpt7_ie_tc_odometry",
    }
    assert all("pairs <" in e["reason"] for e in res["excluded"])


def test_summary_and_paired(cfg, tmp_path):
    ingest_mission(cfg, MISSION)
    with mock.patch.object(summary, "MIN_PAIRS", 100):
        res = summary.run(cfg)
    assert res["summary"]["dlio_map_odometry"]["missions"] == 1
    p = res["paired"]
    assert p["missions"] == 1 and p["a_better"] + p["b_better"] == 1
    summary.write_reports(res, tmp_path)
    assert "DLIO better in" in (tmp_path / "summary.md").read_text()


def test_qc_fail_excludes_mission(cfg):
    import pandas as pd

    from frle.ingest import parquet_path

    ingest_mission(cfg, MISSION)
    path = parquet_path(cfg, "pose", MISSION, "dlio_map_odometry")
    df = pd.read_parquet(path)
    df.loc[3, "t"] = df.loc[2, "t"]
    df.to_parquet(path)
    res = summary.run(cfg)
    assert res["missions"] == []
    assert "QC fail" in res["excluded"][0]["reason"]
