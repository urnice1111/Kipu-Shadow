import json
import logging
import pickle
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import OUTPUT_FILES, Settings
from app.core.anonymize import anonymize_corpus, prepare_engine
from app.core.audit import audit, scrub
from app.core.entities import build_entities
from app.core.registry import Registry
from app.ingestion import Corpus, check_ids, ingest, write_corpus
from app.ingestion.client import ApiSource

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    records: dict[str, int] = field(default_factory=lambda: {"chats": 0, "docs": 0, "tables": 0})
    tokens_in: int = 0
    tokens_out: int = 0


class PipelineIncomplete(NotImplementedError):
    """Raised after the stages that exist; carries what they produced so the job can report it."""

    def __init__(self, message: str, result: RunResult):
        super().__init__(message)
        self.result = result


Pipeline = Callable[[str, str, Path], RunResult]


def state_path(settings: Settings) -> Path:
    return settings.data_dir / "state.pkl"


def make_pipeline(settings: Settings, registry: Registry) -> Pipeline:
    """Full run: ingest, resolve identities, replace, audit, write staging, save live state."""

    def run(sources_url: str, token: str, staging_dir: Path) -> RunResult:
        start = time.monotonic()
        source = ApiSource(sources_url, token)
        try:
            corpus = ingest(source)
        finally:
            source.close()
        check_ids(corpus)
        log.info("ingesta: %s en %.1fs", corpus.counts(), time.monotonic() - start)

        engine = prepare_engine(corpus, registry)
        outputs = anonymize_corpus(engine, corpus)
        entities = build_entities(engine)
        report = audit(outputs, entities)
        if report.leaks:
            fixed = scrub(outputs, report, entities)
            log.warning("auditor: %d fugas, %d reemplazos de último recurso", len(report.leaks), fixed)
            report = audit(outputs, entities)
        log.info(
            "auditor: %d formas revisadas, %d fugas, %d seudónimos sin uso",
            report.checked_forms, len(report.leaks), len(report.unused_pseudonyms),
        )

        out = Corpus(chats=outputs["chats"], docs=outputs["docs"], tables=outputs["tables"], index=corpus.index)
        check_ids(out)
        write_corpus(out, staging_dir, entities)
        save_state(settings, engine, report)
        log.info("corrida completa en %.1fs", time.monotonic() - start)
        return RunResult(records=corpus.counts())

    return run


def save_state(settings: Settings, engine, report) -> None:
    """Directory of known people for /anonymize. Contains real data: stays in data/, never published."""
    path = state_path(settings)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"directory": engine.d, "barrios": engine.barrios_by_city}, f)
    tmp.replace(path)
    (settings.data_dir / "last_audit.json").write_text(
        json.dumps(
            {"leaks": report.leaks, "unused_pseudonyms": report.unused_pseudonyms, "checked_forms": report.checked_forms},
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )


def publish(staging_dir: Path, output_dir: Path) -> None:
    """Swap a complete staging dir into output_dir; the previous output stays until then."""
    missing = [name for name in OUTPUT_FILES if not (staging_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"staging incompleto, faltan {missing}")
    extra = sorted(p.name for p in staging_dir.iterdir() if p.name not in OUTPUT_FILES)
    if extra:
        raise RuntimeError(f"staging con archivos de más {extra}")

    previous = output_dir.with_name(output_dir.name + ".prev")
    shutil.rmtree(previous, ignore_errors=True)
    if output_dir.exists():
        output_dir.rename(previous)
    staging_dir.rename(output_dir)
    shutil.rmtree(previous, ignore_errors=True)


def published_file(output_dir: Path, name: str) -> Path | None:
    """Return a published file only when the whole run is present."""
    if name not in OUTPUT_FILES:
        return None
    if not all((output_dir / n).is_file() for n in OUTPUT_FILES):
        return None
    return output_dir / name
