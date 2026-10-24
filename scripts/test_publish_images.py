"""Input validation and safety checks for GHCR publication."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_images
from publish_images import (
    PublishError,
    docker_auth_is_configured,
    current_revision,
    dependency_lock_digest,
    image_identity,
    validate_services,
    validate_variant,
    validate_version,
    compose_image_reference,
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
            ("voiceservice-tts-cuda", "tts-worker", "cuda", "tts-lock-sha256"),
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
        self.assertIn(
            "make image SERVICE=${{ matrix.service }} VARIANT=${{ matrix.variant }}",
            verify,
        )
        self.assertIn("service: [gateway, stt, tts]", release)
        self.assertIn(
            'make publish SERVICE=${{ matrix.service }} VERSION="$GITHUB_REF_NAME" VARIANT=cuda',
            release,
        )

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


class PublishImagePipelineRegression(unittest.TestCase):
    revision = "a" * 40
    digest = "sha256:" + "b" * 64
    local_refs = {
        "gateway": "speech-platform-gateway:local",
        "stt": "speech-platform-stt-cuda:local",
        "tts": "speech-platform-tts:local",
    }
    identities = {
        "gateway": ("gateway", "foundation"),
        "stt": ("stt-worker", "cuda"),
        "tts": ("tts-worker", "cuda"),
    }

    def details(self, service, *, wrong_label=None):
        role, variant = self.identities[service]
        labels = {
            publish_images.LABEL_REVISION: self.revision,
            publish_images.LABEL_ROLE: role,
            publish_images.LABEL_SERVICE: service,
            publish_images.LABEL_VARIANT: variant,
        }
        if service == "stt":
            labels["com.speech-platform.cuda-lock-sha256"] = (
                publish_images.dependency_lock_digest("cuda")
            )
        if service == "tts":
            labels["com.speech-platform.tts-lock-sha256"] = (
                publish_images.dependency_lock_digest("tts")
            )
        if wrong_label and service == "stt":
            labels[wrong_label] = "incorrect"
        return json.dumps(
            [{"Os": "linux", "Architecture": "amd64", "Config": {"Labels": labels}}]
        )

    def run_publish(self, *, missing_image=None, wrong_label=None):
        calls = []

        def fake_command(args, *, capture=False, env=None):
            calls.append(args)
            if args[:2] == ["git", "rev-parse"]:
                return self.revision
            if args[:2] == ["docker", "compose"]:
                # Simulate a fresh Docker daemon: Compose config is available,
                # but no containers have been created.
                return json.dumps(
                    {
                        "services": {
                            service: {"image": image_ref}
                            for service, image_ref in self.local_refs.items()
                        }
                    }
                )
            if args[:3] == ["docker", "image", "inspect"]:
                reference = args[3]
                if reference == missing_image:
                    raise publish_images.PublishError(
                        f"image does not exist: {reference}"
                    )
                service = (
                    next(
                        name
                        for name, image_ref in self.local_refs.items()
                        if reference == image_ref
                    )
                    if reference in self.local_refs.values()
                    else next(
                        name
                        for name, (package, _role, _variant, _lock) in {
                            "gateway": publish_images.image_identity("gateway", "cuda"),
                            "stt": publish_images.image_identity("stt", "cuda"),
                            "tts": publish_images.image_identity("tts", "cuda"),
                        }.items()
                        if reference.startswith(f"{publish_images.REGISTRY}/{package}@")
                    )
                )
                return self.details(service, wrong_label=wrong_label)
            if args[:3] == ["docker", "buildx", "imagetools"]:
                return f"Name: fake\nDigest: {self.digest}\n"
            return ""

        return calls, fake_command

    def publish_with_mock(self, *, missing_image=None, wrong_label=None):
        calls, fake_command = self.run_publish(
            missing_image=missing_image, wrong_label=wrong_label
        )
        with (
            patch.object(
                publish_images, "docker_auth_is_configured", return_value=True
            ),
            patch.object(
                publish_images, "current_revision", return_value=self.revision
            ),
            patch.object(publish_images, "workflow_identity", return_value="test:run"),
            patch.object(publish_images, "command", side_effect=fake_command),
            tempfile.TemporaryDirectory() as directory,
        ):
            publish_images.publish(
                "v0.1.2", ["gateway", "stt", "tts"], "cuda", Path(directory)
            )
        return calls

    def test_fresh_compose_state_resolves_and_prepares_all_registry_tags(self):
        calls = self.publish_with_mock()
        inspected_locally = [
            call[3]
            for call in calls
            if call[:3] == ["docker", "image", "inspect"]
            and call[3] in self.local_refs.values()
        ]
        tags = [call for call in calls if call[:3] == ["docker", "image", "tag"]]
        pushes = [call for call in calls if call[:2] == ["docker", "push"]]
        self.assertEqual(set(inspected_locally), set(self.local_refs.values()))
        self.assertEqual(
            {call[-1] for call in tags},
            {
                "ghcr.io/azargarov/voiceservice-gateway:v0.1.2",
                "ghcr.io/azargarov/voiceservice-stt-cuda:v0.1.2",
                "ghcr.io/azargarov/voiceservice-tts-cuda:v0.1.2",
            },
        )
        self.assertEqual(len(pushes), 3)
        first_tag = min(
            i for i, call in enumerate(calls) if call[:3] == ["docker", "image", "tag"]
        )
        self.assertTrue(
            all(
                i < first_tag
                for i, call in enumerate(calls)
                if call[:3] == ["docker", "image", "inspect"]
                and call[3] in self.local_refs.values()
            )
        )
        self.assertFalse(any("images" in call and "-q" in call for call in calls))
        # The mocked Docker environment contains no Compose containers; only
        # rendered Compose configuration and docker image inspect are consulted.
        self.assertFalse(any("ps" in call or "up" in call for call in calls))

    def test_missing_expected_image_stops_before_any_registry_tag_or_push(self):
        calls, fake_command = self.run_publish(missing_image=self.local_refs["stt"])
        with (
            patch.object(
                publish_images, "docker_auth_is_configured", return_value=True
            ),
            patch.object(
                publish_images, "current_revision", return_value=self.revision
            ),
            patch.object(publish_images, "workflow_identity", return_value="test:run"),
            patch.object(publish_images, "command", side_effect=fake_command),
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(PublishError, "image does not exist"),
        ):
            publish_images.publish(
                "v0.1.2", ["gateway", "stt", "tts"], "cuda", Path(directory)
            )
        self.assertFalse(any(call[:3] == ["docker", "image", "tag"] for call in calls))
        self.assertFalse(any(call[:2] == ["docker", "push"] for call in calls))

    def test_wrong_service_or_runtime_variant_stops_before_any_registry_write(self):
        for label in (publish_images.LABEL_SERVICE, publish_images.LABEL_VARIANT):
            with self.subTest(label=label):
                calls, fake_command = self.run_publish(wrong_label=label)
                with (
                    patch.object(
                        publish_images, "docker_auth_is_configured", return_value=True
                    ),
                    patch.object(
                        publish_images, "current_revision", return_value=self.revision
                    ),
                    patch.object(
                        publish_images, "workflow_identity", return_value="test:run"
                    ),
                    patch.object(publish_images, "command", side_effect=fake_command),
                    tempfile.TemporaryDirectory() as directory,
                    self.assertRaises(PublishError),
                ):
                    publish_images.publish(
                        "v0.1.2", ["gateway", "stt", "tts"], "cuda", Path(directory)
                    )
                self.assertFalse(
                    any(call[:3] == ["docker", "image", "tag"] for call in calls)
                )
                self.assertFalse(any(call[:2] == ["docker", "push"] for call in calls))

    def test_compose_image_reference_is_resolved_from_rendered_compose(self):
        output = json.dumps({"services": {"stt": {"image": self.local_refs["stt"]}}})
        with patch("publish_images.command", return_value=output) as run_command:
            self.assertEqual(
                compose_image_reference("stt", "cuda", self.revision),
                self.local_refs["stt"],
            )
        args = run_command.call_args.args[0]
        self.assertEqual(args[-3:], ["config", "--format", "json"])
        self.assertNotIn("images", args)


if __name__ == "__main__":
    unittest.main()


class ReleaseTagProvenanceTests(unittest.TestCase):
    def test_mismatched_release_tag_blocks_before_build_or_registry_write(self):
        with (
            patch.object(
                publish_images, "docker_auth_is_configured", return_value=True
            ),
            patch.object(publish_images, "current_revision", return_value="a" * 40),
            patch.object(publish_images, "command", return_value="b" * 40) as command,
            tempfile.TemporaryDirectory() as temp,
        ):
            with self.assertRaisesRegex(PublishError, "release tag"):
                publish_images.publish("v0.2.0", ["tts"], "cuda", Path(temp))
        self.assertEqual(len(command.call_args_list), 1)
        self.assertEqual(command.call_args.args[0][0], "git")
