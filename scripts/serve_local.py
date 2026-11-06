"""Server lokal: menyajikan web/ dan meniru endpoint Azure Function /api/* dari lake lokal.

    python scripts/serve_local.py --port 8000
Lalu buka http://localhost:8000 (dashboard memakai API_BASE kosong = server yang sama).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "functions"))


def make_handler(lake):
    from tcba import api

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kw):
            super().__init__(*args, directory=os.path.join(ROOT, "web"), **kw)

        def _send(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                name = u.path[5:].strip("/")
                if name not in api.ROUTES:
                    return self._send(404, {"error": f"route {name} tidak ada"})
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    return self._send(*api.ROUTES[name](lake, q))
                except Exception as e:
                    return self._send(500, {"error": str(e)})
            return super().do_GET()

        def do_POST(self):
            u = urlparse(self.path)
            if u.path.rstrip("/") == "/api/predict":
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                return self._send(*api.predict(lake, body))
            return self._send(404, {"error": "tidak ada"})

        def log_message(self, fmt, *args):
            sys.stderr.write("[serve] " + fmt % args + "\n")
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lake", default=os.path.join(ROOT, "_lake"))
    a = ap.parse_args()
    os.environ.setdefault("LAKE_MODE", "local")
    os.environ.setdefault("LAKE_ROOT", a.lake)
    from tcba.lake import Lake
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), make_handler(Lake()))
    print(f"Dashboard lokal: http://localhost:{a.port}  (Ctrl+C untuk berhenti)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
