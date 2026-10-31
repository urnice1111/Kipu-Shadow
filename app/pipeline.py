import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.config import OUTPUT_FILES


@dataclass
class RunResult:
    records: dict[str, int] = field(default_factory=lambda: {"chats": 0, "docs": 0, "tables": 0})
    tokens_in: int = 0
    tokens_out: int = 0


Pipeline = Callable[[str, str, Path], RunResult]


def run_pipeline(sources_url: str, token: str, staging_dir: Path) -> RunResult:
    raise NotImplementedError("pipeline no implementado (Hito 2)")


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
