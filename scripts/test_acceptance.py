"""GPU-free M01 acceptance checks."""

import ast
import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer

import yaml
from openapi_spec_validator import validate
from services.worker.server import handler, load_config
from services.tts.config import load_config as load_tts_config

ROOT = Path(__file__).resolve().parents[1]


class Acceptance(unittest.TestCase):
    def test_private_audio_excluded(self):
        for filename in (".gitignore", ".dockerignore"):
            text = (ROOT / filename).read_text()
            for suffix in ("m4a", "wav", "mp3", "flac", "ogg", "pcm"):
                self.assertIn(f"*.{suffix}", text)

    def test_worker_config(self):
        for kind in ("stt",):
            path = ROOT / f"configs/{kind}.yaml"
            valid = yaml.safe_load(path.read_text())
            self.assertEqual(load_config(path, kind), valid)
            for host in ("localhost", "worker.internal", "192.0.2.10"):
                with tempfile.TemporaryDirectory() as directory:
                    candidate = {**valid, "listen_host": host}
                    host_config = Path(directory) / "host.yaml"
                    host_config.write_text(yaml.safe_dump(candidate))
                    self.assertEqual(load_config(host_config, kind), candidate)
            invalid = [
                {**valid, "extra": 1},
                {},
                {**valid, "listen_port": 0},
                {**valid, "listen_port": 65536},
                {**valid, "socket_timeout_seconds": True},
                {**valid, "socket_timeout_seconds": 0},
                {**valid, "socket_timeout_seconds": 86401},
                {**valid, "poll_interval_seconds": True},
                {**valid, "poll_interval_seconds": 0},
                {**valid, "poll_interval_seconds": 61},
                {**valid, "listen_host": "http://localhost"},
                {**valid, "listen_host": "bad host"},
                {**valid, "listen_host": "bad_host"},
                {**valid, "listen_host": "256.0.0.1"},
                {**valid, "listen_host": "::1"},
                {**valid, "kind": "other"},
            ]
            for data in invalid:
                with tempfile.TemporaryDirectory() as directory:
                    bad = Path(directory) / "bad.yaml"
                    bad.write_text(yaml.safe_dump(data))
                    with self.assertRaises(ValueError):
                        load_config(bad, kind)
            for port in (1, 65535):
                boundary = {**valid, "listen_port": port}
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "boundary.yaml"
                    path.write_text(yaml.safe_dump(boundary))
                    self.assertEqual(load_config(path, kind), boundary)
            with tempfile.TemporaryDirectory() as directory:
                bad = Path(directory) / "duplicate.yaml"
                bad.write_text(
                    (ROOT / f"configs/{kind}.yaml").read_text() + "listen_port: 1\n"
                )
                with self.assertRaises(ValueError):
                    load_config(bad, kind)
        self.assertEqual(load_tts_config(ROOT / "configs/tts.yaml")["kind"], "tts")

    def test_worker_http(self):
        for kind in ("stt",):
            config = load_config(ROOT / f"configs/{kind}.yaml", kind)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler(config))
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                for method, path, expected in [
                    ("GET", "/metrics", 200),
                    ("GET", "/healthz", 200),
                    ("GET", "/readyz", 503),
                    ("POST", "/internal/v1/speech", 404),
                    ("POST", "/internal/v1/transcriptions", 404),
                ]:
                    connection = http.client.HTTPConnection(
                        *server.server_address, timeout=2
                    )
                    connection.request(method, path)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    response.read()
                    connection.close()
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def test_openapi(self):
        for path in (ROOT / "api/openapi").glob("*.yaml"):
            validate(yaml.safe_load(path.read_text()))
        public = yaml.safe_load((ROOT / "api/openapi/public-v1.yaml").read_text())
        for path, operations in public["paths"].items():
            for method, operation in operations.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for status, response in operation["responses"].items():
                    self.assertIn(
                        "X-Request-ID",
                        response.get("headers", {}),
                        f"{method.upper()} {path} response {status} lacks request ID header",
                    )
        transcribe = public["paths"]["/v1/stt/transcriptions"]["post"]
        self.assertEqual(transcribe["x-maxRequestSizeBytes"], 26214400)
        self.assertEqual(
            yaml.safe_load((ROOT / "configs/gateway.yaml").read_text())[
                "max_request_bytes"
            ],
            transcribe["x-maxRequestSizeBytes"],
        )
        self.assertIn("413", transcribe["responses"])
        transform = public["paths"]["/v1/text/transformations"]["post"]
        prompt_hash = transform["responses"]["200"]["headers"]["X-Speech-Prompt-SHA256"]
        self.assertEqual(prompt_hash["schema"]["pattern"], "^[a-f0-9]{64}$")
        self.assertNotIn("/v1/stt/models", public["paths"])
        self.assertEqual(public["security"], [{"bearerAuth": []}])
        voices = public["paths"]["/v1/tts/voices"]["get"]
        self.assertEqual(set(voices["responses"]), {"200", "401", "403", "500", "503"})
        tts = public["paths"]["/v1/tts/speech"]["post"]
        self.assertEqual(tts["x-maxRequestSizeBytes"], 65536)
        self.assertEqual(
            tts["requestBody"]["content"]["application/json"]["schema"]["properties"][
                "text"
            ]["maxLength"],
            49152,
        )
        self.assertEqual(
            tts["requestBody"]["content"]["application/json"]["schema"]["properties"][
                "input_format"
            ]["enum"],
            ["text", "ssml"],
        )
        self.assertEqual(
            tts["requestBody"]["content"]["application/json"]["schema"]["properties"][
                "input_format"
            ]["default"],
            "text",
        )
        for name in ("internal-stt-v1.yaml", "internal-tts-v1.yaml"):
            internal = yaml.safe_load((ROOT / "api/openapi" / name).read_text())
            operation = next(iter(internal["paths"].values()))["post"]
            expected_limit = 65536 if name == "internal-tts-v1.yaml" else 26214400
            self.assertEqual(operation["x-maxRequestSizeBytes"], expected_limit)
            self.assertNotIn("401", operation["responses"])
            self.assertNotIn("403", operation["responses"])
            not_ready = internal["paths"]["/readyz"]["get"]["responses"]["503"]
            self.assertEqual(
                not_ready["content"]["application/json"]["schema"]["$ref"],
                "#/components/schemas/Error",
            )

    def test_compose_isolation(self):
        compose = yaml.safe_load(
            (ROOT / "deployments/compose/compose.yaml").read_text()
        )
        self.assertEqual(
            set(compose["networks"]),
            {"gateway_publish", "stt_private", "tts_private"},
        )
        self.assertTrue(
            all(
                compose["networks"][name]["internal"]
                for name in ("stt_private", "tts_private")
            )
        )
        self.assertEqual(
            compose["networks"]["gateway_publish"]["driver_opts"][
                "com.docker.network.bridge.enable_ip_masquerade"
            ],
            "false",
        )
        self.assertEqual(
            set(compose["services"]["gateway"]["networks"]),
            {"gateway_publish", "stt_private", "tts_private"},
        )
        self.assertEqual(set(compose["services"]["stt"]["networks"]), {"stt_private"})
        self.assertEqual(set(compose["services"]["tts"]["networks"]), {"tts_private"})
        for name, service in compose["services"].items():
            self.assertTrue(service["read_only"])
            self.assertEqual(service["cap_drop"], ["ALL"])
            self.assertIn("no-new-privileges:true", service["security_opt"])
            self.assertNotIn("privileged", service)
            self.assertNotIn("network_mode", service)
            self.assertIn("mem_limit", service)
            if name != "gateway":
                self.assertNotIn("ports", service)
                self.assertNotIn("depends_on", service)
            for volume in service.get("volumes", []):
                self.assertTrue(volume.endswith(":ro"))

    def test_no_deployment_addresses_or_worker_coupling(self):
        for folder in ("cmd", "internal", "services"):
            for path in (ROOT / folder).rglob("*"):
                if path.suffix not in {".py", ".go"} or "test" in path.name:
                    continue
                text = path.read_text()
                # Fixed XML/SSML vocabulary namespaces are protocol identifiers,
                # not deployment endpoints or service addresses.
                for namespace in (
                    "http://www.w3.org/2001/10/synthesis",
                    "http://www.w3.org/XML/1998/namespace",
                ):
                    text = text.replace(namespace, "")
                relative_path = path.relative_to(ROOT).as_posix()
                if relative_path == "internal/gateway/groq_stt.go":
                    # This fixed endpoint is a provider protocol constant, not
                    # a deployment-specific address.
                    text = text.replace(
                        "https://api.groq.com/openai/v1/audio/transcriptions", ""
                    )
                if relative_path in {
                    "internal/gateway/groq_stt.go",
                    "internal/config/config.go",
                }:
                    # These exact model IDs form the validated external
                    # provider allowlist, not a local deployment model choice.
                    text = text.replace("whisper-large-v3-turbo", "")
                    text = text.replace("whisper-large-v3", "")
                for forbidden in (
                    "http://",
                    "https://",
                    "127.0.0.1",
                    "0.0.0.0",
                    "large-v3",
                ):
                    self.assertNotIn(forbidden, text, str(path))
        for kind, other in (("stt", "tts"), ("tts", "stt")):
            for path in (ROOT / f"services/{kind}").glob("*.py"):
                tree = ast.parse(path.read_text())
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        self.assertNotIn(f"services.{other}", node.module or "")
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertNotIn(f"services.{other}", alias.name)


if __name__ == "__main__":
    unittest.main()
