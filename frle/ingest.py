"""Read GrandTour zarr topic archives into canonical Parquet tables.

Layout: data/lake/<table>/<mission>/<topic>.parquet, plus data/lake/_ingest_log/<mission>/<topic>.json.
Re-running is idempotent: a topic is skipped when its archive checksum and the schema version match
the log. One mission can be (re)ingested without touching the others. A broken archive fails only
its own topic.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import zarr

from frle import schema
from frle.config import Config
from frle.download import archive_path, load_manifest, sha256


class IngestError(RuntimeError):
    pass


@dataclass
class TopicResult:
    mission: str
    topic: str
    table: str
    status: str  # "ingested", "skipped" or "failed"
    rows: int = 0
    sha256: str = ""
    schema_version: int = schema.SCHEMA_VERSION
    error: str = ""
    ingested_at: str = ""


def _open_archive(tar_path: Path, workdir: Path, topic: str) -> zarr.Group:
    try:
        with tarfile.open(tar_path) as tar:
            tar.extractall(workdir, filter="data")
    except (tarfile.TarError, EOFError, OSError) as err:
        raise IngestError(f"truncated or corrupt archive: {err}") from err
    group_dir = workdir / topic
    if not group_dir.is_dir():
        raise IngestError(f"archive has no '{topic}' group")
    return zarr.open_group(str(group_dir), mode="r")


def _array(group: zarr.Group, name: str) -> np.ndarray:
    if name not in group:
        raise IngestError(f"missing array '{name}'")
    try:
        return np.asarray(group[name])
    except Exception as err:  # a missing or short chunk raises inside zarr/numcodecs
        raise IngestError(f"cannot read array '{name}': {err}") from err


def _time_series(group: zarr.Group, mission: str, topic: str, table: str) -> pa.Table:
    t = _array(group, "timestamp")
    cols: dict[str, np.ndarray] = {"t": t, "seq": _array(group, "sequence_id").astype(np.int64)}
    xyz = _array(group, "point" if table == "position" else "pose_pos")
    cols |= {"x": xyz[:, 0], "y": xyz[:, 1], "z": xyz[:, 2]}
    if table == "pose":
        q = _array(group, "pose_orien")  # stored as (x, y, z, w)
        cols |= {"qx": q[:, 0], "qy": q[:, 1], "qz": q[:, 2], "qw": q[:, 3]}
    lengths = {k: len(v) for k, v in cols.items()}
    if len(set(lengths.values())) != 1:
        raise IngestError(f"arrays have different lengths: {lengths}")
    n = len(t)
    frame_id = str(group.attrs.get("frame_id", ""))
    data = {"mission": [mission] * n, "topic": [topic] * n, "frame_id": [frame_id] * n} | cols
    return pa.table(data)


def _static_tf(group: zarr.Group, mission: str) -> pa.Table:
    tfs = group.attrs.get("tf")
    if not tfs:
        raise IngestError("no 'tf' attribute")
    rows = []
    for child, tf in tfs.items():
        r, tr = tf["rotation"], tf["translation"]
        rows.append(
            {
                "mission": mission,
                "parent": tf["base_frame_id"],
                "child": tf.get("child_frame_id", child),
                "tx": tr["x"],
                "ty": tr["y"],
                "tz": tr["z"],
                "qx": r["x"],
                "qy": r["y"],
                "qz": r["z"],
                "qw": r["w"],
            }
        )
    return pa.Table.from_pylist(rows)


def read_topic(tar_path: Path, mission: str, topic: str, table: str) -> pa.Table:
    with tempfile.TemporaryDirectory() as tmp:
        group = _open_archive(tar_path, Path(tmp), topic)
        if table == "static_tf":
            out = _static_tf(group, mission)
        else:
            out = _time_series(group, mission, topic, table)
    return schema.conform(table, out)


def parquet_path(cfg: Config, table: str, mission: str, topic: str) -> Path:
    return cfg.lake_dir / table / mission / f"{topic}.parquet"


def _log_path(cfg: Config, mission: str, topic: str) -> Path:
    return cfg.lake_dir / "_ingest_log" / mission / f"{topic}.json"


def _write_atomic(path: Path, write) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    tmp.replace(path)


def ingest_mission(cfg: Config, mission: str, force: bool = False) -> list[TopicResult]:
    files = load_manifest(cfg)["missions"][mission]
    results = []
    for topic, table in cfg.topics_for(mission).items():
        if table not in schema.TABLES:  # raw sensor archives (point clouds) are not ingested
            continue
        res = TopicResult(mission=mission, topic=topic, table=table, status="failed")
        tar_path = archive_path(cfg, mission, topic)
        out = parquet_path(cfg, table, mission, topic)
        log = _log_path(cfg, mission, topic)
        try:
            if not tar_path.exists():
                raise IngestError(f"archive not found: {tar_path}")
            res.sha256 = sha256(tar_path)
            if res.sha256 != files[topic]["sha256"]:
                raise IngestError("archive checksum does not match the manifest")
            if not force and out.exists() and log.exists():
                prev = json.loads(log.read_text())
                if (
                    prev.get("status") in ("ingested", "skipped")
                    and prev.get("sha256") == res.sha256
                    and prev.get("schema_version") == schema.SCHEMA_VERSION
                ):
                    res.status, res.rows = "skipped", prev["rows"]
                    res.ingested_at = prev["ingested_at"]
                    results.append(res)
                    continue
            data = read_topic(tar_path, mission, topic, table)
            _write_atomic(out, lambda p, d=data: pq.write_table(d, p))
            res.status, res.rows = "ingested", data.num_rows
            res.ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
        except (IngestError, schema.SchemaError) as err:
            res.error = str(err)
        text = json.dumps(asdict(res), indent=2) + "\n"
        _write_atomic(log, lambda p, t=text: p.write_text(t))
        results.append(res)
    return results
