from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .answer_engine import answer_question


LOGGER = logging.getLogger("rulebot.answer_service")


class AnswerHandler(BaseHTTPRequestHandler):
    server_version = "RuleBotAnswerService/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/answer":
            self._send_json(404, {"error": "not_found"})
            return

        try:
            payload = self._read_json()
            question = str(payload.get("question", ""))
            answer = answer_question(
                question,
                _required_env("DOCS_DIR"),
                top_k=int(_required_env("TOP_K")),
                min_score=float(_required_env("MIN_SCORE")),
                backend=_required_env("ANSWER_BACKEND"),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("answer request failed")
            self._send_json(500, {"error": "answer_failed", "message": str(exc)})
            return

        self._send_json(200, answer.to_dict())

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    logging.basicConfig(level=os.environ["LOG_LEVEL"] if "LOG_LEVEL" in os.environ else "INFO")
    host = os.environ["HOST"] if "HOST" in os.environ else "0.0.0.0"
    port = int(os.environ["PORT"] if "PORT" in os.environ else "8080")
    server = ThreadingHTTPServer((host, port), AnswerHandler)
    LOGGER.info("answer service listening on %s:%s", host, port)
    server.serve_forever()


def _required_env(name: str) -> str:
    value = os.environ[name].strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


if __name__ == "__main__":
    main()
