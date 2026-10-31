"""POST /anonymize: same engine and registry as the last full run, applied to new records."""

import pickle
import threading
from collections import defaultdict

from app.config import Settings
from app.core.anonymize import anonymize_chats, anonymize_docs, anonymize_tables, discover_people
from app.core.engine import Engine, Hit
from app.core.entities import build_entities
from app.core.identities import Directory
from app.core.registry import Registry
from app.pipeline import state_path


class LiveService:
    def __init__(self, settings: Settings, registry: Registry):
        self.settings = settings
        self.registry = registry
        self._lock = threading.Lock()
        self._engine: Engine | None = None
        self._state_mtime: float | None = None

    def _load(self) -> Engine:
        path = state_path(self.settings)
        mtime = path.stat().st_mtime if path.is_file() else None
        if self._engine is None or mtime != self._state_mtime:
            if mtime is not None:
                with open(path, "rb") as f:
                    state = pickle.load(f)
                self._engine = Engine(state["directory"], self.registry, state["barrios"])
            else:
                self._engine = Engine(Directory(), self.registry, {})
            self._state_mtime = mtime
        return self._engine

    def anonymize(self, source: str, records: list[dict]) -> tuple[list[dict], list[dict]]:
        with self._lock:
            engine = self._load()
            engine.hits = defaultdict(Hit)
            engine.kept_hits = defaultdict(set)
            engine.kept_surface = defaultdict(set)

            if source == "tables":
                changed = self._learn_rows(engine, records)
                if changed:
                    engine.rebuild()
            discover_people(engine, [(source, records)])

            if source == "chats":
                out = anonymize_chats(engine, records)
            elif source == "docs":
                out = anonymize_docs(engine, records)
            else:
                out = anonymize_tables(engine, records)
            entities = build_entities(engine, records={r["id"] for r in records})
            return out, entities

    @staticmethod
    def _learn_rows(engine: Engine, records: list[dict]) -> bool:
        """Rows of the person tables add or enrich people before replacing."""
        before = len(engine.d.persons)
        changed = False
        for rec in records:
            if rec["table"] == "clientes" and rec["columns"].get("cliente_id"):
                engine.d.add_client_row(rec["id"], rec["columns"])
                changed = True
            elif rec["table"] == "empleados" and rec["columns"].get("id"):
                engine.d.add_employee_row(rec["id"], rec["columns"])
                changed = True
            elif rec["table"] == "pqrs":
                engine.d.link_pqrs_row(rec["id"], rec["columns"])
        return changed or len(engine.d.persons) != before
