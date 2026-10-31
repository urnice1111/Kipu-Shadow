import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.ingestion.chats import read_chats
from app.ingestion.client import Source
from app.ingestion.docs import read_docs
from app.ingestion.tables import read_tables

SOURCES = ("chats", "docs", "tables")


class IngestError(RuntimeError):
    pass


@dataclass
class Corpus:
    chats: list[dict] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    index: dict[str, list[str]] = field(default_factory=dict)
    users: list[dict] = field(default_factory=list)
    chat_meta: dict[str, dict] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {s: len(getattr(self, s)) for s in SOURCES}


def ingest(source: Source) -> Corpus:
    index = source.json("/record_index")
    chats, users, meta = read_chats(source)
    return Corpus(
        chats=chats,
        docs=read_docs(source),
        tables=read_tables(source, index.get("tables", [])),
        index=index,
        users=users,
        chat_meta=meta,
    )


def check_ids(corpus: Corpus) -> None:
    """Fail unless every source matches record_index one to one."""
    problems = []
    for name in SOURCES:
        ids = [r["id"] for r in getattr(corpus, name)]
        expected = set(corpus.index.get(name, []))
        dupes = sorted(i for i, n in Counter(ids).items() if n > 1)
        missing = sorted(expected - set(ids))
        extra = sorted(set(ids) - expected)
        if dupes:
            problems.append(f"{name}: {len(dupes)} ids repetidos, p. ej. {dupes[:3]}")
        if missing:
            problems.append(f"{name}: faltan {len(missing)}, p. ej. {missing[:3]}")
        if extra:
            problems.append(f"{name}: sobran {len(extra)}, p. ej. {extra[:3]}")
    if problems:
        raise IngestError("; ".join(problems))


def write_corpus(corpus: Corpus, out_dir: Path, entities: list[dict] | None = None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in SOURCES:
        with open(out_dir / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for record in getattr(corpus, name):
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out_dir / "entities.json").write_text(
        json.dumps({"entities": entities or []}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
