import pytest

from frle import gate
from frle.faults import FAULTS, run_all


def test_gate_passes_on_unchanged_fixture():
    _, problems = gate.gate()
    assert problems == []


@pytest.fixture(scope="module")
def fault_results():
    return {r["fault"]: r for r in run_all()}


@pytest.mark.parametrize("name", [f.name for f in FAULTS])
def test_seeded_fault_is_caught(fault_results, name):
    assert fault_results[name]["caught"], fault_results[name]


def test_missing_frame_names_the_frame(fault_results):
    assert any("hesai_lidar" in p for p in fault_results["missing_frame"]["problems"])
