"""Local score before spending an official run.

Runs the full pipeline on the sample (tests_sample.json) or on the real corpus
(tests_public.json), writes the four files, runs validar.mjs and checks every test family.

    .venv/bin/python scripts/score_local.py sample
    .venv/bin/python scripts/score_local.py corpus [--refresh]
"""

import argparse
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import load_env  # noqa: E402
from app.core.anonymize import anonymize_corpus, prepare_engine  # noqa: E402
from app.core.audit import audit, record_text, scrub  # noqa: E402
from app.core.entities import build_entities  # noqa: E402
from app.core.registry import Registry  # noqa: E402
from app.core.text import judge_compact_digits, judge_contains, judge_norm  # noqa: E402
from app.ingestion import Corpus, check_ids, ingest, write_corpus  # noqa: E402
from app.ingestion.client import ApiSource  # noqa: E402
from app.ingestion.dirsource import DirSource  # noqa: E402


def contains(rec: dict | None, needle: str, field: str | None = None) -> bool:
    if rec is None:
        return False
    text = field_text(rec, field)
    return judge_contains(judge_norm(text), judge_compact_digits(text), needle)


def field_text(rec: dict, field: str | None) -> str:
    if not field or field in ("any", "raw", "*"):
        return record_text(rec)
    if field.startswith("columns."):
        return str(rec.get("columns", {}).get(field.split(".", 1)[1], ""))
    value = rec.get(field)
    return record_text({"x": value}) if not isinstance(value, str) else value


def evaluate(test: dict, inp: dict, out: dict, entities: list[dict]) -> tuple[bool, str]:
    family = test["family"]
    loc = test.get("locator") or {}
    rid, field = loc.get("record"), loc.get("field")
    payload = test.get("payload") or []

    if family == "directa":
        bad = [p for p in payload if contains(out.get(rid), p, field)]
        elsewhere = [r for p in payload for r, rec in out.items() if contains(rec, p)]
        return not bad and not elsewhere, f"en registro: {bad} | en otros: {elsewhere[:3]}"
    if family == "oculta":
        bad = [p for p in payload if contains(out.get(rid), p, field)]
        return not bad, f"sigue: {bad}"
    if family == "falso_positivo":
        missing = [p for p in payload if p not in field_text(out.get(rid, {}), field)]
        return not missing, f"falta: {missing}"
    if family == "indirecta":
        records = [rid] + list(test.get("join_records") or [])
        together = [r for r in records if out.get(r) and all(contains(out[r], p) for p in payload)]
        return not together, f"juntos en: {together}"
    if family == "homonimos":
        first_two = " ".join(payload[0].split()[:2])
        same = [r for r, rec in inp.items() if contains(rec, first_two, field)]
        names = {field_text(out[r], field) for r in same if r in out}
        return len(same) >= 2 and len(names) == len(same), f"filas: {same} -> {sorted(names)}"
    if family == "consistencia":
        forms = test.get("lookup_forms") or []
        records = sorted(r for r, rec in inp.items() if any(contains(rec, f) for f in forms))
        owners = [e for e in entities if not e.get("kept") and set(forms) & set(e.get("originals", []))]
        if len(owners) != 1:
            return False, f"{len(owners)} entidades con esas formas"
        name = owners[0]["pseudonyms"].get("name", "")
        pseudos = [v for v in owners[0]["pseudonyms"].values()]
        missing = [r for r in records if not any(contains(out.get(r), v) for v in pseudos)]
        return not missing, f"seudónimo {name!r}; registros sin él: {missing[:5]} de {len(records)}"
    return False, f"familia desconocida {family}"


def load_corpus(target: str, refresh: bool) -> tuple[Corpus, list[dict], Path]:
    if target == "sample":
        corpus = ingest(DirSource(ROOT / "sample/unpacked/input"))
        tests = json.loads((ROOT / "sample/unpacked/tests_sample.json").read_text("utf-8"))
        return corpus, tests, ROOT / "sample/unpacked"
    cache = ROOT / "data/state/corpus_dev.pkl"
    if refresh or not cache.is_file():
        load_env()
        corpus = ingest(ApiSource(os.environ["SOURCES_URL"], os.environ["SOURCES_TOKEN"]))
        cache.parent.mkdir(parents=True, exist_ok=True)
        pickle.dump(corpus, open(cache, "wb"))
        (ROOT / "fuentes/record_index.json").write_text(json.dumps(corpus.index), "utf-8")
    corpus = pickle.load(open(cache, "rb"))
    tests = json.loads((ROOT / "fuentes/tests_public.json").read_text("utf-8"))
    return corpus, tests, ROOT / "fuentes"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["sample", "corpus"])
    parser.add_argument("--refresh", action="store_true", help="volver a bajar el corpus del API")
    parser.add_argument("--keep-registry", action="store_true", help="reutilizar el registro de seudónimos")
    args = parser.parse_args()

    work = ROOT / "data/score" / args.target
    if not args.keep_registry:
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    corpus, tests, public_dir = load_corpus(args.target, args.refresh)
    check_ids(corpus)
    start = time.monotonic()
    engine = prepare_engine(corpus, Registry(work / "pseudonyms.db"))
    outputs = anonymize_corpus(engine, corpus)
    entities = build_entities(engine)
    report = audit(outputs, entities)
    if report.leaks:
        scrub(outputs, report, entities)
        report = audit(outputs, entities)
    seconds = time.monotonic() - start
    write_corpus(Corpus(chats=outputs["chats"], docs=outputs["docs"], tables=outputs["tables"]), work / "out", entities)

    inp = {r["id"]: r for src in (corpus.chats, corpus.docs, corpus.tables) for r in src}
    out = {r["id"]: r for src in outputs.values() for r in src}
    passed = 0
    for t in tests:
        ok, detail = evaluate(t, inp, out, entities)
        passed += ok
        print(f"{'PASA ' if ok else 'FALLA'} {t['id']:<10} {t['family']:<14} {t['mechanism']:<40} {detail}")
    validator = subprocess.run(
        ["node", str(ROOT / "validar.mjs"), str(work / "out"), "--public", str(public_dir)],
        capture_output=True, text=True,
    )
    print(validator.stdout.strip())
    persons = sum(1 for e in entities if e["type"] == "person")
    kept = sum(1 for e in entities if e.get("kept"))
    print(
        f"\n{passed}/{len(tests)} tests | {persons} personas, {kept} conservadas | "
        f"auditor: {len(report.leaks)} fugas, {len(report.unused_pseudonyms)} seudónimos sin uso | {seconds:.1f}s"
    )
    return 0 if passed == len(tests) and validator.returncode == 0 and report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
