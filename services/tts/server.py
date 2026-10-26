"""Private HTTP API and process composition for TTS."""

from __future__ import annotations

import argparse
import json
import signal
import select
import socket
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from services.tts.config import load_config
from services.tts.lifecycle import (
    ModelLifecycle,
    SynthesisContext,
    TTSFailure,
    vox_model_factory,
)
from services.worker.request_id import from_headers


def _emit_event(**fields):
    print(json.dumps(fields, separators=(",", ":")), flush=True)


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
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            request_id = getattr(self, "gateway_request_id", None)
            if request_id is not None:
                fields = {
                    "event": "worker_request_failed"
                    if status >= 400
                    else "worker_request_completed",
                    "request_id": request_id,
                    "method": self.command,
                    "path": self.path.split("?", 1)[0],
                    "status": status,
                    "elapsed_ms": int((time.monotonic() - self.request_started) * 1000),
                }
                if isinstance(value, dict) and isinstance(value.get("code"), str):
                    fields["api_code"] = value["code"]
                _emit_event(**fields)

        def do_GET(self):
            if self.path == "/healthz":
                self.reply(200, {"status": "alive"})
            elif self.path == "/readyz":
                readiness = lifecycle.readiness()
                body = (
                    {"status": "ready"}
                    if readiness["ready"]
                    else {
                        "code": readiness["code"],
                        "message": readiness["message"],
                    }
                )
                self.reply(
                    200 if readiness["ready"] else 503,
                    body,
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

        def disconnected(self):
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                return bool(readable) and not self.connection.recv(
                    1, socket.MSG_PEEK | socket.MSG_DONTWAIT
                )
            except BlockingIOError:
                return False
            except (OSError, ValueError):
                return True

        def do_POST(self):
            started = time.monotonic()
            self.request_started = started
            self.gateway_request_id = from_headers(self.headers)
            if self.gateway_request_id is not None:
                _emit_event(
                    event="worker_request_started",
                    request_id=self.gateway_request_id,
                    method=self.command,
                    path=self.path.split("?", 1)[0],
                )
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
            raw_timeout = self.headers.get("X-Request-Timeout-Ms")
            if raw_timeout is not None and (
                len(raw_timeout) > 10
                or not raw_timeout.isascii()
                or not raw_timeout.isdecimal()
                or int(raw_timeout) < 1
            ):
                self.reply(
                    400,
                    {
                        "code": "invalid_request",
                        "message": "request timeout is invalid",
                    },
                )
                return
            maximum = config["request_timeout_seconds"]
            timeout = (
                maximum
                if raw_timeout is None
                else min(int(raw_timeout) / 1000, maximum)
            )
            body_complete = False
            context = SynthesisContext(
                started + timeout, lambda: body_complete and self.disconnected()
            )
            try:
                chunks = []
                remaining_bytes = size
                while remaining_bytes:
                    context.check()
                    remaining = context.deadline - time.monotonic()
                    if remaining <= 0:
                        raise TTSFailure(
                            "deadline_exceeded", "speech request deadline exceeded", 504
                        )
                    self.connection.settimeout(
                        min(config["socket_timeout_seconds"], remaining)
                    )
                    chunk = self.rfile.read1(min(remaining_bytes, 65536))
                    if not chunk:
                        self.reply(
                            400,
                            {
                                "code": "invalid_request",
                                "message": "request body is incomplete",
                            },
                        )
                        return
                    chunks.append(chunk)
                    remaining_bytes -= len(chunk)
                body_complete = True
                context.check()
                body = json.loads(b"".join(chunks))
            except TTSFailure as error:
                self.reply(error.status, {"code": error.code, "message": error.message})
                return
            except TimeoutError:
                self.reply(
                    504,
                    {
                        "code": "deadline_exceeded",
                        "message": "speech request deadline exceeded",
                    },
                )
                return
            except OSError:
                self.reply(
                    400,
                    {
                        "code": "invalid_request",
                        "message": "request body could not be read",
                    },
                )
                return
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
                "input_format",
                "audio_processing",
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
            mode = body.get("mode", "quality")
            input_format = body.get("input_format", "text")
            audio_processing = body.get("audio_processing", "none")
            if not isinstance(input_format, str) or input_format not in {
                "text",
                "ssml",
            }:
                self.reply(
                    400,
                    {
                        "code": "invalid_input_format",
                        "message": "input_format must be text or ssml",
                    },
                )
                return
            if (
                not isinstance(text, str)
                or not text.strip()
                or (
                    input_format == "text" and len(text) > config["max_text_characters"]
                )
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
            if input_format == "ssml" and language != "auto":
                self.reply(
                    400,
                    {
                        "code": "invalid_language",
                        "message": "SSML language is specified by speak and lang xml:lang attributes",
                    },
                )
                return
            if not isinstance(mode, str) or mode not in {
                "quality",
                "fast",
                "auto",
                "high_quality",
                "extra_high_quality",
            }:
                self.reply(
                    400,
                    {
                        "code": "invalid_mode",
                        "message": "mode must be quality, fast, auto, high_quality, or extra_high_quality",
                    },
                )
                return
            if not isinstance(audio_processing, str) or audio_processing not in {
                "none",
                "gentle",
            }:
                self.reply(
                    400,
                    {
                        "code": "invalid_audio_processing",
                        "message": "audio_processing must be none or gentle",
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
                audio, content_type = lifecycle.synthesize(
                    text,
                    language,
                    mode,
                    input_format,
                    audio_processing,
                    context=context,
                )
                context.check()
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
