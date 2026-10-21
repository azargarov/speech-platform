import hashlib
import tempfile
import unittest
from pathlib import Path

import yaml

from services.stt.artifacts import canonical_manifest_digest, verify_artifact
from services.stt.config import (
    ArtifactRoot,
    ModelConfig,
    load_application_config,
    load_deployment_config,
    resolve_backend,
)
from services.stt.domain import ModelIdentity, SpeechFailure


def application_data(**overrides):
    data = {
        "schema_version": 2,
        "default_model": "general",
        "backend": {"id": "fake", "options": {}},
        "models": [
            {
                "alias": "general",
                "family": "whisper",
                "immutable_revision": "b" * 40,
                "artifacts": {
                    "fake": {
                        "ref": "primary",
                        "manifest_sha256": "a" * 64,
                        "format": "fake-v1",
                    }
                },
            }
        ],
        "device_policy": {"mode": "cpu", "preference": ["cpu"]},
        "admission": {
            "max_active": 1,
            "max_queued": 2,
            "max_queued_audio_bytes": 20,
            "max_retained_audio_bytes": 30,
            "max_uploads": 2,
            "max_upload_bytes": 32,
            "max_request_bytes": 16,
            "max_result_bytes": 2048,
            "max_ipc_message_bytes": 65536,
            "queue_wait_timeout_seconds": 1,
            "request_timeout_seconds": 5,
        },
        "lifecycle": {
            "model_load_timeout_seconds": 2,
            "cooperative_cancel_grace_seconds": 0.1,
            "process_exit_timeout_seconds": 0.5,
            "shutdown_drain_timeout_seconds": 1,
        },
        "recovery": {"policy": "manual"},
    }
    data.update(overrides)
    return data


def faster_whisper_data():
    data = application_data()
    data["schema_version"] = 3
    data["backend"] = {
        "id": "faster-whisper",
        "options": {
            "cpu_threads": 2,
            "compute_type_cpu": "int8",
            "compute_type_cuda": "float16",
            "beam_size": 1,
        },
    }
    data["models"][0]["artifacts"]["faster-whisper"] = data["models"][0][
        "artifacts"
    ].pop("fake")
    data["audio_limits"] = {
        "sample_rate_hz": 16000,
        "max_duration_seconds": 60,
        "max_decoded_audio_bytes": 4_000_000,
    }
    return data


class ConfigValidation(unittest.TestCase):
    def load_data(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "application.yaml"
            path.write_text(yaml.safe_dump(data))
            return load_application_config(path)

    def test_valid_versioned_application_and_deployment_configs(self):
        config = self.load_data(application_data())
        self.assertEqual(config.default_model, "general")
        self.assertEqual(config.device_preference, ("cpu",))
        self.assertEqual(config.admission.max_queued, 2)
        self.assertEqual(config.admission.max_retained_audio_bytes, 30)
        self.assertTrue(config.models[0].translation_supported)
        disabled = application_data()
        disabled["models"][0]["translation_supported"] = False
        self.assertFalse(self.load_data(disabled).models[0].translation_supported)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.yaml"
            model_root = Path(directory) / "model-data"
            path.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "artifacts": {
                            "primary": {
                                "directory": str(model_root),
                                "manifest": str(model_root / "manifest.yaml"),
                            }
                        },
                    }
                )
            )
            deployed = load_deployment_config(path)
            self.assertIn("primary", deployed.artifact_roots)

    def test_unknown_missing_duplicate_and_unimplemented_values_fail(self):
        data = application_data()
        data["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "versioned schema"):
            self.load_data(data)
        data = application_data()
        del data["recovery"]
        with self.assertRaisesRegex(ValueError, "versioned schema"):
            self.load_data(data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.yaml"
            path.write_text("schema_version: 2\nschema_version: 2\n")
            with self.assertRaisesRegex(ValueError, "invalid YAML"):
                load_application_config(path)
        for mutate, message in (
            (
                lambda d: d["backend"].update(options={"beam_size": 1}),
                "not implemented",
            ),
            (lambda d: d["recovery"].update(policy="automatic"), "manual recovery"),
            (
                lambda d: d["device_policy"].update(mode="cuda", preference=["cpu"]),
                "explicit device",
            ),
            (lambda d: d["admission"].update(max_active=2), "exactly one"),
            (
                lambda d: d["admission"].update(
                    max_ipc_message_bytes=65536,
                    max_request_bytes=50000,
                    max_retained_audio_bytes=50000,
                    max_upload_bytes=50000,
                ),
                "too small",
            ),
            (lambda d: d["models"][0].update(immutable_revision="main"), "immutable"),
            (
                lambda d: d["models"][0].update(translation_supported="false"),
                "translation_supported",
            ),
        ):
            invalid = application_data()
            mutate(invalid)
            with self.assertRaisesRegex(ValueError, message):
                self.load_data(invalid)

    def test_legacy_m01_health_configuration_remains_valid(self):
        from services.worker.server import load_config

        config = load_config(Path("configs/stt.yaml"), "stt")
        self.assertEqual(config["kind"], "stt")

    def test_cpu_deployment_example_places_manifest_outside_artifact_root(self):
        deployment = load_deployment_config("configs/stt-deployment-cpu.example.yaml")
        artifact = deployment.artifact_roots["smoke-small"]
        self.assertNotIn(artifact.manifest, artifact.directory.parents)
        self.assertNotEqual(artifact.manifest, artifact.directory)

    def test_faster_whisper_v3_configuration_and_cuda_deployment_policy(self):
        config = self.load_data(faster_whisper_data())
        self.assertEqual(config.backend_id, "faster-whisper")
        self.assertEqual(dict(config.backend_options)["compute_type_cuda"], "float16")
        self.assertEqual(config.audio_limits.sample_rate_hz, 16000)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deployment.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 2,
                        "artifacts": {
                            "primary": {
                                "directory": "/models/tiny",
                                "manifest": "/models/tiny/manifest.yaml",
                            }
                        },
                        "device_access": {
                            "cuda_device_index": 0,
                            "minimum_free_gpu_bytes_before_load": 1024,
                        },
                    }
                )
            )
            deployment = load_deployment_config(path)
            self.assertEqual(deployment.cuda_device_index, 0)
            self.assertEqual(deployment.minimum_free_gpu_bytes_before_load, 1024)

    def test_faster_whisper_configuration_rejects_unknown_precision_and_limits(self):
        for mutate in (
            lambda d: d["backend"]["options"].update(extra=True),
            lambda d: d["backend"]["options"].update(compute_type_cuda="auto"),
            lambda d: d["backend"]["options"].update(compute_type_cpu="float16"),
            lambda d: d["audio_limits"].update(max_decoded_audio_bytes=0),
            lambda d: d["device_policy"].update(mode="cuda", preference=["cpu"]),
        ):
            invalid = faster_whisper_data()
            mutate(invalid)
            with self.assertRaises(ValueError):
                self.load_data(invalid)

    def test_unregistered_backend_fails_closed_at_composition(self):
        with self.assertRaises(SpeechFailure) as caught:
            resolve_backend("faster-whisper", {})
        self.assertIn("backend is not available", caught.exception.diagnostic)


