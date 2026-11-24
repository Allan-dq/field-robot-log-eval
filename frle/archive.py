"""Write a GrandTour-style topic archive (a tar holding one zarr v2 group). Used for test fixtures."""

from __future__ import annotations

import tarfile
import tempfile
from pathlib import Path

import numpy as np
import zarr


def write_topic_archive(path: Path, topic: str, arrays: dict[str, np.ndarray], attrs: dict) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        group = zarr.open_group(str(Path(tmp) / topic), mode="w")
        group.attrs.update(attrs)
        for name, values in arrays.items():
            group.create_dataset(name, data=np.asarray(values))
        path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(path, "w") as tar:
            tar.add(Path(tmp) / topic, arcname=topic)


def read_topic_group(path: Path, topic: str) -> tuple[dict[str, np.ndarray], dict]:
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(path) as tar:
            tar.extractall(tmp, filter="data")
        group = zarr.open_group(str(Path(tmp) / topic), mode="r")
        return {k: np.asarray(group[k]) for k in group.array_keys()}, dict(group.attrs)
