import json
from pathlib import Path
from typing import Any

from app.ingestion.client import SourceError

# The sample zip has no tables index; these are the formats stated in ENUNCIADO.md.
DEFAULT_TABLES = {
    "clientes.csv": {"format": "csv", "charset": "latin-1", "separator": ";"},
    "transacciones.csv": {"format": "csv", "charset": "utf-8", "separator": ","},
    "pqrs.xml": {"format": "xml", "charset": "utf-8"},
    "empleados.xml": {"format": "xml", "charset": "utf-8"},
}


class DirSource:
    """Same interface as ApiSource over the layout of sample.zip's input/ folder."""

    def __init__(self, root: Path, index_path: Path | None = None):
        self.root = Path(root)
        self.index_path = Path(index_path) if index_path else self.root.parent / "record_index.json"
        self.requests = 0

    def _read_json(self, path: Path) -> Any:
        if not path.is_file():
            raise SourceError(f"no existe {path}")
        return json.loads(path.read_text("utf-8"))

    def json(self, path: str) -> Any:
        self.requests += 1
        parts = path.strip("/").split("/")
        match parts:
            case ["chats", "channels"]:
                return self._read_json(self.root / "chats" / "channels.json")
            case ["chats", "users"]:
                return self._read_json(self.root / "chats" / "users.json")
            case ["chats", channel]:
                folder = self.root / "chats" / channel
                if not folder.is_dir():
                    raise SourceError(f"no existe el canal {channel}")
                return sorted(p.stem for p in folder.glob("*.json"))
            case ["chats", channel, date]:
                return self._read_json(self.root / "chats" / channel / f"{date}.json")
            case ["docs"]:
                return self._read_json(self.root / "docs" / "index.json")
            case ["tables"]:
                custom = self.root / "tables" / "index.json"
                if custom.is_file():
                    return self._read_json(custom)
                return [
                    {"name": p.name, **DEFAULT_TABLES[p.name]}
                    for p in sorted((self.root / "tables").iterdir())
                    if p.name in DEFAULT_TABLES
                ]
            case ["record_index"]:
                return self._read_json(self.index_path)
        raise SourceError(f"ruta no soportada {path}")

    def bytes(self, path: str) -> bytes:
        self.requests += 1
        parts = path.strip("/").split("/")
        match parts:
            case ["docs", doc_id]:
                for entry in self.json("/docs"):
                    if entry["id"] == doc_id:
                        return (self.root / "docs" / entry["filename"]).read_bytes()
                raise SourceError(f"no existe el documento {doc_id}")
            case ["tables", name]:
                file = self.root / "tables" / name
                if not file.is_file():
                    raise SourceError(f"no existe la tabla {name}")
                return file.read_bytes()
        raise SourceError(f"ruta no soportada {path}")

    def close(self) -> None:
        pass
