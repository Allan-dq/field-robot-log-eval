"""Download GrandTour topic archives with checksums.

The manifest (data/manifest.json) lists, for every mission and topic, the path, size and sha256
reported by the Hugging Face tree API. Files are verified after download; a mismatch is an error.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import urllib.request
from pathlib import Path

import certifi

from frle.config import Config

_SSL = ssl.create_default_context(cafile=certifi.where())

TREE_API = "https://huggingface.co/api/datasets/{repo}/tree/main/{mission}/{folder}"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tree(cfg: Config, mission: str, folder: str) -> list[dict]:
    with urllib.request.urlopen(
        TREE_API.format(repo=cfg.repo, mission=mission, folder=folder), context=_SSL
    ) as r:
        return json.load(r)


def build_manifest(cfg: Config) -> dict:
    """Queries the Hugging Face tree API for the configured missions and topics."""
    manifest: dict = {"source": cfg.repo, "missions": {}}
    for mission in cfg.missions:
        entries = {Path(e["path"]).name: e for e in _tree(cfg, mission, "data")}
        files = {}
        for topic in cfg.topics:
            e = entries.get(f"{topic}.tar")
            if e is None:
                raise FileNotFoundError(f"{mission}: no archive for topic {topic}")
            files[topic] = {"path": e["path"], "size": e["size"], "sha256": e["lfs"]["oid"]}
        manifest["missions"][mission] = files
    cfg.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def load_manifest(cfg: Config) -> dict:
    return json.loads(cfg.manifest_path.read_text())


def archive_path(cfg: Config, mission: str, topic: str) -> Path:
    return cfg.raw_dir / mission / f"{topic}.tar"


def fetch(cfg: Config, mission: str, from_dir: Path | None = None) -> list[Path]:
    """Puts every archive of a mission in data/raw/<mission>/ and verifies its checksum.

    from_dir: copy from a local folder (<from_dir>/<mission>/<topic>.tar) instead of downloading.
    """
    files = load_manifest(cfg)["missions"][mission]
    out = []
    for topic, meta in files.items():
        dest = archive_path(cfg, mission, topic)
        if dest.exists() and sha256(dest) == meta["sha256"]:
            out.append(dest)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(".tar.part")
        if from_dir is not None:
            shutil.copyfile(from_dir / mission / f"{topic}.tar", part)
        else:
            with (
                urllib.request.urlopen(f"{cfg.base_url}/{meta['path']}", context=_SSL) as r,
                part.open("wb") as f,
            ):
                shutil.copyfileobj(r, f, 1 << 20)
        digest = sha256(part)
        if digest != meta["sha256"]:
            part.unlink()
            raise ValueError(f"{mission}/{topic}: sha256 {digest} != manifest {meta['sha256']}")
        part.replace(dest)
        out.append(dest)
    return out
