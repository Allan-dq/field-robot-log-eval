"""Paths and the mission/topic configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    base_url: str
    repo: str
    topics: dict[str, str]
    missions: list[str]
    data_dir: Path

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def lake_dir(self) -> Path:
        return self.data_dir / "lake"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"


def load(config_path: Path | None = None, data_dir: Path | None = None) -> Config:
    path = config_path or REPO / "config" / "missions.yaml"
    raw = yaml.safe_load(path.read_text())
    return Config(
        base_url=raw["source"]["base_url"],
        repo=raw["source"]["repo"],
        topics=dict(raw["topics"]),
        missions=[str(m) for m in raw["missions"]],
        data_dir=data_dir or REPO / "data",
    )
