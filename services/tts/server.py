"""Private HTTP API and process composition for TTS."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from services.tts.config import load_config
from services.tts.lifecycle import ModelLifecycle, TTSFailure, vox_model_factory


def handler(config: dict, lifecycle: ModelLifecycle):
    inference_slot = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        daemon_threads = True

        def setup(self):
            super().setup()
            self.connection.settimeout(config["socket_timeout_seconds"])

        def log_message(self, *_args):
            return

        def reply(self, status, value, content_type="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

        def do_GET(self):
            if self.path == "/healthz":
                self.reply(200, {"status": "alive"})
            elif self.path == "/readyz":
                self.reply(
                    200 if lifecycle.ready() else 503,
                    {"status": "ready" if lifecycle.ready() else "draining"},
                )
            elif self.path == "/internal/v1/state":
                self.reply(200, lifecycle.state())
            elif self.path == "/internal/v1/voices":
                self.reply(
                    200,
                    [
                        {
                            "id": "default",
                            "languages": ["en", "ru", "sv"],
                            "streaming": False,
                        }
                    ],
                )
            else:
                self.reply(
                    404, {"code": "not_found", "message": "endpoint unavailable"}
                )

        def do_POST(self):
            if self.path == "/internal/v1/warmup":
                if not inference_slot.acquire(blocking=False):
                    self.reply(
                        429,
                        {
                            "code": "overloaded",
                            "message": "TTS inference capacity is full",
                        },
                    )
                    return
                try:
                    lifecycle.warmup()
                    self.reply(200, lifecycle.state())
                except TTSFailure as error:
                    self.reply(
                        error.status, {"code": error.code, "message": error.message}
                    )
                finally:
                    inference_slot.release()
                return
            if self.path != "/internal/v1/speech":
                self.reply(
                    404, {"code": "not_found", "message": "endpoint unavailable"}
                )
                return
            if self.headers.get_content_type() != "application/json":
                self.reply(
                    415,
                    {
                        "code": "unsupported_media_type",
                        "message": "application/json is required",
                    },
                )
                return
            size = self.headers.get("Content-Length")
            if size is None:
                self.reply(
                    411,
                    {
                        "code": "content_length_required",
                        "message": "Content-Length is required",
                    },
                )
                return
            try:
                size = int(size)
            except ValueError:
                self.reply(
                    400,
                    {"code": "invalid_request", "message": "invalid Content-Length"},
                )
                return
            if size < 0 or size > config["max_request_bytes"]:
                self.reply(
                    413,
                    {
                        "code": "request_too_large",
                        "message": "request size limit exceeded",
                    },
                )
                return
            try:
                body = json.loads(self.rfile.read(size))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.reply(
                    400,
                    {
                        "code": "invalid_request",
                        "message": "request must be valid JSON",
                    },
                )
                return
            if not isinstance(body, dict) or set(body) - {
                "text",
                "voice",
                "language",
                "mode",
            }:
                self.reply(
                    400,
                    {
                        "code": "invalid_request",
                        "message": "request fields are invalid",
                    },
                )
                return
            text = body.get("text")
            voice = body.get("voice", "default")
            language = body.get("language", "auto")
            mode = body.get("mode", "auto")
            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > config["max_text_characters"]
            ):
                self.reply(
                    400,
                    {
                        "code": "invalid_text",
                        "message": "text must contain 1..10000 characters",
                    },
                )
                return
            if voice != "default":
                self.reply(404, {"code": "unknown_voice", "message": "unknown voice"})
                return
            if not isinstance(language, str) or language not in {
                "auto",
                "en",
                "ru",
                "sv",
            }:
                self.reply(
                    400,
                    {
                        "code": "invalid_language",
                        "message": "language must be auto, en, ru, or sv",
                    },
                )
                return
            if not isinstance(mode, str) or mode not in {"quality", "fast", "auto"}:
                self.reply(
                    400,
                    {
                        "code": "invalid_mode",
                        "message": "mode must be quality, fast, or auto",
                    },
                )
                return
            if mode == "fast" and not config["fast_mode_enabled"]:
                self.reply(
                    422,
                    {
                        "code": "mode_unavailable",
                        "message": "fast mode has not passed quality acceptance",
                    },
                )
                return
            if not inference_slot.acquire(blocking=False):
                self.reply(
                    429,
                    {"code": "overloaded", "message": "TTS inference capacity is full"},
                )
                return
            try:
                audio, content_type = lifecycle.synthesize(text, language, mode)
            except TTSFailure as error:
                self.reply(error.status, {"code": error.code, "message": error.message})
                return
            finally:
                inference_slot.release()
            self.reply(200, audio, content_type)

    return Handler


def serve(config: dict, lifecycle: ModelLifecycle):
    server = ThreadingHTTPServer(
        (config["listen_host"], config["listen_port"]), handler(config, lifecycle)
    )
    server.daemon_threads = True
    stopping = threading.Event()

    def stop(_signum, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.timeout = config["poll_interval_seconds"]
    print(json.dumps({"event": "tts_worker_starting"}), flush=True)
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()
        stopped = lifecycle.stop(config["shutdown_timeout_seconds"])
        print(
            json.dumps(
                {"event": "tts_worker_stopped", "active_inference_drained": stopped}
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config)
    if not args.check_config:
        serve(config, ModelLifecycle(config, vox_model_factory(config)))


if __name__ == "__main__":
    main()
