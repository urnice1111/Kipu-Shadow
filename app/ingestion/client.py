import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    pass


class Source(Protocol):
    def json(self, path: str) -> Any: ...

    def bytes(self, path: str) -> bytes: ...


class ApiSource:
    """Organizer sources API: bearer auth, retries, and a request-rate ceiling.

    The token only lives in the client headers; errors carry method, path and status.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        max_per_second: float = 8.0,
        attempts: int = 5,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )
        self._min_interval = 1.0 / max_per_second
        self._attempts = attempts
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last = 0.0
        self.requests = 0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last + self._min_interval - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()

    def _get(self, path: str) -> httpx.Response:
        problem = ""
        for attempt in range(self._attempts):
            self._throttle()
            self.requests += 1
            try:
                response = self._client.get(path)
            except httpx.TransportError as exc:
                problem = type(exc).__name__
            else:
                if response.status_code == 200:
                    return response
                problem = f"HTTP {response.status_code}"
                if response.status_code not in RETRY_STATUS:
                    break
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    self._sleep(float(retry_after))
                    continue
            if attempt + 1 < self._attempts:
                self._sleep(0.5 * 2**attempt)
        log.warning("GET %s failed: %s", path, problem)
        raise SourceError(f"GET {path}: {problem}")

    def json(self, path: str) -> Any:
        return json.loads(self._get(path).content)

    def bytes(self, path: str) -> bytes:
        return self._get(path).content

    def close(self) -> None:
        self._client.close()
