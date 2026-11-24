import json
import shutil
from pathlib import Path

import pytest

from frle import config

FIXTURE = Path(__file__).parent / "fixtures" / "grandtour_10s"
MISSION = "2024-11-04-10-57-34"


@pytest.fixture
def cfg(tmp_path):
    """A config whose data dir holds a copy of the 10 s fixture as raw archives."""
    data = tmp_path / "data"
    shutil.copytree(FIXTURE / MISSION, data / "raw" / MISSION)
    shutil.copy(FIXTURE / "manifest.json", data / "manifest.json")
    return config.load(data_dir=data)


def refresh_checksum(cfg, mission, topic):
    """After a test modifies an archive on purpose, put its new checksum in the manifest."""
    from frle.download import archive_path, sha256

    manifest = json.loads(cfg.manifest_path.read_text())
    manifest["missions"][mission][topic]["sha256"] = sha256(archive_path(cfg, mission, topic))
    cfg.manifest_path.write_text(json.dumps(manifest))