class ArtifactValidation(unittest.TestCase):
    def test_valid_manifest_identity_files_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "artifact"
            root.mkdir()
            contents = b"fake weights"
            (root / "model.bin").write_bytes(contents)
            manifest = {
                "manifest_version": 1,
                "model": {
                    "family": "whisper",
                    "repository": "local-fixture",
                    "revision": "b" * 40,
                },
                "artifact": {
                    "format": "fake-v1",
                    "tool": "fixture",
                    "tool_version": "1",
                },
                "files": [
                    {
                        "path": "model.bin",
                        "size_bytes": len(contents),
                        "sha256": hashlib.sha256(contents).hexdigest(),
                    }
                ],
            }
            manifest_path = base / "manifest.yaml"
            manifest_path.write_text(yaml.safe_dump(manifest))
            model = ModelConfig(
                "general",
                ModelIdentity("whisper", "b" * 40),
                "primary",
                canonical_manifest_digest(manifest),
                "fake-v1",
            )
            verified = verify_artifact(model, ArtifactRoot(root, manifest_path))
            self.assertEqual(verified.identity.manifest_sha256, model.manifest_sha256)

    def test_mismatch_path_escape_symlink_and_unlisted_file_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "artifact"
            root.mkdir()
            (root / "file.bin").write_bytes(b"x")
            manifest = {
                "manifest_version": 1,
                "model": {
                    "family": "whisper",
                    "repository": "fixture",
                    "revision": "c" * 40,
                },
                "artifact": {
                    "format": "fake-v1",
                    "tool": "fixture",
                    "tool_version": "1",
                },
                "files": [
                    {
                        "path": "file.bin",
                        "size_bytes": 1,
                        "sha256": hashlib.sha256(b"x").hexdigest(),
                    }
                ],
            }
            manifest_path = base / "manifest.yaml"
            manifest_path.write_text(yaml.safe_dump(manifest))
            model = ModelConfig(
                "general",
                ModelIdentity("whisper", "c" * 40),
                "primary",
                canonical_manifest_digest(manifest),
                "fake-v1",
            )
            (root / "extra.bin").write_bytes(b"extra")
            with self.assertRaises(SpeechFailure):
                verify_artifact(model, ArtifactRoot(root, manifest_path))
            (root / "extra.bin").unlink()
            manifest["files"][0]["sha256"] = "0" * 64
            manifest_path.write_text(yaml.safe_dump(manifest))
            model = ModelConfig(
                "general",
                ModelIdentity("whisper", "c" * 40),
                "primary",
                canonical_manifest_digest(manifest),
                "fake-v1",
            )
            with self.assertRaises(SpeechFailure):
                verify_artifact(model, ArtifactRoot(root, manifest_path))
            manifest["files"][0]["sha256"] = hashlib.sha256(b"x").hexdigest()
            manifest_path.write_text(yaml.safe_dump(manifest))
            manifest["files"][0]["size_bytes"] = 9
            manifest_path.write_text(yaml.safe_dump(manifest))
            model = ModelConfig(
                "general",
                ModelIdentity("whisper", "c" * 40),
                "primary",
                canonical_manifest_digest(manifest),
                "fake-v1",
            )
            with self.assertRaises(SpeechFailure):
                verify_artifact(model, ArtifactRoot(root, manifest_path))
            manifest["files"][0]["size_bytes"] = 1
            manifest_path.write_text(yaml.safe_dump(manifest))
            model = ModelConfig(
                "general",
                ModelIdentity("whisper", "c" * 40),
                "primary",
                canonical_manifest_digest(manifest),
                "fake-v1",
            )
            (root / "link.bin").symlink_to(root / "file.bin")
            with self.assertRaises(SpeechFailure):
                verify_artifact(model, ArtifactRoot(root, manifest_path))
            (root / "link.bin").unlink()
            manifest["files"][0]["path"] = "../escape"
            manifest_path.write_text(yaml.safe_dump(manifest))
            model = ModelConfig(
                "general",
                ModelIdentity("whisper", "c" * 40),
                "primary",
                canonical_manifest_digest(manifest),
                "fake-v1",
            )
            with self.assertRaises(SpeechFailure):
                verify_artifact(model, ArtifactRoot(root, manifest_path))


if __name__ == "__main__":
    unittest.main()
