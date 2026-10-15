"""A tiny fake SIS REST API for local demos and tests (standard library only).

Endpoint:  GET /api/v1/enrollments?term=2026F&page=1&page_size=5
Auth:      Authorization: Bearer <token>

All data below is fictional. 
The dataset deliberately includes messy records (missing IDs, unknown statuses, 
inconsistent formatting).
"""
from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

API_TOKEN = "demo-token"

SAMPLE_ENROLLMENTS = [
    {"student_id": "S1001", "course": "CSE115", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1001", "course": "MTH141", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1002", "course": "CSE115", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1002", "course": "PHY107", "term": "2026F", "status": "waitlisted"},
    {"student_id": "S1003", "course": "MTH141", "term": "2026F", "status": "dropped"},
    {"student_id": "S1003", "course": "ENG201", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1004", "course": "CSE115", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1004", "course": "BIO200", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1005", "course": "ENG201", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1005", "course": "PHY107", "term": "2026F", "status": "enrolled"},
    # Messy records the client code must cope with:
    {"student_id": "", "course": "CSE115", "term": "2026F", "status": "enrolled"},
    {"student_id": "S1006", "course": "CSE250", "term": "2026F", "status": "audit"},
    {"student_id": "S1007", "course": "MTH141", "term": "2026F", "status": "enrolled"},
    {"student_id": "s1008", "course": " cse 115 ", "term": "2026F", "status": "Enrolled"},
    # Different term, should never be returned for a 2026F query:
    {"student_id": "S1001", "course": "CSE116", "term": "2027S", "status": "enrolled"},
]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep demo output quiet
        pass

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 (http.server naming convention)
        url = urlparse(self.path)
        if self.headers.get("Authorization") != f"Bearer {self.server.token}":
            return self._send(401, {"error": "unauthorized"})
        if url.path != "/api/v1/enrollments":
            return self._send(404, {"error": "not found"})

        query = parse_qs(url.query)
        try:
            page = int(query.get("page", ["1"])[0])
            page_size = int(query.get("page_size", ["5"])[0])
            if page < 1 or page_size < 1:
                raise ValueError
        except ValueError:
            return self._send(400, {"error": "page and page_size must be positive integers"})

        # Simulate a transient outage the first time a given page is requested.
        if page in self.server.flaky_pages:
            self.server.flaky_pages.discard(page)
            return self._send(503, {"error": "temporarily unavailable"})

        term = query.get("term", [""])[0]
        rows = [r for r in self.server.enrollments if r.get("term") == term]
        total_pages = max(1, math.ceil(len(rows) / page_size))
        start = (page - 1) * page_size
        self._send(200, {
            "data": rows[start:start + page_size],
            "page": page,
            "total_pages": total_pages,
        })


def make_server(enrollments=None, token: str = API_TOKEN, flaky_pages=()) -> ThreadingHTTPServer:
    """Create (but don't start) a server on a free local port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.enrollments = list(SAMPLE_ENROLLMENTS if enrollments is None else enrollments)
    server.token = token
    server.flaky_pages = set(flaky_pages)
    return server


def start_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def base_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"
