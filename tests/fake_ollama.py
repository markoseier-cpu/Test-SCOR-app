"""Minimaalne VÕLTS-Ollama HTTP-server UI-testi jaoks (ainult 127.0.0.1, ei kasuta võrku).

Ei ole päris keelemudel: /api/chat tagastab fikseeritud vastuse viitega [1].
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from conftest import FakeEmbedder

_emb = FakeEmbedder()
MODELS = ["fake-llm:latest", "fake-embed:latest"]
REPLY = "Sünteetilises testdokumendis tähendab XQ1.2 vidinate tarne kinnitamist [1]. Vale viide [42]."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": m} for m in MODELS]})
        elif self.path == "/api/version":
            self._send({"version": "fake"})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if req.get("model") not in MODELS and f"{req.get('model')}:latest" not in MODELS:
            return self._send({"error": f"model '{req.get('model')}' not found"}, 404)
        if self.path == "/api/embed":
            vec = _emb.embed(req["model"].split(":")[0], req["input"]).tolist()
            return self._send({"embeddings": vec})
        if self.path == "/api/chat":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for part in (REPLY[:30], REPLY[30:]):
                self.wfile.write((json.dumps({"message": {"content": part}, "done": False}) + "\n").encode())
            self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
            return
        self._send({"error": "not found"}, 404)


def start() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
