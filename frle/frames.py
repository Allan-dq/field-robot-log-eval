"""Frames and the prism lever arm.

Static transform convention in the GrandTour zarr `tf` attribute: an entry (parent, child, t, q)
maps parent coordinates to child coordinates, p_child = R(q) p_parent + t. That is the inverse of the
usual ROS reading (pose of the child in the parent). Evidence, checked by tests/test_frames.py:
the stored `base -> box_base` entry inverted gives exactly the URDF joint `cpt7_to_robot_base`
(xyz 0.0764038 -0.0361 0.2802790, rpy 3.1415126 0 0) in leggedrobotics/grand_tour_box,
box_model/box_model/urdf/box/boxi_description.yaml. See docs/evaluation.md.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial.transform import Rotation

# Prism position in box_base, from the calibrated URDF joint `box_base_to_prism` in
# leggedrobotics/grand_tour_box, box_model/box_model/urdf/box/boxi_description.yaml.
# It is not fitted on the evaluation data. docs/evaluation.md has the cross-check against the data.
PRISM_IN_BOX_BASE = np.array([0.3088378015503127, -0.038312997211241984, -0.2349441159711169])

# Body frame of each estimator's pose. dlio: GrandTour's own evo config
# (box_utils/box_auto/cfg/evo_evaluations.yaml: topic lidar_map_odometry, frame hesai_lidar).
# anymal: the leg odometry estimates the robot base. cpt7: the CPT7 IMU, which tf puts at box_base.
BODY_FRAME = {
    "dlio_map_odometry": "hesai_lidar",
    "anymal_state_odometry": "base",
    "cpt7_ie_tc_odometry": "cpt7_imu",
}


class StaticTF:
    """Static transforms of one mission, as stored (p_child = R p_parent + t)."""

    def __init__(self, table: pd.DataFrame):
        self._edges: dict[str, tuple[str, Rotation, np.ndarray]] = {}
        for row in table.itertuples():
            q = Rotation.from_quat([row.qx, row.qy, row.qz, row.qw])
            self._edges[row.child] = (row.parent, q, np.array([row.tx, row.ty, row.tz]))

    def _chain_to(self, frame: str) -> list[str]:
        chain = [frame]
        while chain[-1] in self._edges:
            chain.append(self._edges[chain[-1]][0])
        return chain

    def point_in_frame(self, point: np.ndarray, src: str, dst: str) -> np.ndarray:
        """Expresses a point given in frame `src` in frame `dst` (both in the static tree)."""
        up = self._chain_to(src)
        down = self._chain_to(dst)
        common = next(f for f in up if f in down)
        p = np.asarray(point, dtype=float)
        for frame in up[: up.index(common)]:  # child -> parent: p_parent = R^T (p_child - t)
            _, q, t = self._edges[frame]
            p = q.inv().apply(p - t)
        for frame in reversed(down[: down.index(common)]):  # parent -> child
            _, q, t = self._edges[frame]
            p = q.apply(p) + t
        return p


def prism_in_body(tf: StaticTF, topic: str) -> np.ndarray:
    return tf.point_in_frame(PRISM_IN_BOX_BASE, "box_base", BODY_FRAME[topic])
