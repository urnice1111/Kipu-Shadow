"""Replay the evaluator's logged /anonymize calls against the current code and compare.

Builds the live state from the cached corpus with a temporary copy of the real pseudonym registry,
so nothing in data/ changes. Prints real data: run it locally only.

    .venv/bin/python scripts/replay_anonymize.py [--log logs/requests.jsonl]
"""

import argparse
import json
import pickle
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.core.anonymize import anonymize_corpus, prepare_engine  # noqa: E402
from app.core.audit import audit, record_text  # noqa: E402
from app.core.entities import build_entities  # noqa: E402
from app.core.registry import Registry  # noqa: E402
from app.core.text import judge_compact_digits, judge_contains, judge_norm  # noqa: E402
from app.live import LiveService  # noqa: E402
from app.pipeline import save_state  # noqa: E402
from app.schemas import RECORD_MODELS  # noqa: E402


def copy_registry(dst: Path) -> None:
    src = sqlite3.connect(ROOT / "data" / "pseudonyms.db")
    out = sqlite3.connect(dst / "pseudonyms.db")
    src.backup(out)
    out.close()
    src.close()
    shutil.copy(ROOT / "data" / "secret.key", dst / "secret.key")


def by_originals(entities: list[dict]) -> dict[frozenset, dict]:
    return {frozenset(e["originals"]): e.get("pseudonyms") or {} for e in entities if not e.get("kept")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, default=ROOT / "logs" / "requests.jsonl")
    args = parser.parse_args()
    calls = [json.loads(line) for line in args.log.read_text("utf-8").splitlines() if line.strip()]
    calls = [c for c in calls if c["path"] == "/v1/anonymize" and c["status"] == 200 and isinstance(c["response"], dict)]

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        copy_registry(tmp)
        settings = Settings(data_dir=tmp, output_dir=tmp / "output", staging_dir=tmp / "staging")
        registry = Registry(tmp / "pseudonyms.db")
        corpus = pickle.load(open(ROOT / "data/state/corpus_dev.pkl", "rb"))
        engine = prepare_engine(corpus, registry)
        outputs = anonymize_corpus(engine, corpus)
        save_state(settings, engine, audit(outputs, build_entities(engine)))
        live = LiveService(settings, registry)

        same_records = changed_records = leaks = changed_pseudonyms = 0
        for call in calls:
            req = call["request"]
            model = RECORD_MODELS[req["source"]]
            records = [model.model_validate(r).model_dump(mode="json") for r in req["records"]]
            out, entities = live.anonymize(req["source"], records)
            for old, new in zip(call["response"]["records"], out):
                if old == new:
                    same_records += 1
                else:
                    changed_records += 1
                    print(f"\n[registro distinto] {new['id']}")
                    print(f"  antes: {record_text(old)[:240]}")
                    print(f"  ahora: {record_text(new)[:240]}")
            for rec in out:
                text = record_text(rec)
                norm, compact = judge_norm(text), judge_compact_digits(text)
                for e in entities:
                    if e.get("kept"):
                        continue
                    for orig in e["originals"]:
                        if len(orig) >= 4 and judge_contains(norm, compact, orig):
                            leaks += 1
                            print(f"\n[fuga] {rec['id']}: {orig!r}")
            old_p, new_p = by_originals(call["response"]["entities"]), by_originals(entities)
            for key, pseudos in old_p.items():
                now = new_p.get(key)
                if now is not None and now != pseudos:
                    changed_pseudonyms += 1
                    print(f"\n[seudónimo distinto] {sorted(key)[:3]}: {pseudos} -> {now}")
        registry.close()

    print(
        f"\n{len(calls)} llamadas | registros iguales {same_records}, distintos {changed_records} | "
        f"seudónimos distintos {changed_pseudonyms} | fugas {leaks}"
    )
    return 0 if not (changed_pseudonyms or leaks) else 1


if __name__ == "__main__":
    sys.exit(main())
