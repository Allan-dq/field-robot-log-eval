import numpy as np
import pandas as pd
import pytest

from conftest import MISSION
from frle import qc
from frle.ingest import ingest_mission, parquet_path


@pytest.fixture
def lake(cfg):
    ingest_mission(cfg, MISSION)
    return cfg


def load(cfg, table, topic):
    return pd.read_parquet(parquet_path(cfg, table, MISSION, topic))


def failed(checks):
    return {c.name for c in checks if not c.passed}


def test_clean_fixture_passes(lake):
    results = {r.topic: r for r in qc.run(lake)}
    assert set(results) == {
        "prism_position",
        "cpt7_ie_tc_odometry",
        "dlio_map_odometry",
        "anymal_state_odometry",
    }
    for topic in ("cpt7_ie_tc_odometry", "dlio_map_odometry", "anymal_state_odometry"):
        assert results[topic].status == "pass", (topic, failed(results[topic].checks))
    # The real prism stream is irregular even in this short window (total-station tracking).
    assert failed(results["prism_position"].checks) == {"regular_rate"}


def test_reports_are_written(lake, tmp_path):
    qc.write_reports(qc.run(lake), tmp_path)
    assert "prism_position" in (tmp_path / "qc.md").read_text()
    assert (tmp_path / "qc.json").exists()


# Seeded faults: each one must be caught by the named check, and only the expected checks fail.
def seed_duplicate(df):
    df.loc[10, "t"] = df.loc[9, "t"]
    return df


def seed_backwards(df):
    df.loc[[10, 11]] = df.loc[[11, 10]].to_numpy()
    return df


def seed_nan(df):
    df.loc[20, "x"] = np.nan
    return df


def seed_bad_quaternion(df):
    df.loc[5, ["qx", "qy", "qz", "qw"]] = [0.0, 0.0, 0.0, 2.0]
    return df


def seed_gap(df):
    return df.drop(index=range(30, 60)).reset_index(drop=True)


def seed_jump(df):
    df.loc[40:, "x"] += 5.0
    return df


@pytest.mark.parametrize(
    "seed, expected",
    [
        (seed_duplicate, {"unique_time"}),
        (seed_backwards, {"monotonic_time"}),
        (seed_nan, {"finite_values"}),
        (seed_bad_quaternion, {"unit_quaternion"}),
        (seed_gap, {"no_gaps"}),
        (seed_jump, {"no_jumps"}),
    ],
)
def test_seeded_fault_is_caught(lake, seed, expected):
    df = seed(load(lake, "pose", "dlio_map_odometry"))
    _, checks = qc.check_series(df, "pose", mission_span=10.0)
    assert expected <= failed(checks)
    # rate regularity may also drop when samples are removed or swapped
    assert failed(checks) - expected <= {"regular_rate"}


def test_partial_coverage_is_flagged(lake):
    df = load(lake, "pose", "dlio_map_odometry")
    _, checks = qc.check_series(df, "pose", mission_span=20.0)
    assert failed(checks) == {"coverage"}


def test_empty_topic_fails(lake):
    df = load(lake, "position", "prism_position").iloc[:0]
    _, checks = qc.check_series(df, "position", mission_span=10.0)
    assert failed(checks) == {"non_empty"}
