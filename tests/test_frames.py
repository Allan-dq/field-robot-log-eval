import numpy as np
import pytest

from conftest import MISSION
from frle.frames import PRISM_IN_BOX_BASE, StaticTF, prism_in_body
from frle.ingest import ingest_mission, parquet_path


@pytest.fixture
def tf(cfg):
    import pandas as pd

    ingest_mission(cfg, MISSION)
    return StaticTF(pd.read_parquet(parquet_path(cfg, "static_tf", MISSION, "tf")))


def test_stored_transform_is_inverse_of_urdf_joint(tf):
    """URDF joint cpt7_to_robot_base (grand_tour_box boxi_description.yaml): box_base sits at
    xyz (0.0764038, -0.0361, 0.2802790) in base. The stored entry must reproduce that when read
    as p_child = R p_parent + t."""
    origin_of_box_base_in_base = tf.point_in_frame([0, 0, 0], "box_base", "base")
    assert np.allclose(origin_of_box_base_in_base, [0.0764038, -0.0361, 0.2802790], atol=1e-6)


def test_round_trip(tf):
    p = np.array([0.1, -0.2, 0.3])
    there = tf.point_in_frame(p, "box_base", "hesai_lidar")
    assert np.allclose(tf.point_in_frame(there, "hesai_lidar", "box_base"), p)
    across = tf.point_in_frame(p, "hesai_lidar", "base")
    assert np.allclose(tf.point_in_frame(across, "base", "hesai_lidar"), p)


def test_lever_arms(tf):
    assert np.allclose(prism_in_body(tf, "cpt7_ie_tc_odometry"), PRISM_IN_BOX_BASE)
    # The prism sits on top of the robot, so it is above the base.
    assert prism_in_body(tf, "anymal_state_odometry")[2] > 0.3
