"""Shared transport only. STT and TTS do not import each other."""

import argparse
import json
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml


class StrictLoader(yaml.SafeLoader):
    pass


def mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError("duplicate configuration field")
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def load_config(path, kind):
    data = yaml.load(Path(path).read_text(), Loader=StrictLoader)
    fields = {
        "kind",
        "listen_host",
        "listen_port",
        "max_request_bytes",
        "request_timeout_seconds",
        "shutdown_timeout_seconds",
        "model_path",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("configuration fields must match required schema")
    if data["kind"] != kind or kind not in {"stt", "tts"}:
        raise ValueError("invalid worker kind")
    for field in ("listen_host", "model_path"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(f"{field} must be nonempty")
    if not Path(data["model_path"]).is_absolute():
        raise ValueError("model_path must be absolute")
    for field in (
        "listen_port",
        "max_request_bytes",
        "request_timeout_seconds",
        "shutdown_timeout_seconds",
    ):
        if type(data[field]) is not int or data[field] <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if data["listen_port"] > 65535:
        raise ValueError("invalid port")
    return data


def handler(config):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(config["request_timeout_seconds"])

        def log_message(self, *_args):
            pass  # Never log payloads or transcription content.

        def reply(self, status, data):
            payload = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/metrics":
                payload = (
                    "# HELP speech_ready Whether this component can serve inference.\n"
                    "# TYPE speech_ready gauge\nspeech_ready 0\n"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/healthz":
                self.reply(200, {"status": "alive"})
            elif self.path == "/readyz":
                self.reply(
                    503, {"code": "not_ready", "message": "model provider unavailable"}
                )
            else:
                self.reply(
                    404, {"code": "not_found", "message": "endpoint unavailable"}
                )

        def do_POST(self):
            self.close_connection = True
            self.reply(404, {"code": "not_found", "message": "endpoint unavailable"})

    return Handler


def main(kind):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config, kind)
    if args.check_config:
        return
    server = ThreadingHTTPServer(
        (config["listen_host"], config["listen_port"]), handler(config)
    )
    server.daemon_threads = True
    server.block_on_close = False
    stopping = threading.Event()

    def stop(_signum, _frame):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.timeout = min(0.5, config["shutdown_timeout_seconds"])
    print(json.dumps({"event": "worker_starting", "kind": kind}), flush=True)
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()
