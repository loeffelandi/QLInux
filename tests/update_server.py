"""Lokaler HTTP-Server und Release-Antworten fuer die Update-Tests."""

from __future__ import annotations

import hashlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes: dict[str, object] = {}
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def handle_error(self, request, client_address) -> None:
        """Abgebrochene Verbindungen (Abbruch, Zeitlimit) sind hier gewollt."""

    def body(self, path: str, data: bytes, status: int = 200, **headers: str) -> None:
        def route(handler: BaseHTTPRequestHandler) -> None:
            handler.send_response(status)
            handler.send_header("Content-Length", str(len(data)))
            for name, value in headers.items():
                handler.send_header(name.replace("_", "-"), value)
            handler.end_headers()
            handler.wfile.write(data)

        self.routes[path] = route

    def redirect(self, path: str, location: str) -> None:
        def route(handler: BaseHTTPRequestHandler) -> None:
            handler.send_response(302)
            handler.send_header("Location", location)
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        self.routes[path] = route

    def truncated(self, path: str, data: bytes, claimed: int) -> None:
        def route(handler: BaseHTTPRequestHandler) -> None:
            handler.send_response(200)
            handler.send_header("Content-Length", str(claimed))
            handler.end_headers()
            handler.wfile.write(data)
            handler.wfile.flush()
            handler.close_connection = True

        self.routes[path] = route

    def stall(self, path: str, seconds: float) -> None:
        def route(handler: BaseHTTPRequestHandler) -> None:
            time.sleep(seconds)
            handler.send_response(200)
            handler.send_header("Content-Length", "2")
            handler.end_headers()
            handler.wfile.write(b"{}")

        self.routes[path] = route


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:
        route = self.server.routes.get(self.path)
        if route is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        route(self)  # type: ignore[operator]

    def log_message(self, *args) -> None:
        pass


def _release(tag: str, assets: list[dict] | None = None, **extra) -> dict:
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/loeffelandi/QLInux/releases/tag/{tag}",
        "assets": assets or [],
        **extra,
    }


def _asset(name: str, data: bytes = b"x", url: str = "https://example.org/a") -> dict:
    return {
        "name": name,
        "size": len(data),
        "browser_download_url": url,
        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
    }
