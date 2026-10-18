"""Tests for strict release descriptor and model-manifest compatibility checks."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.release_manifest import (
    ReleaseManifestError,
    load_release,
    validate_release,
)


def artifact_manifest(repository="acme/model", revision="a" * 40):
    payload = b"tiny fixture"
    return {
        "manifest_version": 1,
        "model": {"family": "fixture", "repository": repository, "revision": revision},
        "artifact": {
            "format": "fixture-v1",
            "tool": "test",
            "tool_version": "1",
        },
        "files": [
            {
                "path": "weights.bin",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }


def canonical_sha256(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class ReleaseManifestValidation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        compose = self.root / "deployments/compose/compose.yaml"
        compose.parent.mkdir(parents=True)
        compose.write_text("services:\n  gateway: {}\n  stt: {}\n  tts: {}\n")
        artifact = artifact_manifest()
        artifact_path = self.root / "releases/artifacts/fixture.yaml"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False))
        self.release = {
            "schema_version": 1,
            "release_version": "v1.2.3",
            "git_source_revision": "b" * 40,
            "supported_platforms": ["linux/amd64"],
            "services": {
                "gateway": self.service(
                    "gateway", "foundation", "voiceservice-gateway"
                ),
                "stt": self.service("stt", "cuda", "voiceservice-stt-cuda"),
                "tts": self.service(
                    "tts", "health-only", "voiceservice-tts-health-only"
                ),
            },
        }
        self.release["services"]["stt"]["required_model_artifacts"] = [
            {
                "id": "fixture-model",
                "source": "huggingface_hub",
                "family": "fixture",
                "repository": "acme/model",
                "revision": "a" * 40,
                "artifact_format": "fixture-v1",
                "manifest_path": "releases/artifacts/fixture.yaml",
                "manifest_sha256": canonical_sha256(artifact),
            }
        ]

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def service(name, variant, package):
        return {
            "image": f"ghcr.io/azargarov/{package}@sha256:{'c' * 64}",
            "platform": "linux/amd64",
            "runtime_variant": variant,
            "capabilities": ["health"],
            "dependencies": [],
            "required_model_artifacts": [],
            "configuration_compatibility": {
                "source_revision_bound": True,
                "schema_versions": {},
            },
        }

    def test_valid_release_and_current_v012_descriptor(self):
        validate_release(self.release, self.root)
        release = load_release()
        self.assertEqual(release["release_version"], "v0.1.2")
        self.assertEqual(release["services"]["stt"]["runtime_variant"], "cuda")

    def test_cpu_stt_release_variant_is_supported(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["stt"]["runtime_variant"] = "cpu"
        candidate["services"]["stt"]["image"] = (
            f"ghcr.io/azargarov/voiceservice-stt-cpu@sha256:{'d' * 64}"
        )
        validate_release(candidate, self.root)

    def test_missing_or_mutable_oci_digest_is_rejected(self):
        for image in (
            "ghcr.io/azargarov/voiceservice-gateway",
            "ghcr.io/azargarov/voiceservice-gateway:v1.2.3",
            f"ghcr.io/azargarov/voiceservice-gateway@sha256:{'G' * 64}",
        ):
            candidate = copy.deepcopy(self.release)
            candidate["services"]["gateway"]["image"] = image
            with self.subTest(image=image), self.assertRaises(ReleaseManifestError):
                validate_release(candidate, self.root)

    def test_unknown_compose_service_and_runtime_variant_are_rejected(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["unknown"] = candidate["services"]["gateway"]
        with self.assertRaisesRegex(ReleaseManifestError, "unknown Compose service"):
            validate_release(candidate, self.root)

        candidate = copy.deepcopy(self.release)
        candidate["services"]["stt"]["runtime_variant"] = "npu"
        with self.assertRaisesRegex(ReleaseManifestError, "runtime variant"):
            validate_release(candidate, self.root)

    def test_model_revision_and_manifest_digest_must_match(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["stt"]["required_model_artifacts"][0]["revision"] = (
            "d" * 40
        )
        with self.assertRaisesRegex(ReleaseManifestError, "identity differs"):
            validate_release(candidate, self.root)

        candidate = copy.deepcopy(self.release)
        candidate["services"]["stt"]["required_model_artifacts"][0][
            "manifest_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(ReleaseManifestError, "manifest is invalid"):
            validate_release(candidate, self.root)

    def test_missing_artifact_manifest_and_unknown_fields_are_rejected(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["stt"]["required_model_artifacts"][0]["manifest_path"] = (
            "releases/artifacts/missing.yaml"
        )
        with self.assertRaises(ReleaseManifestError):
            validate_release(candidate, self.root)

        candidate = copy.deepcopy(self.release)
        candidate["unrecognized"] = True
        with self.assertRaisesRegex(ReleaseManifestError, "fields do not match"):
            validate_release(candidate, self.root)

    def test_dependency_must_be_in_release_and_acyclic(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["gateway"]["dependencies"] = ["not-present"]
        with self.assertRaisesRegex(ReleaseManifestError, "absent from this release"):
            validate_release(candidate, self.root)

        candidate["services"]["gateway"]["dependencies"] = ["stt"]
        candidate["services"]["stt"]["dependencies"] = ["gateway"]
        with self.assertRaisesRegex(ReleaseManifestError, "cycle"):
            validate_release(candidate, self.root)

    def test_tts_health_only_cannot_claim_inference(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["tts"]["capabilities"] = ["health", "tts-inference"]
        with self.assertRaisesRegex(ReleaseManifestError, "health-only"):
            validate_release(candidate, self.root)

    def test_configuration_compatibility_uses_current_schema_support(self):
        candidate = copy.deepcopy(self.release)
        candidate["services"]["stt"]["configuration_compatibility"]["schema_versions"][
            "application"
        ] = [99]
        with self.assertRaisesRegex(ReleaseManifestError, "unsupported version"):
            validate_release(candidate, self.root)


if __name__ == "__main__":
    unittest.main()
