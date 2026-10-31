"""Read logs/requests.jsonl: what the evaluator sent and what we answered.

Prints real PII from the evaluator's requests: run it locally only, never paste its output anywhere.

    .venv/bin/python scripts/requests_report.py                      # summary per endpoint
    .venv/bin/python scripts/requests_report.py --anonymize          # every /anonymize, field by field
    .venv/bin/python scripts/requests_report.py --anonymize --since 2026-10-31T22:00
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path, since: str | None) -> list[dict]:
    entries = []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if since and entry["ts"] < since:
            continue
        entries.append(entry)
    return entries


def route(path: str) -> str:
    return re.sub(r"^/v1/run/[^/]+$", "/v1/run/{job_id}", path)


def summary(entries: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for e in entries:
        groups[(e["method"], route(e["path"]), e["status"])].append(e)
    print(f"{len(entries)} requests, {entries[0]['ts']} → {entries[-1]['ts']}\n" if entries else "sin requests")
    for (method, path, status), group in sorted(groups.items()):
        ms = [e["ms"] for e in group]
        print(f"{method:5} {path:28} {status}  x{len(group):<4} prom {sum(ms) / len(ms):8.1f} ms  máx {max(ms):8.1f} ms")
    for e in entries:
        if e["status"] >= 400 or e["error"]:
            print(f"\n{e['ts']} {e['method']} {e['path']} -> {e['status']}")
            print(json.dumps(e["response"], ensure_ascii=False, indent=2) if e["response"] else "")
            if e["error"]:
                print(e["error"])


def leaves(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, f"{prefix}.{k}" if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def anonymize(entries: list[dict]) -> None:
    for e in entries:
        if e["path"] != "/v1/anonymize":
            continue
        req = e["request"] if isinstance(e["request"], dict) else {}
        records = req.get("records", [])
        print("=" * 100)
        print(f"{e['ts']}  {e['id']}  source={req.get('source')}  {len(records)} registros  {e['status']}  {e['ms']} ms")
        if e["status"] != 200 or not isinstance(e["response"], dict):
            print(json.dumps(e["response"], ensure_ascii=False, indent=2))
            continue
        for original, anon in zip(records, e["response"]["records"]):
            print(f"\n  [{original.get('id')}]")
            out = dict(leaves(anon))
            for key, value in leaves(original):
                if out.get(key) == value:
                    print(f"      {key}: {value}")
                else:
                    print(f"    - {key}: {value}")
                    print(f"    + {key}: {out.get(key)}")
        print("\n  entidades:")
        for ent in e["response"]["entities"]:
            if ent.get("kept"):
                print(f"    kept    {ent['originals']}")
            else:
                pseudo = {k: v for k, v in (ent.get("pseudonyms") or {}).items() if v}
                print(f"    {ent['entity_id']:10} {ent['originals']} -> {pseudo}  en {ent['records']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=ROOT / "logs" / "requests.jsonl")
    parser.add_argument("--since", help="ISO UTC, p. ej. 2026-10-31T22:00")
    parser.add_argument("--anonymize", action="store_true", help="detalle de cada /anonymize")
    args = parser.parse_args()
    entries = load(args.log, args.since)
    if args.anonymize:
        anonymize(entries)
    else:
        summary(entries)


if __name__ == "__main__":
    main()
