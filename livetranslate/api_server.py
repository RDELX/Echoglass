"""Local HTTP API for the Echoglass browser extension.

Listens on 127.0.0.1 only and answers only requests whose Origin is the Echoglass
extension, so ordinary web pages can't drive the app or spend the user's API keys.

    POST /api/status                   app + live-translation state
    POST /api/translate {text, target?} translate text with the app's current translator
    POST /api/live {action}            start | stop | toggle live translation
    POST /api/overlay {visible?}       show / hide (or toggle) the subtitle overlay
"""

import copy
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from . import __version__
from .config import Config
from .translation import create_translator

log = logging.getLogger(__name__)

# Fixed by the "key" in browser-extension/manifest.json.
EXTENSION_ID = "ijmgbbpjnfdbpinihnnlefpbegipjlfl"
ALLOWED_ORIGINS = {f"chrome-extension://{EXTENSION_ID}"}
MAX_TEXT = 20_000


class ApiServer:
    """`controls` are callables provided by the UI; they're invoked from server threads and
    must be thread-safe (the main window passes Qt-signal emitters)."""

    def __init__(self, cfg: Config, status: Callable[[], dict], live: Callable[[str], None],
                 overlay: Callable[[bool | None], None]):
        self.cfg = cfg
        self.status, self.live, self.overlay = status, live, overlay
        self._httpd: ThreadingHTTPServer | None = None
        self._translators: dict[str, object] = {}
        self._tlock = threading.Lock()

    # ---- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        if self._httpd is not None:
            return
        api = self

        class Handler(_Handler):
            server_api = api

        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.cfg.api.port), Handler)
        except OSError as e:
            log.warning("Extension API couldn't listen on port %d: %s", self.cfg.api.port, e)
            return
        self._httpd.daemon_threads = True
        threading.Thread(target=self._httpd.serve_forever, name="api", daemon=True).start()
        log.info("Extension API listening on 127.0.0.1:%d", self.cfg.api.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def listening(self) -> bool:
        return self._httpd is not None

    # ---- translation -----------------------------------------------------------------

    def translate(self, text: str, target: str | None) -> dict:
        tc = copy.copy(self.cfg.translation)
        if tc.backend == "none":
            raise ValueError("Translation is turned off in Echoglass. Pick a translator in the app.")
        target = target or tc.target_language
        key = repr((tc.backend, tc.ollama_url, tc.ollama_model, tc.lmstudio_url, tc.lmstudio_model,
                    tc.openai_model, tc.claude_model, tc.openai_api_key, tc.deepl_api_key,
                    tc.anthropic_api_key))
        with self._tlock:
            tr = self._translators.get(key)
            if tr is None:
                self._translators = {key: create_translator(tc)}  # keep just the current one
                tr = self._translators[key]
        out = tr.translate(text, None, target, [], kind="text")
        return {"translation": out, "target": target, "translator": tr.label}


class _Handler(BaseHTTPRequestHandler):
    # Everything is POST: Chrome omits the Origin header on extension GET requests, and
    # the Origin check is what keeps web pages out.
    server_api: ApiServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # route to logging, not stderr
        log.debug("api: " + fmt, *args)

    def _origin_ok(self) -> bool:
        return self.headers.get("Origin") in ALLOWED_ORIGINS

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        if self._origin_ok():
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if not self._origin_ok():
            return self._send(403, {"error": "forbidden"})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._send(405, {"error": "use POST"})

    def do_POST(self):
        if not self._origin_ok():
            return self._send(403, {"error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(min(length, 4 * MAX_TEXT)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid JSON"})
        api = self.server_api
        try:
            if self.path == "/api/status":
                return self._send(200, {"app": "Echoglass", "version": __version__, **api.status()})
            if self.path == "/api/translate":
                text = str(body.get("text", "")).strip()
                if not text:
                    return self._send(400, {"error": "no text"})
                if len(text) > MAX_TEXT:
                    return self._send(413, {"error": f"text longer than {MAX_TEXT} characters"})
                return self._send(200, api.translate(text, body.get("target")))
            if self.path == "/api/live":
                action = body.get("action", "toggle")
                if action not in ("start", "stop", "toggle"):
                    return self._send(400, {"error": "action must be start, stop or toggle"})
                api.live(action)
                return self._send(200, {"ok": True})
            if self.path == "/api/overlay":
                v = body.get("visible")
                api.overlay(None if v is None else bool(v))
                return self._send(200, {"ok": True})
        except Exception as e:
            log.warning("API %s failed: %s", self.path, e)
            return self._send(500, {"error": str(e)})
        self._send(404, {"error": "not found"})
