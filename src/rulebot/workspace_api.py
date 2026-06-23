from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

from .workspace_grep import GrepIndex, request_from_dict


class GrepApi:
    def __init__(self, projections: dict[str, GrepIndex]):
        self.projections = projections

    def post_grep(self, projection_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        index = self.projections.get(projection_id)
        if index is None:
            return 404, {"error": "projection_not_found"}
        try:
            response = index.grep(request_from_dict(payload))
        except ValueError as exc:
            return 400, {"error": "bad_request", "message": str(exc)}
        except TimeoutError as exc:
            return 504, {"error": "grep_timeout", "message": str(exc)}
        return 200, response.to_dict()


def make_grep_handler(api: GrepApi) -> type[BaseHTTPRequestHandler]:
    class GrepHandler(BaseHTTPRequestHandler):
        server_version = "WorkspaceGrepApi/0.1"

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) != 4 or parts[:2] != ["api", "projections"] or parts[3] != "grep":
                self._send_json(404, {"error": "not_found"})
                return
            payload = self._read_json()
            status, body = api.post_grep(parts[2], payload)
            self._send_json(status, body)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return GrepHandler
