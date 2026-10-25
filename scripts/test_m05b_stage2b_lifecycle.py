"""Offline process-lifecycle regression for the private M05B Gateway profile."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "configs/gateway-text.example.yaml"
SYNTHETIC_OUTPUT = "Synthetic offline transformation result."


class FakeEndpoints(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, FakeHandler)
        self.provider_requests = 0


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        if self.path != "/readyz":
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        if self.path != "/api/generate":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        if (
            payload.get("model") != "qwen3.5:9b-q4_K_M"
            or payload.get("stream") is not False
        ):
            self.send_error(400)
            return
        self.server.provider_requests += 1
        body = json.dumps(
            {"response": SYNTHETIC_OUTPUT, "done": True, "done_reason": "stop"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request_json(url: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, method="GET" if payload is None else "POST")
    if payload is not None:
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=8) as response:
        return response.status, json.loads(response.read())


class GatewayProcessLifecycleTest(unittest.TestCase):
    def test_gateway_stays_alive_for_sequential_authenticated_requests(self):
        evidence = {
            "scenario": "single-controller owns Gateway across readiness and sequential requests",
            "provider": "local fake Ollama protocol endpoint",
            "requests": [],
        }
        process = None
        fake = None
        fake_thread = None
        log_file = None

        with tempfile.TemporaryDirectory(prefix="stage2b-lifecycle-") as workdir:
            evidence_path = Path(workdir) / "offline-lifecycle.json"
            binary = Path(workdir) / "gateway"
            build = subprocess.run(
                ["go", "build", "-o", str(binary), "./cmd/gateway"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            fake = FakeEndpoints(("127.0.0.1", 0))
            fake_thread = threading.Thread(target=fake.serve_forever, daemon=True)
            fake_thread.start()
            fake_url = f"http://127.0.0.1:{fake.server_port}"

            config = yaml.safe_load(CONFIG_FILE.read_text())
            config["listen_host"] = "127.0.0.1"
            config["listen_port"] = free_loopback_port()
            config["stt_url"] = fake_url
            config["tts_url"] = fake_url
            transform = config["text_transform"]
            transform["prompt_file"] = str(
                ROOT / "configs/prompts/text-transformation-system.txt"
            )
            transform["selection"]["allow_cloud"] = False
            for provider in transform["providers"]:
                if provider["type"] == "ollama":
                    provider["endpoint"] = f"{fake_url}/api/generate"
            test_config = Path(workdir) / "gateway.yaml"
            test_config.write_text(yaml.safe_dump(config, sort_keys=False))
            test_config.chmod(0o600)

            token = "synthetic-stage2b-offline-token-00000000"
            env = os.environ.copy()
            env.pop("GROQ_API_KEY", None)
            env["SPEECH_API_TOKEN"] = token
            log_path = Path(workdir) / "offline-gateway.log"
            log_file = log_path.open("w", encoding="utf-8")
            log_path.chmod(0o600)
            try:
                process = subprocess.Popen(
                    [str(binary), "--config", str(test_config)],
                    cwd=ROOT,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                evidence["pid"] = process.pid
                evidence["startup"] = "launched"
                gateway_url = f"http://127.0.0.1:{config['listen_port']}"

                ready_state = None
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(
                            f"Gateway exited before readiness: {process.returncode}"
                        )
                    try:
                        status, health = request_json(f"{gateway_url}/healthz", token)
                        ready_status, ready = request_json(
                            f"{gateway_url}/readyz", token
                        )
                        if (
                            status == 200
                            and health.get("status") == "alive"
                            and ready_status == 200
                            and ready.get("status") == "ready"
                        ):
                            ready_state = "alive and ready"
                            break
                    except (
                        URLError,
                        TimeoutError,
                        http.client.HTTPException,
                        json.JSONDecodeError,
                    ):
                        time.sleep(0.1)
                self.assertEqual(ready_state, "alive and ready")
                self.assertIsNone(
                    process.poll(), "Gateway exited immediately after readiness"
                )
                evidence["readiness"] = ready_state

                raw_payloads = [
                    {"text": "Synthetic raw passthrough one."},
                    {"text": "Synthetic raw passthrough two."},
                ]
                for payload in raw_payloads:
                    status, response = request_json(
                        f"{gateway_url}/v1/text/transformations", token, payload
                    )
                    self.assertEqual(status, 200)
                    self.assertEqual(response["original_text"], payload["text"])
                    self.assertEqual(response["transformed_text"], payload["text"])
                    self.assertFalse(response["generated"])
                    self.assertIsNone(response["model"])
                    self.assertIsNone(response["provider"])
                    self.assertIsNone(
                        process.poll(), "Gateway exited between raw requests"
                    )
                    evidence["requests"].append(
                        {
                            "kind": "authenticated_raw_passthrough",
                            "status": status,
                            "alive_after": True,
                        }
                    )

                generated_request = {
                    "text": "Synthetic sentence for offline transformation.",
                    "mode": "written",
                    "format": "concise",
                    "target_language": "none",
                    "model": "local-qwen",
                    "local_only": True,
                }
                status, response = request_json(
                    f"{gateway_url}/v1/text/transformations", token, generated_request
                )
                self.assertEqual(status, 200)
                self.assertEqual(response["transformed_text"], SYNTHETIC_OUTPUT)
                self.assertTrue(response["generated"])
                self.assertEqual(response["model"], "local-qwen")
                self.assertEqual(response["provider"], "host-ollama")
                self.assertFalse(response["fallback_occurred"])
                self.assertEqual(fake.provider_requests, 1)
                self.assertIsNone(
                    process.poll(), "Gateway exited after fake-provider request"
                )
                evidence["requests"].append(
                    {
                        "kind": "fake_provider_transformation",
                        "status": status,
                        "alive_after": True,
                    }
                )
                evidence["fake_provider_requests"] = fake.provider_requests
                evidence["alive_between_requests"] = True
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                    try:
                        evidence["exit_status"] = process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        evidence["exit_status"] = process.wait(timeout=5)
                        evidence["forced_kill"] = True
                    evidence["cleaned_up"] = process.poll() is not None
                if fake is not None:
                    fake.shutdown()
                    fake.server_close()
                if fake_thread is not None:
                    fake_thread.join(timeout=3)
                if log_file is not None:
                    log_file.close()
                evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
                evidence_path.chmod(0o600)

        self.assertTrue(evidence.get("cleaned_up"))
        self.assertFalse(evidence.get("forced_kill", False))
        self.assertEqual(evidence.get("exit_status"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
