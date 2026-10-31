"""Watch the sources API until the Págalo migration shows up.

Compares GET /record_index (plus channels, docs and tables) with the saved baseline in
fuentes/record_index.json. When something grows it prints the difference, saves the new
index next to the baseline and shows a macOS notification.

    .venv/bin/python scripts/watch_sources.py            # every 2 minutes
    .venv/bin/python scripts/watch_sources.py --once     # single check, exit 0 if unchanged, 3 if changed
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_env  # noqa: E402
from app.ingestion.client import ApiSource, SourceError  # noqa: E402

BASELINE = ROOT / "fuentes/record_index.json"


def snapshot(source: ApiSource) -> dict:
    return {
        "index": source.json("/record_index"),
        "channels": sorted(c["name"] for c in source.json("/chats/channels")),
        "docs": sorted(d["id"] for d in source.json("/docs")),
        "tables": sorted(t["name"] for t in source.json("/tables")),
    }


def diff(baseline: dict, snap: dict) -> list[str]:
    lines = []
    for k in ("chats", "docs", "tables"):
        old, new = set(baseline.get(k, [])), set(snap["index"].get(k, []))
        if old != new:
            lines.append(f"{k}: {len(old)} -> {len(new)} (+{len(new - old)} nuevos, -{len(old - new)} quitados)")
    lines.append(f"canales: {', '.join(snap['channels'])}")
    lines.append(f"tablas: {', '.join(snap['tables'])}")
    return lines


def notify(message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "Kipu Shadow" sound name "Glass"'],
            check=False, capture_output=True,
        )
    except FileNotFoundError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--every", type=int, default=120, help="segundos entre revisiones")
    args = parser.parse_args()

    load_env()
    source = ApiSource(os.environ["SOURCES_URL"], os.environ["SOURCES_TOKEN"])
    baseline = json.loads(BASELINE.read_text("utf-8"))
    total = sum(len(v) for v in baseline.values())
    print(f"línea base: {total} ids ({', '.join(f'{k}={len(v)}' for k, v in baseline.items())})")

    while True:
        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            snap = snapshot(source)
        except SourceError as exc:
            print(f"[{stamp}] error consultando el API: {exc}")
            if args.once:
                return 2
            time.sleep(args.every)
            continue
        changed = any(set(baseline.get(k, [])) != set(snap["index"].get(k, [])) for k in ("chats", "docs", "tables"))
        now_total = sum(len(v) for v in snap["index"].values())
        if changed:
            out = BASELINE.with_name("record_index_post.json")
            out.write_text(json.dumps(snap["index"]), "utf-8")
            print(f"[{stamp}] EL API CAMBIÓ: {total} -> {now_total} ids. Guardado en {out.relative_to(ROOT)}")
            for line in diff(baseline, snap):
                print("   " + line)
            notify(f"El API de fuentes cambió: {total} -> {now_total} ids")
            return 3
        print(f"[{stamp}] sin cambios ({now_total} ids)")
        if args.once:
            return 0
        time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
