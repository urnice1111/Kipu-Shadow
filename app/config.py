import os
from dataclasses import dataclass, field
from pathlib import Path

TEAM = "Kipu Shadow"
VERSION = "0.1.0"
OUTPUT_FILES = ("chats.jsonl", "docs.jsonl", "tables.jsonl", "entities.json")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    output_dir: Path
    staging_dir: Path
    models: list[str] = field(default_factory=list)
    log_dir: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "registry.db"


def load_env(path: Path | None = None) -> None:
    """Load KEY=value lines from .env without overriding the real environment."""
    path = path or Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def get_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    return Settings(
        data_dir=Path(os.environ.get("KIPU_DATA_DIR", root / "data")),
        output_dir=Path(os.environ.get("KIPU_OUTPUT_DIR", root / "output")),
        staging_dir=Path(os.environ.get("KIPU_STAGING_DIR", root / "output_staging")),
        log_dir=Path(os.environ.get("KIPU_LOG_DIR", root / "logs")),
    )
