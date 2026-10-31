import logging
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime

from app.config import Settings
from app.pipeline import Pipeline, publish
from app.schemas import RecordCounts, RunCost, RunStatus

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    chats INTEGER,
    docs INTEGER,
    tables INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    seconds REAL,
    error TEXT
)
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_error(exc: BaseException, secret: str) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if secret:
        message = message.replace(secret, "***")
    return message[:500]


class JobRunner:
    """Runs one full pipeline at a time in a background thread, tracked in SQLite."""

    def __init__(self, settings: Settings, pipeline: Pipeline):
        self.settings = settings
        self.pipeline = pipeline
        self._lock = threading.Lock()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(SCHEMA)
            db.execute(
                "UPDATE jobs SET status='failed', finished_at=?, error=? "
                "WHERE status IN ('queued', 'running')",
                (_now(), "interrumpido por reinicio"),
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.settings.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def _update(self, job_id: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._connect() as db:
            db.execute(f"UPDATE jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id))

    def submit(self, sources_url: str, token: str) -> str:
        with self._lock:
            with self._connect() as db:
                active = db.execute(
                    "SELECT job_id FROM jobs WHERE status IN ('queued', 'running') "
                    "ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
                if active:
                    return active["job_id"]
                job_id = uuid.uuid4().hex
                db.execute(
                    "INSERT INTO jobs (job_id, status, created_at) VALUES (?, 'queued', ?)",
                    (job_id, _now()),
                )
            threading.Thread(
                target=self._run, args=(job_id, sources_url, token), name=f"run-{job_id}", daemon=True
            ).start()
            return job_id

    def _run(self, job_id: str, sources_url: str, token: str) -> None:
        start = time.monotonic()
        staging = self.settings.staging_dir
        self._update(job_id, status="running", started_at=_now())
        try:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            result = self.pipeline(sources_url, token, staging)
            publish(staging, self.settings.output_dir)
        except Exception as exc:
            shutil.rmtree(staging, ignore_errors=True)
            error = _safe_error(exc, token)
            log.warning("job %s failed: %s", job_id, error)
            partial = getattr(exc, "result", None)
            counts = partial.records if partial else {}
            self._update(
                job_id,
                status="failed",
                finished_at=_now(),
                chats=counts.get("chats", 0),
                docs=counts.get("docs", 0),
                tables=counts.get("tables", 0),
                seconds=round(time.monotonic() - start, 3),
                error=error,
            )
            return
        self._update(
            job_id,
            status="done",
            finished_at=_now(),
            chats=result.records.get("chats", 0),
            docs=result.records.get("docs", 0),
            tables=result.records.get("tables", 0),
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            seconds=round(time.monotonic() - start, 3),
        )
        self._archive(job_id)

    def _archive(self, job_id: str) -> None:
        """Keep a copy of each published output; the next run overwrites output/."""
        if not self.settings.log_dir:
            return
        target = self.settings.log_dir / "runs" / f"{_now().replace(':', '')}_{job_id}"
        try:
            shutil.copytree(self.settings.output_dir, target)
            audit = self.settings.data_dir / "last_audit.json"
            if audit.is_file():
                shutil.copy2(audit, target / "last_audit.json")
        except OSError as exc:
            log.warning("no se pudo archivar la salida de %s: %s", job_id, exc)

    def status(self, job_id: str) -> RunStatus | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            return None
        return RunStatus(
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            records=RecordCounts(
                chats=row["chats"] or 0, docs=row["docs"] or 0, tables=row["tables"] or 0
            ),
            cost=RunCost(
                tokens_in=row["tokens_in"] or 0,
                tokens_out=row["tokens_out"] or 0,
                seconds=row["seconds"] or 0.0,
            ),
            error=row["error"],
        )
