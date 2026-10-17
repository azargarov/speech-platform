from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


class HostPreflightImportTests(unittest.TestCase):
    def test_launcher_config_preflight_does_not_import_container_runtime(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = yaml.safe_load(
                (repository / "configs/stt-application-cpu.example.yaml").read_text()
            )
            application["default_model"] = "smoke-small"
            model = application["models"][0]
            model["immutable_revision"] = "b" * 40
            model["artifacts"]["faster-whisper"]["manifest_sha256"] = "a" * 64
            application["device_policy"] = {
                "mode": "cuda",
                "preference": ["cuda"],
            }
            app_path = root / "application.yaml"
            app_path.write_text(json.dumps(application))
            deployment_path = root / "deployment.yaml"
            deployment_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "artifacts": {
                            "smoke-small": {
                                "directory": "/models/smoke-small",
                                "manifest": "/models/smoke-small-manifest.yaml",
                            }
                        },
                        "device_access": {
                            "cuda_device_index": 0,
                            "minimum_free_gpu_bytes_before_load": 12 * 1024**3,
                        },
                    }
                )
            )

            probe = r"""
import sys
from importlib.abc import MetaPathFinder

class ContainerOnlyBlocker(MetaPathFinder):
    blocked = {"aiohttp", "faster_whisper", "av", "ctranslate2", "torch"}
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.blocked:
            raise AssertionError("container-only import attempted: " + fullname)

sys.meta_path.insert(0, ContainerOnlyBlocker())
from scripts.launch_stt_cuda_diagnostic import _load_cuda_http_profile
app, deployment, profile = _load_cuda_http_profile(
    sys.argv[1], sys.argv[2], "b" * 40, "a" * 64
)
assert app.device_mode == "cuda"
assert deployment.cuda_device_index == 0
assert profile["compute_type"] == "float16"
print("host_preflight_config=pass")
"""
            env = dict(os.environ)
            env["PYTHONPATH"] = str(repository)
            result = subprocess.run(
                [sys.executable, "-c", probe, str(app_path), str(deployment_path)],
                cwd=repository,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "host_preflight_config=pass")


if __name__ == "__main__":
    unittest.main()
