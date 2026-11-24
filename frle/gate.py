"""Regression gate: run the pipeline on the committed fixture and compare with a baseline.
Rules: config/gate.yaml, reasons: docs/regression_gate.md."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import yaml

from frle import config, evaluate, ingest, qc
from frle.config import REPO


def load_rules(path: Path | None = None) -> dict:
    return yaml.safe_load((path or REPO / "config" / "gate.yaml").read_text())


def prepare(workdir: Path, fixture: Path) -> config.Config:
    data = workdir / "data"
    (data / "raw").mkdir(parents=True)
    for mission_dir in sorted(p for p in fixture.iterdir() if p.is_dir()):
        shutil.copytree(mission_dir, data / "raw" / mission_dir.name)
    shutil.copy(fixture / "manifest.json", data / "manifest.json")
    missions = sorted(json.loads((fixture / "manifest.json").read_text())["missions"])
    cfg = config.load(data_dir=data)
    return config.Config(cfg.base_url, cfg.repo, cfg.topics, missions, data)  # all topics


def run_pipeline(cfg: config.Config) -> dict:
    out: dict = {"ingest": {}, "qc": {}, "eval": {}}
    for mission in cfg.missions:
        for r in ingest.ingest_mission(cfg, mission):
            out["ingest"][f"{mission}/{r.topic}"] = r.status
    for r in qc.run(cfg):
        out["qc"][f"{r.mission}/{r.topic}"] = {
            "status": r.status,
            "failed_checks": sorted(c.name for c in r.checks if not c.passed),
        }
    for mission in cfg.missions:
        try:
            res = evaluate.evaluate_mission(cfg, mission)
        except Exception as err:  # noqa: BLE001 - a crash in the evaluation is a gate failure
            out["eval_error"] = f"{type(err).__name__}: {err}"
            continue
        for s in res["scores"]:
            out["eval"][f"{mission}/{s['topic']}"] = {"rmse_m": s["rmse_m"], "pairs": s["pairs"]}
    return out


def compare(current: dict, baseline: dict, rules: dict) -> list[str]:
    r = rules["rules"]
    problems = []
    if r.get("all_topics_ingested"):
        for key in baseline["ingest"]:
            status = current["ingest"].get(key, "missing")
            if status == "failed" or status == "missing":
                problems.append(f"ingest: {key} {status}")
    for key, q in current["qc"].items():
        if r.get("qc_no_fail") and q["status"] == "fail":
            problems.append(f"qc: {key} fails {q['failed_checks']}")
        if r.get("qc_no_new_failed_checks"):
            before = set(baseline["qc"].get(key, {}).get("failed_checks", []))
            new = sorted(set(q["failed_checks"]) - before)
            if new:
                problems.append(f"qc: {key} newly failing {new}")
    if "eval_error" in current:
        problems.append(f"eval: crashed ({current['eval_error']})")
    for key, b in baseline["eval"].items():
        c = current["eval"].get(key)
        if c is None:
            if r.get("all_estimators_scored"):
                problems.append(f"eval: {key} not scored")
            continue
        limit = b["rmse_m"] + r["rmse_abs_margin_m"]
        if not c["rmse_m"] <= limit:
            problems.append(f"eval: {key} RMSE {c['rmse_m']:.4f} m > limit {limit:.4f} m")
        if c["pairs"] < (1 - r["pairs_max_drop"]) * b["pairs"]:
            problems.append(
                f"eval: {key} pairs {c['pairs']} < {1 - r['pairs_max_drop']:.0%} of {b['pairs']}"
            )
    return problems


def gate(fixture: Path | None = None, rules_path: Path | None = None) -> tuple[dict, list[str]]:
    rules = load_rules(rules_path)
    fixture = fixture or REPO / rules["fixture"]
    baseline = json.loads((REPO / rules["baseline"]).read_text())
    with tempfile.TemporaryDirectory() as tmp:
        current = run_pipeline(prepare(Path(tmp), fixture))
    return current, compare(current, baseline, rules)


def write_baseline(rules_path: Path | None = None) -> dict:
    rules = load_rules(rules_path)
    with tempfile.TemporaryDirectory() as tmp:
        current = run_pipeline(prepare(Path(tmp), REPO / rules["fixture"]))
    (REPO / rules["baseline"]).write_text(json.dumps(current, indent=2) + "\n")
    return current
