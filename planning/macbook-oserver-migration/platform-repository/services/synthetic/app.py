#!/usr/bin/env python3
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


VERSION = (Path(__file__).parent / "VERSION").read_text().strip()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        responses = {
            "/healthz": {"status": "ok"},
            "/readyz": {"status": "ready"},
            "/synthetic": {"service": "SVC-SYNTHETIC", "version": VERSION},
        }
        payload = responses.get(self.path)
        if payload is None:
            self.send_error(404)
            return
        body = (json.dumps(payload, sort_keys=True) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
