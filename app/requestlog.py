"""One JSON line per HTTP request: body in, body out, status and latency.

The evaluator's live tests are hidden; this is the only record of what it sent and what we
answered. Contains original PII from those requests: local only, never commit or share it.
"""

import hashlib
import json
import logging
import threading
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Large file downloads are logged by size and hash; a copy of each run lives in logs/runs/.
FILE_PREFIXES = ("/v1/output/", "/v1/entities")
REDACTED_KEYS = {"token"}
TEXT_LIMIT = 20_000


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _decode(raw: bytes):
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")[:TEXT_LIMIT]
    if isinstance(body, dict):
        body = {k: "***" if k in REDACTED_KEYS else v for k, v in body.items()}
    return body


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


class RequestLog:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line)


class RequestLogMiddleware:
    def __init__(self, app, path: Path):
        self.app = app
        self.log = RequestLog(path)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = _now()
        start = time.monotonic()
        is_file = scope["path"].startswith(FILE_PREFIXES)
        request_chunks: list[bytes] = []
        response_chunks: list[bytes] = []
        digest = hashlib.sha256()
        state = {"status": None, "bytes": 0, "content_type": None}

        async def receive_logged():
            message = await receive()
            if message["type"] == "http.request":
                request_chunks.append(message.get("body", b""))
            return message

        async def send_logged(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["content_type"] = next(
                    (v.decode("latin-1") for k, v in message.get("headers", []) if k == b"content-type"), None
                )
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                state["bytes"] += len(body)
                if is_file:
                    digest.update(body)
                else:
                    response_chunks.append(body)
            await send(message)

        error = None
        try:
            await self.app(scope, receive_logged, send_logged)
        except BaseException:
            error = traceback.format_exc()
            raise
        finally:
            if is_file:
                response = {"bytes": state["bytes"], "sha256": digest.hexdigest()}
            else:
                response = _decode(b"".join(response_chunks))
            entry = {
                "ts": started,
                "id": uuid.uuid4().hex[:12],
                "method": scope["method"],
                "path": scope["path"],
                "query": scope.get("query_string", b"").decode("latin-1") or None,
                "client": _header(scope, b"x-forwarded-for") or (scope.get("client") or [None])[0],
                "user_agent": _header(scope, b"user-agent"),
                "status": state["status"] or 500,
                "ms": round((time.monotonic() - start) * 1000, 1),
                "request": _decode(b"".join(request_chunks)),
                "response": response,
                "content_type": state["content_type"],
                "error": error,
            }
            try:
                self.log.write(entry)
            except Exception:
                log.exception("no se pudo escribir el log de %s %s", scope["method"], scope["path"])
