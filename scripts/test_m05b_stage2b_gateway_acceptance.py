"""Offline integration acceptance through the compiled Gateway binary."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_SOURCE = ROOT / "configs/gateway.yaml"
TOKEN = "offline-acceptance-token-0123456789"
CLOUD_KEY = "offline-fake-cloud-key"


class ProviderState:
    def __init__(self, protocol: str):
        self.protocol = protocol
        self.lock = threading.Lock()
        self.calls: list[dict] = []
        self.plans: dict[str, list[dict]] = {}

    def reset(self, plans: dict[str, list[dict]] | None = None) -> None:
        with self.lock:
            self.calls.clear()
            self.plans = {key: list(value) for key, value in (plans or {}).items()}

    def dispatch(self, handler: BaseHTTPRequestHandler, body: dict) -> None:
        model = str(body.get("model", ""))
        with self.lock:
            self.calls.append(
                {
                    "model": model,
                    "authorization_present": bool(handler.headers.get("Authorization")),
                    "path": handler.path,
                }
            )
            plan = self.plans.get(model, []).pop(0) if self.plans.get(model) else {}
        started = plan.get("started")
        if started is not None:
            started.set()
        release = plan.get("release")
        if release is not None:
            release.wait(timeout=4)
        delay = plan.get("delay", 0)
        if delay:
            time.sleep(delay)
        status = plan.get("status", 200)
        if "body" in plan:
            response_body = plan["body"]
        elif self.protocol == "ollama":
            response_body = json.dumps(
                {
                    "model": model,
                    "response": plan.get("text", "synthetic-local-result"),
                    "done": True,
                    "done_reason": "stop",
                }
            ).encode()
        else:
            response_body = json.dumps(
                {
                    "model": model,
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": plan.get("text", "synthetic-cloud-result")
                            },
                        }
                    ],
                }
            ).encode()
        handler.send_response(status)
        for key, value in plan.get("headers", {}).items():
            handler.send_header(key, value)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(response_body)))
        handler.end_headers()
        try:
            handler.wfile.write(response_body)
        except (BrokenPipeError, ConnectionResetError):
            pass


class FakeProviderServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, protocol: str, tls_context=None):
        self.state = ProviderState(protocol)
        handler = self.make_handler()
        super().__init__(("127.0.0.1", 0), handler)
        if tls_context is not None:
            self.socket = tls_context.wrap_socket(self.socket, server_side=True)

    def make_handler(self):
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def do_POST(self):
                expected = (
                    "/api/generate"
                    if state.protocol == "ollama"
                    else "/v1/chat/completions"
                )
                if self.path != expected:
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "-1"))
                    if length < 0 or length > 65536:
                        self.send_error(413)
                        return
                    body = json.loads(self.rfile.read(length))
                    state.dispatch(self, body)
                except (ValueError, json.JSONDecodeError):
                    self.send_error(400)

        return Handler


class FakeWorkerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        class WorkerHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def do_GET(self):
                if self.path != "/readyz":
                    self.send_error(404)
                    return
                body = b'{"status":"ready"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        super().__init__(("127.0.0.1", 0), WorkerHandler)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(url: str, payload: dict | None = None, token: str | None = TOKEN):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, method="GET" if payload is None else "POST")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=5) as response:
            body = response.read()
            status = response.status
    except HTTPError as exc:
        body = exc.read()
        status = exc.code
    try:
        return status, json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, body


class GatewayAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.TemporaryDirectory(prefix="m05b-gateway-acceptance-")
        cls.binary = Path(cls.workdir.name) / "gateway"
        cls.certificate = Path(cls.workdir.name) / "fake-provider.crt"
        cls.private_key = Path(cls.workdir.name) / "fake-provider.key"
        certificate = subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(cls.private_key),
                "-out",
                str(cls.certificate),
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if certificate.returncode:
            raise RuntimeError(
                f"test TLS certificate generation failed: {certificate.stderr[-1000:]}"
            )
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cls.certificate, cls.private_key)
        result = subprocess.run(
            ["go", "build", "-o", str(cls.binary), "./cmd/gateway"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"Gateway build failed: {result.stderr[-2000:]}")
        cls.local = FakeProviderServer("ollama")
        cls.cloud = FakeProviderServer("openai", tls)
        cls.worker = FakeWorkerServer()
        cls.threads = []
        for server in (cls.local, cls.cloud, cls.worker):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)
        cls.evidence = {
            "scope": "compiled Gateway with deterministic loopback providers; offline only",
            "scenarios": [],
        }

    @classmethod
    def tearDownClass(cls):
        for server in (cls.local, cls.cloud, cls.worker):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=3)
        evidence_path = Path(cls.workdir.name) / "offline-gateway-acceptance.json"
        temp = evidence_path.with_suffix(".tmp")
        temp.write_text(json.dumps(cls.evidence, indent=2) + "\n")
        temp.chmod(0o600)
        os.replace(temp, evidence_path)
        cls.workdir.cleanup()

    @contextlib.contextmanager
    def gateway(
        self,
        *,
        policy="ordered",
        allow_cloud=True,
        models=None,
        cloud_key=True,
        request_timeout="240s",
        local_timeout="180s",
    ):
        config = yaml.safe_load(CONFIG_SOURCE.read_text())
        config["listen_host"] = "127.0.0.1"
        config["listen_port"] = free_port()
        config["stt_url"] = f"http://127.0.0.1:{self.worker.server_port}"
        config["tts_url"] = config["stt_url"]
        transform = config["text_transform"]
        transform["prompt_file"] = str(
            ROOT / "configs/prompts/text-transformation-system.txt"
        )
        transform["selection"]["policy"] = policy
        transform["selection"]["allow_cloud"] = allow_cloud
        transform["request_timeout"] = request_timeout
        if local_timeout != "180s":
            transform["transport"]["connect_timeout"] = "100ms"
            transform["transport"]["tls_handshake_timeout"] = "100ms"
        for provider in transform["providers"]:
            if provider["id"] == "host-ollama":
                provider["endpoint"] = (
                    f"http://127.0.0.1:{self.local.server_port}/api/generate"
                )
                provider["timeout"] = local_timeout
            elif provider["id"] == "groq":
                provider["endpoint"] = (
                    f"https://127.0.0.1:{self.cloud.server_port}/v1/chat/completions"
                )
                provider["timeout"] = (
                    "30s" if request_timeout == "240s" else request_timeout
                )
        if models is not None:
            model_map = {model["id"]: model for model in transform["models"]}
            transform["models"] = [model_map[model_id] for model_id in models]
        config_path = Path(self.workdir.name) / f"gateway-{free_port()}.yaml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        config_path.chmod(0o600)
        env = os.environ.copy()
        env["SPEECH_API_TOKEN"] = TOKEN
        env["SSL_CERT_FILE"] = str(self.certificate)
        env.pop("GROQ_API_KEY", None)
        if cloud_key:
            env["GROQ_API_KEY"] = CLOUD_KEY
        log_path = Path(self.workdir.name) / f"gateway-{config['listen_port']}.log"
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [str(self.binary), "--config", str(config_path)],
                cwd=ROOT,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            base = f"http://127.0.0.1:{config['listen_port']}"
            yielded = False
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(
                            f"Gateway exited during startup ({process.returncode})"
                        )
                    try:
                        status, health = request_json(base + "/healthz", token=None)
                        if status == 200 and health.get("status") == "alive":
                            break
                    except (URLError, TimeoutError, ConnectionError, ValueError):
                        time.sleep(0.05)
                else:
                    self.fail("Gateway did not become healthy")
                yield base, process
                yielded = True
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    exit_status = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    exit_status = process.wait(timeout=3)
                if yielded:
                    self.assertEqual(
                        exit_status, 0, "isolated Gateway failed clean shutdown"
                    )

    def post(self, base: str, payload: dict, token: str | None = TOKEN):
        return request_json(base + "/v1/text/transformations", payload, token)

    def record(self, name: str, details: dict):
        self.evidence["scenarios"].append({"name": name, **details})

    def test_gateway_api_selection_fallback_restrictions_and_metadata(self):
        # Deliberately put cloud first: ordered preserves config order, while
        # local_first and cloud_first apply their respective locality order.
        order = ["groq-qwen", "local-qwen", "groq-gpt-oss"]
        for policy, expected_provider, expected_model in (
            ("ordered", "groq", "groq-qwen"),
            ("local_first", "host-ollama", "local-qwen"),
            ("cloud_first", "groq", "groq-qwen"),
        ):
            self.local.state.reset()
            self.cloud.state.reset()
            with self.gateway(policy=policy, models=order) as (base, _process):
                status, response = self.post(
                    base, {"text": "Synthetic policy check.", "mode": "written"}
                )
            self.assertEqual(status, 200)
            self.assertEqual(response["provider"], expected_provider)
            self.assertEqual(response["model"], expected_model)
            self.assertFalse(response["fallback_occurred"])
            calls = self.local.state.calls + self.cloud.state.calls
            self.assertEqual(len(calls), 1)
            if expected_provider == "groq":
                self.assertTrue(calls[0]["authorization_present"])
            self.assertEqual(
                calls[0]["model"],
                "qwen/qwen3.8-27b"
                if expected_provider == "groq"
                else "qwen3.5:9b-q4_K_M",
            )
            self.record(
                f"selection_{policy}",
                {
                    "status": status,
                    "model": response["model"],
                    "provider": response["provider"],
                    "provider_calls": len(calls),
                },
            )

        self.local.state.reset(
            {
                "qwen3.5:9b-q4_K_M": [
                    {"status": 500, "body": b'{"error":"synthetic failure"}'}
                ]
            }
        )
        self.cloud.state.reset()
        with self.gateway(models=["local-qwen", "groq-qwen", "groq-gpt-oss"]) as (
            base,
            _process,
        ):
            status, response = self.post(
                base, {"text": "Synthetic fallback check.", "mode": "written"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(
            (response["model"], response["provider"], response["fallback_occurred"]),
            ("groq-qwen", "groq", True),
        )
        self.assertEqual(
            [call["model"] for call in self.local.state.calls + self.cloud.state.calls],
            ["qwen3.5:9b-q4_K_M", "qwen/qwen3.8-27b"],
        )
        self.record(
            "automatic_fallback",
            {
                "status": status,
                "model": response["model"],
                "provider": response["provider"],
                "fallback_occurred": response["fallback_occurred"],
                "local_calls": len(self.local.state.calls),
                "cloud_calls": len(self.cloud.state.calls),
            },
        )

        rate_models = ["groq-qwen", "groq-gpt-oss", "local-qwen"]
        model_429 = {
            "status": 429,
            "headers": {"X-RateLimit-Scope": "model"},
            "body": b'{"error":{"code":"model_rate_limit"}}',
        }
        self.cloud.state.reset({"qwen/qwen3.8-27b": [model_429]})
        self.local.state.reset()
        with self.gateway(policy="cloud_first", models=rate_models) as (base, _process):
            status, response = self.post(
                base, {"text": "Synthetic model limit check.", "mode": "written"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(
            (response["model"], response["fallback_occurred"]), ("groq-gpt-oss", True)
        )
        self.assertEqual(
            [call["model"] for call in self.cloud.state.calls],
            ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"],
        )
        self.record(
            "model_rate_limit",
            {
                "status": status,
                "selected_model": response["model"],
                "cloud_provider_calls": len(self.cloud.state.calls),
                "local_provider_calls": len(self.local.state.calls),
            },
        )

        provider_429 = {
            "status": 429,
            "headers": {"X-RateLimit-Scope": "provider"},
            "body": b'{"error":{"code":"provider_rate_limit"}}',
        }
        self.cloud.state.reset({"qwen/qwen3.8-27b": [provider_429]})
        self.local.state.reset()
        with self.gateway(policy="cloud_first", models=rate_models) as (base, _process):
            status, response = self.post(
                base, {"text": "Synthetic provider limit check.", "mode": "written"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(
            (response["model"], response["provider"], response["fallback_occurred"]),
            ("local-qwen", "host-ollama", True),
        )
        self.assertEqual(
            [call["model"] for call in self.cloud.state.calls], ["qwen/qwen3.8-27b"]
        )
        self.assertEqual(len(self.local.state.calls), 1)
        self.record(
            "provider_rate_limit",
            {
                "status": status,
                "selected_model": response["model"],
                "cloud_provider_calls": len(self.cloud.state.calls),
                "local_provider_calls": len(self.local.state.calls),
            },
        )

    def test_gateway_api_explicit_cloud_auth_passthrough_and_missing_credentials(self):
        self.local.state.reset(
            {
                "qwen3.5:9b-q4_K_M": [
                    {"status": 500, "body": b'{"error":"synthetic failure"}'},
                    {"status": 500, "body": b'{"error":"synthetic failure"}'},
                ]
            }
        )
        self.cloud.state.reset()
        with self.gateway(models=["local-qwen", "groq-qwen", "groq-gpt-oss"]) as (
            base,
            _process,
        ):
            raw_text = "Raw unchanged\r\n  synthetic  "
            status, response = self.post(base, {"text": raw_text})
            self.assertEqual(status, 200)
            self.assertEqual(response["transformed_text"], raw_text)
            self.assertFalse(response["generated"])
            self.assertIsNone(response["model"])
            self.assertIsNone(response["provider"])
            self.assertEqual(
                len(self.local.state.calls) + len(self.cloud.state.calls), 0
            )
            unauthorized_status, _ = self.post(
                base,
                {
                    "text": "Synthetic auth check.",
                    "mode": "written",
                    "model": "groq-qwen",
                },
                token="wrong",
            )
            self.assertEqual(unauthorized_status, 401)
            self.assertEqual(
                len(self.local.state.calls) + len(self.cloud.state.calls), 0
            )
            explicit_status, explicit = self.post(
                base,
                {
                    "text": "Synthetic explicit check.",
                    "mode": "written",
                    "model": "local-qwen",
                },
            )
            self.assertEqual(explicit_status, 503)
            self.assertEqual(explicit["code"], "text_transform_failed")
            self.assertEqual(len(self.cloud.state.calls), 0)
            local_only_status, _ = self.post(
                base,
                {
                    "text": "Synthetic local-only check.",
                    "mode": "written",
                    "local_only": True,
                },
            )
            self.assertEqual(local_only_status, 503)
            self.assertEqual(len(self.cloud.state.calls), 0)
        self.record(
            "raw_auth_explicit_and_local_only",
            {
                "raw_passthrough_status": status,
                "unauthorized_status": unauthorized_status,
                "explicit_failure_status": explicit_status,
                "cloud_calls": len(self.cloud.state.calls),
            },
        )

        self.local.state.reset()
        self.cloud.state.reset()
        with self.gateway(
            allow_cloud=False, models=["local-qwen", "groq-qwen", "groq-gpt-oss"]
        ) as (base, _process):
            status, body = self.post(
                base,
                {
                    "text": "Synthetic cloud prohibition.",
                    "mode": "written",
                    "model": "groq-qwen",
                },
            )
            self.assertEqual(status, 403)
            self.assertEqual(body["code"], "cloud_not_allowed")
            self.assertEqual(
                len(self.local.state.calls) + len(self.cloud.state.calls), 0
            )
        self.record(
            "global_cloud_prohibition",
            {
                "status": status,
                "provider_calls": len(self.local.state.calls)
                + len(self.cloud.state.calls),
            },
        )

        self.cloud.state.reset()
        with self.gateway(models=["groq-qwen", "local-qwen"], cloud_key=False) as (
            base,
            _process,
        ):
            ready_status, ready = request_json(base + "/readyz", token=None)
            status, body = self.post(
                base,
                {
                    "text": "Synthetic missing credential.",
                    "mode": "written",
                    "model": "groq-qwen",
                },
            )
            self.assertEqual(ready_status, 200)
            self.assertEqual(ready["status"], "ready")
            self.assertEqual(status, 503)
            self.assertEqual(body["code"], "provider_unavailable")
            self.assertEqual(len(self.cloud.state.calls), 0)
        self.record(
            "missing_cloud_credential_speech_readiness",
            {
                "ready_status": ready_status,
                "transform_status": status,
                "cloud_calls": len(self.cloud.state.calls),
            },
        )

    def test_gateway_api_provider_errors_timeout_and_invalid_response(self):
        models = ["local-qwen"]
        self.local.state.reset(
            {
                "qwen3.5:9b-q4_K_M": [
                    {"status": 500, "body": b'{"error":"synthetic provider error"}'},
                    {"body": b'{"done":true,"done_reason":"stop"}'},
                ]
            }
        )
        self.cloud.state.reset()
        with self.gateway(allow_cloud=False, models=models) as (base, _process):
            error_status, error = self.post(
                base,
                {
                    "text": "Synthetic provider error.",
                    "mode": "written",
                    "model": "local-qwen",
                },
            )
            invalid_status, invalid = self.post(
                base,
                {
                    "text": "Synthetic invalid completion.",
                    "mode": "written",
                    "model": "local-qwen",
                },
            )
        self.assertEqual((error_status, error["code"]), (503, "text_transform_failed"))
        self.assertEqual(
            (invalid_status, invalid["code"]), (502, "invalid_provider_response")
        )
        self.record(
            "provider_error_and_invalid_response",
            {
                "provider_error_status": error_status,
                "provider_error_code": error["code"],
                "invalid_status": invalid_status,
                "invalid_code": invalid["code"],
                "local_calls": len(self.local.state.calls),
                "cloud_calls": len(self.cloud.state.calls),
            },
        )

        self.local.state.reset({"qwen3.5:9b-q4_K_M": [{"delay": 2.0}]})
        self.cloud.state.reset()
        with self.gateway(
            allow_cloud=False, models=models, request_timeout="1s", local_timeout="1s"
        ) as (base, _process):
            timeout_status, timeout = self.post(
                base,
                {
                    "text": "Synthetic timeout.",
                    "mode": "written",
                    "model": "local-qwen",
                },
            )
        self.assertEqual(timeout_status, 504)
        self.assertEqual(timeout["code"], "deadline_exceeded")
        self.assertEqual(len(self.cloud.state.calls), 0)
        self.record(
            "total_timeout",
            {
                "status": timeout_status,
                "code": timeout["code"],
                "local_calls": len(self.local.state.calls),
                "cloud_calls": len(self.cloud.state.calls),
            },
        )

    def test_gateway_shutdown_cancels_active_provider_request(self):
        started = threading.Event()
        release = threading.Event()
        self.local.state.reset(
            {"qwen3.5:9b-q4_K_M": [{"started": started, "release": release}]}
        )
        self.cloud.state.reset()
        request_result: dict = {}
        with self.gateway(models=["local-qwen", "groq-qwen"]) as (base, process):

            def submit():
                request_result["result"] = self.post(
                    base,
                    {"text": "Synthetic shutdown cancellation.", "mode": "written"},
                )

            thread = threading.Thread(target=submit, daemon=True)
            thread.start()
            self.assertTrue(
                started.wait(timeout=3), "fake Ollama request did not start"
            )
            process.terminate()
            thread.join(timeout=3)
            self.assertFalse(
                thread.is_alive(), "Gateway request did not finish on shutdown"
            )
            self.assertNotEqual(request_result["result"][0], 200)
            self.assertEqual(
                len(self.cloud.state.calls),
                0,
                "shutdown must not dispatch cloud fallback",
            )
            release.set()
        self.record(
            "gateway_shutdown_cancellation",
            {
                "request_status": request_result["result"][0],
                "local_calls": len(self.local.state.calls),
                "cloud_calls": len(self.cloud.state.calls),
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
