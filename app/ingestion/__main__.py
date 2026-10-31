"""Ingest the sources into normalized, NOT anonymized records for local checks.

    python -m app.ingestion --source api --out data/ingest
    python -m app.ingestion --source dir --dir sample/unpacked/input --out data/ingest_sample
"""

import argparse
import os
import sys
import time
from pathlib import Path

from app.config import load_env
from app.ingestion import IngestError, check_ids, ingest, write_corpus
from app.ingestion.client import ApiSource
from app.ingestion.dirsource import DirSource


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingestion")
    parser.add_argument("--source", choices=["api", "dir"], default="api")
    parser.add_argument("--dir", type=Path, help="carpeta input/ con el layout de sample.zip")
    parser.add_argument("--index", type=Path, help="record_index.json (por defecto junto a --dir)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.source == "api":
        load_env()
        url, token = os.environ.get("SOURCES_URL"), os.environ.get("SOURCES_TOKEN")
        if not url or not token:
            print("Faltan SOURCES_URL y SOURCES_TOKEN (entorno o .env).", file=sys.stderr)
            return 2
        source = ApiSource(url, token)
    else:
        if not args.dir:
            print("--source dir requiere --dir", file=sys.stderr)
            return 2
        source = DirSource(args.dir, args.index)

    start = time.monotonic()
    try:
        corpus = ingest(source)
        check_ids(corpus)
    except IngestError as exc:
        print(f"FALLA: {exc}", file=sys.stderr)
        return 1
    finally:
        source.close()
    write_corpus(corpus, args.out)
    counts = corpus.counts()
    print(
        f"OK: {counts['chats']} chats, {counts['docs']} docs, {counts['tables']} filas "
        f"({sum(counts.values())} registros) en {time.monotonic() - start:.1f}s "
        f"con {source.requests} peticiones -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
