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

ROOT = Path(__file__).resolve().parents[1]


class Acceptance(unittest.TestCase):
    def test_private_audio_excluded(self):
        for filename in (".gitignore", ".dockerignore"):
            text = (ROOT / filename).read_text()
            for suffix in ("m4a", "wav", "mp3", "flac", "ogg", "pcm"):
                self.assertIn(f"*.{suffix}", text)

    def test_worker_config(self):
        for kind in ("stt", "tts"):
            path = ROOT / f"configs/{kind}.yaml"
            valid = yaml.safe_load(path.read_text())
            self.assertEqual(load_config(path, kind), valid)
            invalid = [
                {**valid, "extra": 1},
                {},
                {**valid, "listen_port": 0},
                {**valid, "listen_port": 65536},
                {**valid, "max_request_bytes": -1},
                {**valid, "request_timeout_seconds": True},
                {**valid, "model_path": "relative"},
                {**valid, "kind": "other"},
            ]
            for data in invalid:
                with tempfile.TemporaryDirectory() as directory:
                    bad = Path(directory) / "bad.yaml"
                    bad.write_text(yaml.safe_dump(data))
                    with self.assertRaises(ValueError):
                        load_config(bad, kind)
            with tempfile.TemporaryDirectory() as directory:
                bad = Path(directory) / "duplicate.yaml"
                bad.write_text(path.read_text() + "listen_port: 1\n")
                with self.assertRaises(ValueError):
                    load_config(bad, kind)

    def test_worker_http(self):
        for kind in ("stt", "tts"):
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

    def test_compose_isolation(self):
        compose = yaml.safe_load(
            (ROOT / "deployments/compose/compose.yaml").read_text()
        )
        self.assertTrue(compose["networks"]["speech"]["internal"])
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
