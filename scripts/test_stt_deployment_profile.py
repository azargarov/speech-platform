from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.stt_deployment_profile import (
    compose_environment,
    load_and_validate,
    validate_rendered_compose,
    write_env_file,
)
from services.stt.artifacts import canonical_manifest_digest
from services.stt.config import load_application_config
from services.stt.domain import SpeechFailure


class DeploymentProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o750)
        self.group = os.getgid()
        self.release = self.root / "release"
        artifact_dir = self.release / "artifact"
        artifact_dir.mkdir(parents=True)
        payload = b"fixture model bytes"
        (artifact_dir / "model.bin").write_bytes(payload)
        revision = "a" * 40
        manifest = {
            "manifest_version": 1,
            "model": {
                "family": "whisper",
                "repository": "fixture/model",
                "revision": revision,
            },
            "artifact": {
                "format": "ctranslate2-whisper",
                "tool": "fixture-converter",
                "tool_version": "1.0",
            },
            "files": [
                {
                    "path": "model.bin",
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        manifest_path = self.release / "manifest.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
        self.manifest_digest = canonical_manifest_digest(manifest)

        application = yaml.safe_load(
            Path("configs/stt-application-cpu.example.yaml").read_text()
        )
        application["default_model"] = "large-v3-turbo"
        application["backend"]["options"]["compute_type_cuda"] = "float16"
        application["device_policy"] = {"mode": "cuda", "preference": ["cuda"]}
        application["models"][0].update(
            {
                "alias": "large-v3-turbo",
                "immutable_revision": revision,
                "artifacts": {
                    "faster-whisper": {
                        "ref": "large-v3-turbo",
                        "manifest_sha256": self.manifest_digest,
                        "format": "ctranslate2-whisper",
                    }
                },
            }
        )
        self.application_path = self.root / "application.yaml"
        self._write_yaml(self.application_path, application)

        deployment = {
            "schema_version": 2,
            "artifacts": {
                "large-v3-turbo": {
                    "directory": "/models/artifact",
                    "manifest": "/models/manifest.yaml",
                }
            },
            "device_access": {
                "cuda_device_index": 0,
                "minimum_free_gpu_bytes_before_load": 1024,
            },
        }
        self.deployment_path = self.root / "deployment.yaml"
        self._write_yaml(self.deployment_path, deployment)
        self.worker_path = Path("configs/stt.yaml")

        self.profile = {
            "schema_version": 1,
            "project_name": "speech-platform-test",
            "runtime": {
                "image": "registry.example.invalid/stt@sha256:" + "1" * 64,
                "image_id": "sha256:" + "3" * 64,
                "image_reference_verified": True,
                "image_role": "stt-worker",
                "platform": "linux/amd64",
                "base_image": "python:3.13.9-slim@sha256:" + "2" * 64,
                "base_image_platform": "linux/amd64",
                "base_image_platform_verified": True,
                "source_revision": "4" * 40,
                "source_revision_verified": True,
                "cuda_lock_sha256": hashlib.sha256(
                    Path("services/requirements-stt-cuda.lock").read_bytes()
                ).hexdigest(),
            },
            "model": {
                "alias": "large-v3-turbo",
                "revision": revision,
                "manifest_sha256": self.manifest_digest,
                "host_release_root": str(self.release),
                "container_artifact_directory": "/models/artifact",
                "container_manifest_path": "/models/manifest.yaml",
            },
            "device": {
                "host_physical_index": 0,
                "expected_host_uuid": "GPU-0123456789abcdef",
                "container_cuda_index": 0,
            },
            "artifact_access": {
                "service_uid": 65532,
                "service_gid": 65532,
                "supplementary_read_gid": self.group,
            },
            "resources": {
                "cpu_limit": 4.0,
                "memory_limit_bytes": 12 * 1024**3,
                "pids_limit": 128,
                "limits_reviewed": True,
            },
            "lifecycle": {
                "stop_grace_period_seconds": 125,
                "termination_margin_seconds": 3,
            },
            "healthcheck": {
                "interval_seconds": 10,
                "timeout_seconds": 3,
                "probe_timeout_seconds": 2,
                "retries": 3,
                "start_period_seconds": 130,
            },
        }
        for path in (self.release, self.release / "artifact"):
            path.chmod(0o750)
        (self.release / "manifest.yaml").chmod(0o640)
        (self.release / "artifact" / "model.bin").chmod(0o640)
        self.profile_path = self.root / "profile.yaml"
        self._write_profile()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _write_yaml(path, value):
        path.write_text(yaml.safe_dump(value, sort_keys=False))

    def _write_profile(self):
        self._write_yaml(self.profile_path, self.profile)

    def _validate(
        self,
        *,
        verify_files=True,
        dockerfile_path="deployments/compose/worker-stt-cuda.Dockerfile",
    ):
        return load_and_validate(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            dockerfile_path=dockerfile_path,
            verify_files=verify_files,
        )

    def _compose(self, validated):
        profile = validated["profile"]
        model = validated["model"]
        resources = validated["resources"]
        health = validated["healthcheck"]
        device = validated["device"]
        return {
            "name": profile["project_name"],
            "services": {
                "gateway": {
                    "networks": {"stt_private": None, "tts_private": None},
                    "ports": [{}],
                },
                "tts": {"networks": {"tts_private": None}},
                "stt": {
                    "profiles": ["cuda"],
                    "image": validated["image"],
                    "build": None,
                    "command": [
                        "services.stt.main",
                        "--config",
                        "/config/stt.yaml",
                        "--application-config",
                        "/config/stt-application.yaml",
                        "--deployment-config",
                        "/config/stt-deployment.yaml",
                    ],
                    "platform": "linux/amd64",
                    "pull_policy": "never",
                    "restart": "no",
                    "stop_grace_period": "125s",
                    "mem_limit": str(resources["memory_limit_bytes"]),
                    "cpus": resources["cpu_limit"],
                    "pids_limit": resources["pids_limit"],
                    "user": "65532:65532",
                    "read_only": True,
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "ports": [],
                    "networks": {"stt_private": None},
                    "group_add": [str(self.group)],
                    "environment": {
                        "STT_LISTEN_PORT": "8081",
                        "STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS": "2",
                    },
                    "deploy": {
                        "resources": {
                            "reservations": {
                                "devices": [
                                    {
                                        "driver": "nvidia",
                                        "device_ids": [
                                            str(device["host_physical_index"])
                                        ],
                                        "capabilities": ["gpu"],
                                    }
                                ]
                            }
                        }
                    },
                    "healthcheck": {
                        "test": ["CMD", "python", "-c", "GET /healthz"],
                        "interval": f"{health['interval_seconds']}s",
                        "timeout": f"{health['timeout_seconds']}s",
                        "start_period": f"{health['start_period_seconds']}s",
                        "retries": health["retries"],
                    },
                    "volumes": [
                        {
                            "source": str(self.worker_path.resolve()),
                            "target": "/config/stt.yaml",
                            "read_only": True,
                        },
                        {
                            "source": str(self.application_path.resolve()),
                            "target": "/config/stt-application.yaml",
                            "read_only": True,
                        },
                        {
                            "source": str(self.deployment_path.resolve()),
                            "target": "/config/stt-deployment.yaml",
                            "read_only": True,
                        },
                        {
                            "source": str(self.release),
                            "target": "/models",
                            "read_only": True,
                        },
                    ],
                    "labels": {
                        "com.speech-platform.image-role": "stt-worker",
                        "com.speech-platform.source-revision": profile["runtime"][
                            "source_revision"
                        ],
                        "com.speech-platform.cuda-lock-sha256": profile["runtime"][
                            "cuda_lock_sha256"
                        ],
                        "com.speech-platform.deployment-profile-sha256": validated[
                            "profile_sha256"
                        ],
                        "com.speech-platform.model-manifest-sha256": model[
                            "manifest_sha256"
                        ],
                        "com.speech-platform.model-revision": model["revision"],
                        "com.speech-platform.application-config-sha256": hashlib.sha256(
                            self.application_path.read_bytes()
                        ).hexdigest(),
                        "com.speech-platform.deployment-config-sha256": hashlib.sha256(
                            self.deployment_path.read_bytes()
                        ).hexdigest(),
                        "com.speech-platform.worker-config-sha256": hashlib.sha256(
                            self.worker_path.read_bytes()
                        ).hexdigest(),
                    },
                },
            },
            "networks": {
                "stt_private": {"internal": True},
                "tts_private": {"internal": True},
            },
        }

    def test_valid_profile_verifies_model_and_generates_private_compose_environment(
        self,
    ):
        validated = self._validate()
        environment = compose_environment(
            validated,
            self.application_path,
            self.deployment_path,
            self.worker_path,
        )
        self.assertEqual(environment["STT_HOST_GPU_DEVICE_ID"], "0")
        self.assertEqual(
            environment["STT_CUDA_IMAGE"], self.profile["runtime"]["image"]
        )
        private = self.root / "private"
        env_path = private / "stt-compose.env"
        write_env_file(env_path, environment)
        self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)
        self.assertIn("STT_MODEL_MANIFEST_SHA256", env_path.read_text())

    def test_rendered_compose_matches_profile_and_rejects_unsafe_overrides(self):
        validated = self._validate()
        rendered = self._compose(validated)
        validate_rendered_compose(rendered, validated)
        mutations = (
            (
                "gpu",
                lambda value: value["services"]["stt"]["deploy"]["resources"][
                    "reservations"
                ]["devices"][0].update(device_ids=["all"]),
            ),
            (
                "broad gpus allocation",
                lambda value: value["services"]["stt"].update(gpus="all"),
            ),
            (
                "ports",
                lambda value: value["services"]["stt"].update(ports=[{"target": 8081}]),
            ),
            (
                "health",
                lambda value: value["services"]["stt"]["healthcheck"].update(
                    test=["CMD", "python", "GET /readyz"]
                ),
            ),
            (
                "build",
                lambda value: value["services"]["stt"].update(build={"context": "."}),
            ),
            (
                "restart",
                lambda value: value["services"]["stt"].update(restart="always"),
            ),
            (
                "read-only",
                lambda value: value["services"]["stt"].update(read_only=False),
            ),
            (
                "image",
                lambda value: value["services"]["stt"].update(image="mutable:latest"),
            ),
            (
                "entrypoint command",
                lambda value: value["services"]["stt"].update(
                    command=["/opt/validation/probe.py"]
                ),
            ),
            (
                "config mount",
                lambda value: value["services"]["stt"]["volumes"][0].update(
                    source="/unexpected/stt.yaml"
                ),
            ),
            (
                "configuration identity",
                lambda value: value["services"]["stt"]["labels"].update(
                    {"com.speech-platform.worker-config-sha256": "0" * 64}
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(name=name):
                changed = copy.deepcopy(rendered)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validate_rendered_compose(changed, validated)

    def test_profile_template_and_mutable_image_fail_closed(self):
        template = yaml.safe_load(
            Path("configs/stt-deployment-profile-cuda.example.yaml").read_text()
        )
        self._write_yaml(self.profile_path, template)
        with self.assertRaisesRegex(ValueError, "replacement values"):
            self._validate()
        self.profile["runtime"]["image"] = "speech-platform:latest"
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "immutable sha256"):
            self._validate()

    def test_runtime_provenance_requires_platform_image_and_source_evidence(self):
        self.profile["runtime"]["base_image_platform_verified"] = False
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "manifest identity requires"):
            self._validate(verify_files=False)
        self.profile["runtime"]["base_image_platform_verified"] = True
        self.profile["runtime"]["image_reference_verified"] = False
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "verified against its image ID"):
            self._validate(verify_files=False)
        self.profile["runtime"]["image_reference_verified"] = True
        self.profile["runtime"]["source_revision_verified"] = False
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "source revision must be verified"):
            self._validate(verify_files=False)

    def test_validation_image_id_and_wrong_image_role_are_rejected(self):
        self.profile["runtime"]["image_id"] = (
            "sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540"
        )
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "validation image"):
            self._validate(verify_files=False)
        self.profile["runtime"]["image_id"] = "sha256:" + "3" * 64
        self.profile["runtime"]["image_role"] = "validation"
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "production STT worker"):
            self._validate(verify_files=False)

    def test_validation_repository_reference_is_rejected(self):
        self.profile["runtime"]["image"] = (
            "registry.example.invalid/speech-platform-cuda-validation@sha256:"
            + "1" * 64
        )
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "validation-only image references"):
            self._validate(verify_files=False)

    def test_cuda_dockerfile_must_be_production_entrypoint_and_locked(self):
        dockerfile = self.root / "Dockerfile"
        content = Path("deployments/compose/worker-stt-cuda.Dockerfile").read_text(
            encoding="utf-8"
        )
        dockerfile.write_text(
            content.replace(
                'ENTRYPOINT ["python", "-m"]',
                'ENTRYPOINT ["python", "/opt/validation/probe.py"]',
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "production STT image"):
            self._validate(verify_files=False, dockerfile_path=dockerfile)

    def test_cuda_dockerfile_exposes_all_locked_cuda_library_directories(self):
        original = Path("deployments/compose/worker-stt-cuda.Dockerfile").read_text(
            encoding="utf-8"
        )
        dockerfile = self.root / "Dockerfile"
        dockerfile.write_text(
            original.replace("nvidia/cuda_nvrtc/lib:", ""), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "production STT image"):
            self._validate(verify_files=False, dockerfile_path=dockerfile)

    def test_production_stt_module_entrypoint_delegates_to_worker_server(self):
        entrypoint = Path("services/stt/main.py").read_text(encoding="utf-8")
        self.assertIn("from services.worker.server import main", entrypoint)
        self.assertIn('main("stt")', entrypoint)

    def test_cuda_dockerfile_rejects_embedded_artifacts_and_download_steps(self):
        original = Path("deployments/compose/worker-stt-cuda.Dockerfile").read_text(
            encoding="utf-8"
        )
        cases = (
            ("COPY private/model.bin /models/model.bin\n", "copy only the lock"),
            ("RUN hf download some/model\n", "must not download models"),
        )
        for addition, error in cases:
            with self.subTest(addition=addition):
                dockerfile = self.root / "Dockerfile"
                dockerfile.write_text(original + addition, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, error):
                    self._validate(verify_files=False, dockerfile_path=dockerfile)

    def test_cuda_example_configuration_is_explicit_and_uses_approved_model(self):
        app = load_application_config("configs/stt-application-cuda.example.yaml")
        self.assertEqual(app.default_model, "large-v3-turbo")
        self.assertEqual(app.device_mode, "cuda")
        self.assertEqual(app.device_preference, ("cuda",))
        self.assertEqual(dict(app.backend_options)["compute_type_cuda"], "float16")

    def test_profile_rejects_gpu_mismatch_resource_review_and_timeout_mismatch(self):
        cases = (
            ("host GPU", "device", "host_physical_index", 1, "physical GPU 0"),
            (
                "resource review",
                "resources",
                "limits_reviewed",
                False,
                "require operator review",
            ),
            ("stop grace", "lifecycle", "stop_grace_period_seconds", 11, "stop grace"),
            (
                "health start period",
                "healthcheck",
                "start_period_seconds",
                100,
                "start period",
            ),
        )
        for name, section, key, value, error in cases:
            with self.subTest(name=name):
                original = self.profile[section][key]
                self.profile[section][key] = value
                self._write_profile()
                with self.assertRaisesRegex(ValueError, error):
                    self._validate(verify_files=False)
                self.profile[section][key] = original

    def test_artifact_permissions_and_integrity_fail_closed(self):
        model = self.release / "artifact" / "model.bin"
        model.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "insufficient or too broad"):
            self._validate()
        model.chmod(0o640)
        model.write_bytes(b"modified")
        with self.assertRaises(SpeechFailure):
            self._validate()

    def test_missing_artifact_release_is_not_accepted(self):
        self.profile["model"]["host_release_root"] = str(self.root / "absent")
        self._write_profile()
        with self.assertRaises(ValueError):
            self._validate()

    def test_untraversable_model_release_parent_fails_closed(self):
        self.root.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "parent is not traversable"):
            self._validate()


if __name__ == "__main__":
    unittest.main()
