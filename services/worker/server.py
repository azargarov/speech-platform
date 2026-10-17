"""Shared transport only. STT and TTS do not import each other."""

import argparse
import ipaddress
import json
import math
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
        "socket_timeout_seconds",
        "poll_interval_seconds",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("configuration fields must match required schema")
    if data["kind"] != kind or kind not in {"stt", "tts"}:
        raise ValueError("invalid worker kind")
    if not isinstance(data["listen_host"], str) or not valid_host(data["listen_host"]):
        raise ValueError("listen_host must be a valid IPv4 address or hostname")
    if type(data["listen_port"]) is not int or data["listen_port"] <= 0:
        raise ValueError("listen_port must be a positive integer")
    if (
        type(data["socket_timeout_seconds"]) is not int
        or not 0 < data["socket_timeout_seconds"] <= 86400
    ):
        raise ValueError("socket_timeout_seconds must be in 1..86400")
    if data["listen_port"] > 65535:
        raise ValueError("invalid port")
    interval = data["poll_interval_seconds"]
    if (
        type(interval) not in (int, float)
        or not math.isfinite(interval)
        or not 0 < interval <= 60
    ):
        raise ValueError("poll_interval_seconds must be greater than 0 and at most 60")
    return data


def valid_host(value):
    if not isinstance(value, str) or not value or value.strip() != value:
        return False
    try:
        ipaddress.IPv4Address(value)
        return True
    except ipaddress.AddressValueError:
        if all(char.isdigit() or char == "." for char in value):
            return False
        if len(value) > 253:
            return False
        labels = value.rstrip(".").split(".")
        return all(
            label
            and len(label) <= 63
            and label[0].isascii()
            and label[0].isalnum()
            and label[-1].isascii()
            and label[-1].isalnum()
            and all(
                char.isascii() and (char.isalnum() or char == "-") for char in label
            )
            for label in labels
        )


def handler(config, lifecycle=None):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(config["socket_timeout_seconds"])

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
                ready = lifecycle.ready() if lifecycle is not None else False
                metric_value = "1" if ready else "0"
                payload = (
                    "# HELP speech_ready Whether this component can serve inference.\n"
                    f"# TYPE speech_ready gauge\nspeech_ready {metric_value}\n"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            elif self.path == "/healthz":
                self.reply(200, {"status": "alive"})
            elif self.path == "/readyz":
                ready = lifecycle.ready() if lifecycle is not None else False
                if ready:
                    self.reply(200, {"status": "ready"})
                elif lifecycle is not None and lifecycle.cleanup_unconfirmed():
                    self.reply(
                        503,
                        {
                            "code": "cleanup_unconfirmed",
                            "message": "inference process cleanup is unconfirmed",
                        },
                    )
                else:
                    self.reply(
                        503,
                        {"code": "not_ready", "message": "model provider unavailable"},
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
    parser.add_argument("--application-config")
    parser.add_argument("--deployment-config")
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config, kind)
    application_config = None
    deployment_config = None
    if args.application_config or args.deployment_config:
        if kind != "stt" or not args.application_config or not args.deployment_config:
            parser.error(
                "STT application and deployment config must be supplied together"
            )
        from services.stt.config import load_application_config, load_deployment_config

        application_config = load_application_config(args.application_config)
        deployment_config = load_deployment_config(args.deployment_config)
    if args.check_config:
        return
    if application_config is not None and deployment_config is not None:
        raise ValueError(
            "no production inference backend is registered in M02-A; refusing to start"
        )
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
    server.timeout = config["poll_interval_seconds"]
    print(json.dumps({"event": "worker_starting", "kind": kind}), flush=True)
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        server.server_close()
