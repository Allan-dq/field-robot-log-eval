"""Seeded faults for the regression gate. Each fault changes the fixture data or, through a patch,
the code, the way a real bug or data problem would. See docs/regression_gate.md."""

from __future__ import annotations

import contextlib
import json
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import numpy as np

from frle import evaluate, frames, gate
from frle.archive import read_topic_group, write_topic_archive
from frle.config import Config
from frle.download import archive_path, sha256


@dataclass(frozen=True)
class Fault:
    name: str
    kind: str  # "data" or "code"
    description: str
    apply: Callable[[Config], contextlib.AbstractContextManager]


def _edit(cfg: Config, topic: str, change: Callable[[dict, dict], None]) -> None:
    """Rewrites one topic archive of every mission and updates the manifest checksum, so the fault
    looks like bad data at the source rather than a corrupted download."""
    manifest = json.loads(cfg.manifest_path.read_text())
    for mission in cfg.missions:
        path = archive_path(cfg, mission, topic)
        arrays, attrs = read_topic_group(path, topic)
        change(arrays, attrs)
        write_topic_archive(path, topic, arrays, attrs)
        manifest["missions"][mission][topic]["sha256"] = sha256(path)
    cfg.manifest_path.write_text(json.dumps(manifest))


def data_fault(topic: str, change: Callable[[dict, dict], None]):
    @contextlib.contextmanager
    def apply(cfg: Config) -> Iterator[None]:
        _edit(cfg, topic, change)
        yield

    return apply


def code_fault(target: str, replacement):
    @contextlib.contextmanager
    def apply(cfg: Config) -> Iterator[None]:
        with mock.patch(target, replacement):
            yield

    return apply


def _duplicate(a, _):
    a["timestamp"][10] = a["timestamp"][9]


def _backwards(a, _):
    for k in ("timestamp", "pose_pos", "pose_orien", "sequence_id"):
        a[k][[10, 11]] = a[k][[11, 10]]


def _nan(a, _):
    a["pose_pos"][20, 0] = np.nan


def _bad_quat(a, _):
    a["pose_orien"][5] = [0.0, 0.0, 0.0, 2.0]


def _drop_share(share: float, seed: int = 0):
    def change(a, _):
        keep = np.random.default_rng(seed).random(len(a["timestamp"])) >= share
        for k in list(a):
            a[k] = a[k][keep]

    return change


def _prism_gap(seconds: float):
    def change(a, _):
        t = a["timestamp"]
        mid = t[0] + 0.5 * (t[-1] - t[0])
        keep = (t < mid) | (t >= mid + seconds)
        for k in list(a):
            a[k] = a[k][keep]

    return change


def _time_offset(dt: float):
    def change(a, _):
        a["timestamp"] = a["timestamp"] + dt

    return change


def _drop_frame(frame: str):
    def change(_, attrs):
        attrs["tf"] = {k: v for k, v in attrs["tf"].items() if k != frame}

    return change


@contextlib.contextmanager
def _truncate(cfg: Config) -> Iterator[None]:
    manifest = json.loads(cfg.manifest_path.read_text())
    for mission in cfg.missions:
        path = archive_path(cfg, mission, "cpt7_ie_tc_odometry")
        data = path.read_bytes()
        path.write_bytes(data[: len(data) // 2])
        manifest["missions"][mission]["cpt7_ie_tc_odometry"]["sha256"] = sha256(path)
    cfg.manifest_path.write_text(json.dumps(manifest))
    yield


class _RosReadingTF(frames.StaticTF):
    """Reads the stored transforms the usual ROS way (pose of the child in the parent)."""

    def __init__(self, table):
        super().__init__(table)
        self._edges = {
            child: (parent, q.inv(), -q.inv().apply(t))
            for child, (parent, q, t) in self._edges.items()
        }


_orig_prism_trajectory = evaluate.prism_trajectory


def _wxyz_read(est, lever_arm):
    est = est.rename(columns={"qx": "qw", "qy": "qx", "qz": "qy", "qw": "qz"})
    return _orig_prism_trajectory(est, lever_arm)


def _nearest_pose(ref, est):
    """Association that snaps to the nearest estimate pose instead of interpolating."""
    import copy

    from evo.core import sync

    i_ref, i_est = sync.matching_time_indices(ref.timestamps, est.timestamps, evaluate.MAX_DIFF_S)
    r, e = copy.deepcopy(ref), copy.deepcopy(est)
    r.reduce_to_ids(i_ref)
    e.reduce_to_ids(i_est)
    e.timestamps = r.timestamps.copy()
    return r, e


FAULTS: list[Fault] = [
    Fault(
        "duplicate_stamp",
        "data",
        "DLIO: one timestamp repeated",
        data_fault("dlio_map_odometry", _duplicate),
    ),
    Fault(
        "backward_stamp",
        "data",
        "DLIO: two messages swapped",
        data_fault("dlio_map_odometry", _backwards),
    ),
    Fault(
        "nan_position", "data", "DLIO: one position is NaN", data_fault("dlio_map_odometry", _nan)
    ),
    Fault(
        "bad_quaternion",
        "data",
        "leg odometry: one quaternion of norm 2",
        data_fault("anymal_state_odometry", _bad_quat),
    ),
    Fault(
        "dropped_messages",
        "data",
        "DLIO: 30 % of messages dropped at random",
        data_fault("dlio_map_odometry", _drop_share(0.3)),
    ),
    Fault(
        "ground_truth_gap",
        "data",
        "prism: 3 s of ground truth missing",
        data_fault("prism_position", _prism_gap(3.0)),
    ),
    Fault(
        "time_offset",
        "data",
        "DLIO: clock 0.1 s late",
        data_fault("dlio_map_odometry", _time_offset(0.1)),
    ),
    Fault("truncated_archive", "data", "CPT7: archive cut in half", _truncate),
    Fault(
        "missing_frame",
        "data",
        "tf: hesai_lidar frame missing",
        data_fault("tf", _drop_frame("hesai_lidar")),
    ),
    Fault(
        "no_lever_arm",
        "code",
        "prism lever arm ignored",
        code_fault("frle.evaluate.prism_in_body", lambda tf, topic: np.zeros(3)),
    ),
    Fault(
        "wrong_body_frame",
        "code",
        "DLIO body frame set to base",
        code_fault("frle.frames.BODY_FRAME", {**frames.BODY_FRAME, "dlio_map_odometry": "base"}),
    ),
    Fault(
        "ros_tf_reading",
        "code",
        "static tf read the usual ROS way",
        code_fault("frle.evaluate.StaticTF", _RosReadingTF),
    ),
    Fault(
        "quaternion_order",
        "code",
        "pose quaternions read as (w, x, y, z)",
        code_fault("frle.evaluate.prism_trajectory", _wxyz_read),
    ),
    Fault(
        "nearest_association",
        "code",
        "nearest pose instead of interpolation",
        code_fault("frle.evaluate.associate", _nearest_pose),
    ),
]


def run_all(fixture: Path | None = None) -> list[dict]:
    rules = gate.load_rules()
    fixture = fixture or gate.REPO / rules["fixture"]
    baseline = json.loads((gate.REPO / rules["baseline"]).read_text())
    out = []
    for fault in FAULTS:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = gate.prepare(Path(tmp), fixture)
            with fault.apply(cfg):
                current = gate.run_pipeline(cfg)
            problems = gate.compare(current, baseline, rules)
        out.append(
            {
                "fault": fault.name,
                "kind": fault.kind,
                "description": fault.description,
                "caught": bool(problems),
                "problems": problems,
            }
        )
    return out
