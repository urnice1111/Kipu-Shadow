"""Given names that stay identical between input and output, per record (real data: local only).

    .venv/bin/python scripts/leftover_names.py
"""

import pickle
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import detect  # noqa: E402
from app.core.anonymize import anonymize_corpus, prepare_engine  # noqa: E402
from app.core.lexicon import PSEUDO_FEMALE, PSEUDO_MALE  # noqa: E402
from app.core.registry import Registry  # noqa: E402
from app.core.text import fold  # noqa: E402

WORD = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]+")


def texts(r: dict) -> list[str]:
    if "text" in r:
        return [r["text"]] + [a["filename"] for a in r["attachments"]]
    if "body" in r:
        return [r["title"], r["body"]] + list(r["metadata"].values())
    return [v for k, v in r["columns"].items() if k in ("notas", "descripcion", "respuesta", "reporta_a")]


def main() -> int:
    corpus = pickle.load(open(ROOT / "data/state/corpus_dev.pkl", "rb"))
    with tempfile.TemporaryDirectory() as tmp:
        engine = prepare_engine(corpus, Registry(Path(tmp) / "p.db"))
        out = {r["id"]: r for s in anonymize_corpus(engine, corpus).values() for r in s}
    pseudo = {fold(x) for x in PSEUDO_FEMALE + PSEUDO_MALE}
    upper, lower, ex = Counter(), Counter(), {}
    for src in (corpus.chats, corpus.docs, corpus.tables):
        for r in src:
            seen = Counter(w for t in texts(r) for w in WORD.findall(t))
            for t in texts(out[r["id"]]):
                folded = fold(t)
                kept = [(m.start(), m.end()) for m in detect.KEPT.finditer(folded)] if detect.KEPT else []
                for m in WORD.finditer(t):
                    w, fw = m.group(0), fold(m.group(0))
                    if fw not in engine.given_names or fw in pseudo or not seen[w]:
                        continue
                    if any(a <= m.start() < b for a, b in kept):
                        continue
                    bucket = upper if w[0].isupper() else lower
                    bucket[w] += 1
                    ex.setdefault(w, (r["id"], t[max(0, m.start() - 60) : m.end() + 40].replace("\n", " ")))
    for title, bucket in (("Mayúscula", upper), ("Minúscula", lower)):
        print(f"\n=== {title}: {len(bucket)} nombres, {sum(bucket.values())} apariciones")
        for w, n in bucket.most_common(40):
            print(f"  {n:3d} {w}: {ex[w]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
