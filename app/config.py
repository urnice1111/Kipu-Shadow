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

    @property
    def db_path(self) -> Path:
        return self.data_dir / "registry.db"


def get_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    return Settings(
        data_dir=Path(os.environ.get("KIPU_DATA_DIR", root / "data")),
        output_dir=Path(os.environ.get("KIPU_OUTPUT_DIR", root / "output")),
        staging_dir=Path(os.environ.get("KIPU_STAGING_DIR", root / "output_staging")),
    )
