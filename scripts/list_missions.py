"""Lists the GrandTour missions this pipeline uses and writes them into config/missions.yaml.

Rule: every public mission on Hugging Face that has all required topics (prism ground truth,
DLIO, leg odometry, tf). Optional topics are kept only for the missions listed under
optional_topics in the config. Run: python scripts/list_missions.py
"""

import json
import ssl
import urllib.request

import certifi
import yaml

from frle.config import REPO

TREE = "https://huggingface.co/api/datasets/{repo}/tree/main{path}"
CTX = ssl.create_default_context(cafile=certifi.where())


def tree(repo: str, path: str = "") -> list[dict]:
    with urllib.request.urlopen(TREE.format(repo=repo, path=path), context=CTX) as r:
        return json.load(r)


def main() -> None:
    path = REPO / "config" / "missions.yaml"
    raw = yaml.safe_load(path.read_text())
    repo = raw["source"]["repo"]
    optional = set(raw.get("optional_topics", {}))
    required = [t for t in raw["topics"] if t not in optional]
    keep, skipped = [], {}
    for entry in tree(repo):
        if entry["type"] != "directory":
            continue
        mission = entry["path"]
        try:
            names = {e["path"].rsplit("/", 1)[-1] for e in tree(repo, f"/{mission}/data")}
        except OSError as err:
            skipped[mission] = f"no data folder ({err})"
            continue
        missing = [t for t in required if f"{t}.tar" not in names]
        if missing:
            skipped[mission] = f"missing {missing}"
        else:
            keep.append(mission)
    text = path.read_text()
    head = text[: text.index("missions:")]
    body = "missions:\n" + "".join(f'  - "{m}"\n' for m in sorted(keep))
    path.write_text(head + body)
    print(f"{len(keep)} missions kept, {len(skipped)} skipped")
    for m, why in sorted(skipped.items()):
        print(f"  skipped {m}: {why}")


if __name__ == "__main__":
    main()
