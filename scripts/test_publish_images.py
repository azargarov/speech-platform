"""Input validation and safety checks for GHCR publication."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publish_images import (
    PublishError,
    docker_auth_is_configured,
    current_revision,
    dependency_lock_digest,
    image_identity,
    validate_services,
    validate_variant,
    validate_version,
)


class PublishImageValidation(unittest.TestCase):
    def test_accepts_release_semver_tags(self):
        for version in ("v0.1.0", "v1.2.3-rc.1"):
            with self.subTest(version=version):
                validate_version(version)

    def test_rejects_missing_or_invalid_versions(self):
        for version in (
            "",
            "0.1.0",
            "v1",
            "v01.2.3",
            "latest",
            "v1.2.3-.",
            "v1.2.3+build.9",
        ):
            with self.subTest(version=version), self.assertRaises(PublishError):
                validate_version(version)

    def test_service_selection_is_bounded_and_deduplicated(self):
        self.assertEqual(validate_services("gateway stt gateway"), ["gateway", "stt"])
        with self.assertRaisesRegex(PublishError, "unknown service"):
            validate_services("gateway unknown")

    def test_variants_are_explicit_and_bounded(self):
        self.assertEqual(validate_variant("cpu"), "cpu")
        self.assertEqual(validate_variant("cuda"), "cuda")
        with self.assertRaisesRegex(PublishError, "VARIANT"):
            validate_variant("gpu")

    def test_stt_variant_maps_to_distinct_repositories_and_labels(self):
        self.assertEqual(
            image_identity("stt", "cpu"),
            ("voiceservice-stt-cpu", "stt-worker", "cpu", "cpu-lock-sha256"),
        )
        self.assertEqual(
            image_identity("stt", "cuda"),
            ("voiceservice-stt-cuda", "stt-worker", "cuda", "cuda-lock-sha256"),
        )
        self.assertEqual(
            image_identity("tts", "cuda"),
            ("voiceservice-tts-health-only", "tts-health-only", "health-only", None),
        )

    def test_cuda_lock_digest_matches_the_locked_file(self):
        self.assertEqual(
            dependency_lock_digest("cuda"),
            "68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14",
        )

    def test_cuda_compose_build_selects_existing_locked_dockerfile(self):
        overlay = Path("deployments/compose/compose.stt-cuda-build.yaml").read_text()
        dockerfile = Path("deployments/compose/worker-stt-cuda.Dockerfile").read_text()
        self.assertIn("worker-stt-cuda.Dockerfile", overlay)
        self.assertIn("STT_CUDA_BASE_IMAGE:", overlay)
        self.assertIn("STT_SOURCE_REVISION:", overlay)
        self.assertIn("STT_CUDA_LOCK_SHA256:", overlay)
        self.assertIn("COPY services/requirements-stt-cuda.lock", dockerfile)
        self.assertIn("pip install --no-cache-dir --require-hashes", dockerfile)
        self.assertIn('runtime-variant="cuda"', dockerfile)

    def test_build_default_and_release_workflow_variant_are_explicit(self):
        makefile = Path("Makefile").read_text()
        verify = Path(".github/workflows/verify.yaml").read_text()
        release = Path(".github/workflows/release.yaml").read_text()
        self.assertIn("$(strip $(VARIANT)),cpu", makefile)
        self.assertIn("$(strip $(VARIANT)),cuda", makefile)
        self.assertIn("make image VARIANT=cuda", verify)
        self.assertIn("make image VARIANT=cuda", release)
        self.assertIn('make publish VERSION="$GITHUB_REF_NAME" VARIANT=cuda', release)

    def test_dirty_worktree_is_rejected_before_revision_resolution(self):
        with patch("publish_images.command", return_value=" M Makefile") as run_command:
            with self.assertRaisesRegex(PublishError, "clean Git working tree"):
                current_revision()
        run_command.assert_called_once_with(
            ["git", "status", "--porcelain"], capture=True
        )

    def test_auth_configuration_must_include_ghcr_or_credential_store(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            with patch.dict(os.environ, {"DOCKER_CONFIG": directory}):
                config.write_text('{"auths":{"https://index.docker.io/v1/":{}}}')
                self.assertFalse(docker_auth_is_configured())
                config.write_text('{"credHelpers":{"ghcr.io":"secretservice"}}')
                self.assertTrue(docker_auth_is_configured())


if __name__ == "__main__":
    unittest.main()
