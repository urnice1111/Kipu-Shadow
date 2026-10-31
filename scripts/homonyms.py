"""Every mention of a homonym (same given name + first surname) and who it was resolved to.

Prints real data: run it locally only.

    .venv/bin/python scripts/homonyms.py
"""

import pickle
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.anonymize import anonymize_corpus, prepare_engine  # noqa: E402
from app.core.registry import Registry  # noqa: E402
from app.core.text import fold  # noqa: E402


def text_of(r: dict) -> str:
    return r.get("text") or r.get("body") or " | ".join(r.get("columns", {}).values())


def main() -> int:
    corpus = pickle.load(open(ROOT / "data/state/corpus_dev.pkl", "rb"))
    with tempfile.TemporaryDirectory() as tmp:
        engine = prepare_engine(corpus, Registry(Path(tmp) / "p.db"))
        anonymize_corpus(engine, corpus)
    d = engine.d
    records = {r["id"]: r for s in (corpus.chats, corpus.docs, corpus.tables) for r in s}
    groups = defaultdict(list)
    for pid, p in d.persons.items():
        if p.given and p.surnames:
            groups[(fold(p.given[0]), fold(p.surnames[0]))].append(pid)
    for (g, s), pids in groups.items():
        if len(pids) < 2:
            continue
        print(f"\n#### {g} {s}: {[(pid, d.persons[pid].canonical) for pid in pids]}")
        rx = re.compile(rf"(?<![a-z]){g}(?:[\s_.-]+[a-z]+)?[\s_.-]+{s}(?![a-z])")
        for rid, r in records.items():
            t = text_of(r)
            for m in rx.finditer(fold(t)):
                winners = [pid for pid in pids if pid in engine.hits and rid in engine.hits[pid].records]
                if rid.split(":")[0] in ("clientes", "empleados") and any(rid in d.persons[w].rows for w in winners):
                    break
                print(f"  {rid[:38]:38} gana={winners} :: {t[max(0, m.start() - 70) : m.end() + 60]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
