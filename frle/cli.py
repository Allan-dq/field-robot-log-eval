"""Command line: frle manifest | download | ingest | qc."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from frle import config, download, evaluate, gate, ingest, qc, summary
from frle.config import REPO


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="frle")
    p.add_argument("--data-dir", type=Path, default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("manifest", help="rebuild data/manifest.json from the Hugging Face tree API")
    d = sub.add_parser(
        "download", help="download and verify the archives of the configured missions"
    )
    d.add_argument("--mission", action="append")
    d.add_argument("--from-dir", type=Path, help="copy from <dir>/<mission>/<topic>.tar instead")
    i = sub.add_parser("ingest", help="archives -> Parquet lake")
    i.add_argument("--mission", action="append")
    i.add_argument("--force", action="store_true")
    q = sub.add_parser("qc", help="data-quality checks -> reports/qc.{json,md}")
    q.add_argument("--out", type=Path, default=REPO / "reports")
    e = sub.add_parser("eval", help="APE against the prism -> reports/eval.{json,md}")
    e.add_argument("--mission", action="append")
    e.add_argument("--out", type=Path, default=REPO / "reports")
    sm = sub.add_parser("summary", help="evaluation of all missions + summary -> reports/")
    sm.add_argument("--out", type=Path, default=REPO / "reports")
    g = sub.add_parser("gate", help="regression gate on the committed fixture")
    g.add_argument("--update-baseline", action="store_true")
    args = p.parse_args(argv)

    cfg = config.load(data_dir=args.data_dir)
    if args.cmd == "manifest":
        download.build_manifest(cfg)
        print(f"wrote {cfg.manifest_path}")
        return 0
    if args.cmd == "download":
        for mission in args.mission or cfg.missions:
            for path in download.fetch(cfg, mission, args.from_dir):
                print(f"ok {path}")
        return 0
    if args.cmd == "ingest":
        failed = 0
        for mission in args.mission or cfg.missions:
            for r in ingest.ingest_mission(cfg, mission, force=args.force):
                print(f"{r.status:8s} {r.mission} {r.topic} rows={r.rows} {r.error}")
                failed += r.status == "failed"
        return 1 if failed else 0
    if args.cmd == "qc":
        results = qc.run(cfg)
        qc.write_reports(results, args.out)
        for r in results:
            print(f"{r.status:5s} {r.mission} {r.topic}")
        return 1 if any(r.status == "fail" for r in results) else 0
    if args.cmd == "eval":
        results = [evaluate.evaluate_mission(cfg, m) for m in args.mission or cfg.missions]
        evaluate.write_reports(results, args.out)
        print((args.out / "eval.md").read_text())
        return 0
    if args.cmd == "summary":
        result = summary.run(cfg)
        summary.write_reports(result, args.out)
        print((args.out / "summary.md").read_text())
        return 0
    if args.cmd == "gate":
        if args.update_baseline:
            gate.write_baseline()
            print("baseline written")
            return 0
        _, problems = gate.gate()
        for line in problems:
            print(f"GATE FAIL {line}")
        print("gate passed" if not problems else f"gate failed: {len(problems)} problem(s)")
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
