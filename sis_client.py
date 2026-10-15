"""REST client for a paginated SIS enrollment API.

Design notes:
  * Transient failures (timeouts, 429, 5xx) are retried with exponential backoff.
  * Client errors (400, 401, 404, ...) are NOT retried: retrying a bad request
    or a bad credential only hides the problem and hammers the server.
  * Pagination is exposed as a generator, so callers can process large result
    sets without holding everything in memory.
  * `sleep` is injectable so tests don't have to actually wait.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterator

log = logging.getLogger(__name__)


class SisApiError(Exception):
    """Raised when the SIS API cannot be queried successfully."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class SisClient:
    RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._sleep = sleep

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:  # must precede URLError (its parent)
                if exc.code not in self.RETRYABLE_STATUSES:
                    raise SisApiError(f"HTTP {exc.code} from {path}", status=exc.code) from exc
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc

            if attempt < self.max_retries:
                delay = self.backoff * (2 ** attempt)
                log.warning("Request to %s failed (%s); retry %d/%d in %.2fs",
                            path, last_error, attempt + 1, self.max_retries, delay)
                self._sleep(delay)

        raise SisApiError(
            f"Gave up on {path} after {self.max_retries + 1} attempts: {last_error}"
        )

    def iter_enrollments(self, term: str, page_size: int = 5) -> Iterator[dict]:
        """Yield raw enrollment records for a term, following pagination."""
        page = 1
        while True:
            body = self._get(
                "/api/v1/enrollments",
                {"term": term, "page": page, "page_size": page_size},
            )
            yield from body["data"]
            if page >= body["total_pages"]:
                return
            page += 1
