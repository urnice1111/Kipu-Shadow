import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import OUTPUT_FILES
from app.ingestion import check_ids, ingest, write_corpus
from app.ingestion.client import ApiSource


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


def run_pipeline(sources_url: str, token: str, staging_dir: Path) -> RunResult:
    source = ApiSource(sources_url, token)
    try:
        corpus = ingest(source)
    finally:
        source.close()
    check_ids(corpus)
    write_corpus(corpus, staging_dir)
    raise PipelineIncomplete(
        "anonimización no implementada (Hitos 3-5)", RunResult(records=corpus.counts())
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
