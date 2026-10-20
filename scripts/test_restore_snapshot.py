"""Temporary-fixture tests for atomic restoration snapshot capture."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.restore_snapshot import (
    CAPTURE_SOURCE_FILES,
    DIGEST_ENV_KEYS,
    IMAGE_ENV_KEYS,
    IMAGE_ID_KEYS,
    INTEGER_ENV_KEYS,
    MEMORY_ENV_KEYS,
    NUMBER_ENV_KEYS,
    OPTIONAL_ARTIFACT_EVIDENCE_FILES,
    PATH_ENV_KEYS,
    PERSISTED_ENV_KEYS,
    PROJECT_ENV_KEYS,
    PROJECT_FILES,
    RENDER_ENV_KEYS,
    REVISION_ENV_KEYS,
    SERVICES,
    TRACKED_SOURCE_FILES,
    SnapshotCaptureError,
    capture_snapshot,
    host_bindings_sha256,
    verify_retained_snapshot,
)
from scripts.project_lock import ProjectLock


class SnapshotCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.private = self.base / "private"
        self.deployment = self.private / "deployment" / "fixture"
        self.root = self.deployment / "restoration"
        self.source_root = self.deployment / "inputs"
        self.lock_root = self.base / "locks"
        for directory in (
            self.private,
            self.private / "deployment",
            self.deployment,
            self.root,
            self.source_root,
            self.lock_root,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
        self.paths = {role: self.source_root / role for role in CAPTURE_SOURCE_FILES}
        for role, path in self.paths.items():
            content = self._source_content(role)
            path.write_bytes(content)
            path.chmod(0o600)
        self.rendered = self._rendered_compose()
        self.bindings_digest = host_bindings_sha256(self.rendered)
        self.hashes = {
            service: hashlib.sha256(service.encode()).hexdigest()
            for service in SERVICES
        }
        self.configuration = {
            service: hashlib.sha256((service + "config").encode()).hexdigest()
            for service in SERVICES
        }
        self.runtime_identity = {
            service: hashlib.sha256((service + "runtime").encode()).hexdigest()
            for service in SERVICES
        }
        self.artifacts = {
            service: [
                "oci://registry.invalid/"
                + service
                + "@sha256:"
                + ("a" if service == "gateway" else "b" if service == "stt" else "c")
                * 64
            ]
            for service in SERVICES
        }
        self.artifacts["stt"].append(
            "model://fixture/large-v3-turbo@sha256:" + "d" * 64
        )
        self.verify_calls = []
        self.docker_calls = []
        self.runtime_override = None
        self.validation_override = None
        self.render_override = None
        self.verify_override = None
        self.optional_roles = []

    def tearDown(self):
        self.temp.cleanup()

    def _env_value(self, key):
        if key in PATH_ENV_KEYS:
            basename = {
                "GATEWAY_CONFIG": "gateway.yaml",
                "TTS_CONFIG": "tts.yaml",
                "STT_APPLICATION_CONFIG": "stt-application.yaml",
                "STT_DEPLOYMENT_CONFIG": "stt-deployment.yaml",
                "STT_WORKER_CONFIG": "stt.yaml",
            }.get(key)
            if basename:
                role = basename
                return str(self.paths[role].resolve())
            return "/models/" + "e" * 64
        if key in IMAGE_ENV_KEYS:
            return "registry.invalid/" + key.lower() + "@sha256:" + "f" * 64
        if key in IMAGE_ID_KEYS:
            return "sha256:" + "f" * 64
        if key in DIGEST_ENV_KEYS:
            return "1" * 64
        if key in REVISION_ENV_KEYS:
            return "2" * 40
        if key in INTEGER_ENV_KEYS or key in {"GATEWAY_PIDS", "TTS_PIDS"}:
            return "1234"
        if key in NUMBER_ENV_KEYS:
            return "2"
        if key in MEMORY_ENV_KEYS:
            return "128m"
        if key in PROJECT_ENV_KEYS:
            return "speech-platform-fixture"
        if key == "SPEECH_BIND_IP":
            return "127.0.0.1"
        if key == "STT_IMAGE_IDENTITY_MODE":
            return "registry_digest"
        if key == "STT_PLATFORM":
            return "linux/amd64"
        raise AssertionError(f"unclassified env key: {key}")

    def _source_content(self, role):
        if role == "compose.env":
            return "".join(
                f"{key}={json.dumps(self._env_value(key))}\n"
                for key in sorted(PERSISTED_ENV_KEYS)
            ).encode()
        return f"fixture configuration for {role}\n".encode()

    def _rendered_compose(self):
        binds = {
            "gateway": {"/config/gateway.yaml": str(self.paths["gateway.yaml"])},
            "tts": {"/config/tts.yaml": str(self.paths["tts.yaml"])},
            "stt": {
                "/config/stt-application.yaml": str(self.paths["stt-application.yaml"]),
                "/config/stt-deployment.yaml": str(self.paths["stt-deployment.yaml"]),
                "/config/stt.yaml": str(self.paths["stt.yaml"]),
                "/models": "/models/" + "e" * 64,
            },
        }
        return {
            "name": "speech-platform-fixture",
            "services": {
                service: {
                    "image": "registry.invalid/"
                    + service
                    + "@sha256:"
                    + (
                        "a"
                        if service == "gateway"
                        else "b"
                        if service == "stt"
                        else "c"
                    )
                    * 64,
                    "volumes": [
                        {
                            "type": "bind",
                            "source": source,
                            "target": target,
                            "read_only": True,
                        }
                        for target, source in binds[service].items()
                    ],
                }
                for service in SERVICES
            },
        }

    def _contract(self, files):
        if self.validation_override:
            return self.validation_override(files)
        if set(files) != CAPTURE_SOURCE_FILES | set(self.optional_roles):
            raise ValueError("input dependency incomplete")
        return {
            "project_name": "speech-platform-fixture",
            "selected_services": list(SERVICES),
            "required_optional_file_roles": self.optional_roles,
            "configuration_sha256_by_service": self.configuration,
            "runtime_identity_sha256_by_service": self.runtime_identity,
            "image_id_by_service": {
                service: "sha256:"
                + ("a" if service == "gateway" else "b" if service == "stt" else "c")
                * 64
                for service in SERVICES
            },
            "platform_by_service": {service: "linux/amd64" for service in SERVICES},
            "artifacts_by_service": self.artifacts,
            "secret_versions_by_service": {service: [] for service in SERVICES},
            "host_bindings_sha256": self.bindings_digest,
        }

    def _render_default(self, files):
        return {
            "render_environment": {
                key: self._env_value(key) for key in sorted(RENDER_ENV_KEYS)
            },
            "rendered_compose": self.rendered,
            "compose_service_hashes": self.hashes,
        }

    def _render(self, files):
        if self.render_override:
            return self.render_override(files)
        return self._render_default(files)

    def _runtime_default(self):
        self.docker_calls.append("fake-observation")
        now = time.time()
        return {
            "project_name": "speech-platform-fixture",
            "docker_engine_version": "29.1.3",
            "compose_version": "v5.6.0",
            "observed_at_epoch": now,
            "services": {
                service: {
                    "container_id": "container-" + service,
                    "compose_project_name": "speech-platform-fixture",
                    "compose_service_name": service,
                    "image_id": "sha256:"
                    + (
                        "a"
                        if service == "gateway"
                        else "b"
                        if service == "stt"
                        else "c"
                    )
                    * 64,
                    "image_reference": self.artifacts[service][0][len("oci://") :],
                    "platform": "linux/amd64",
                    "compose_config_hash": self.hashes[service],
                    "configuration_sha256": self.configuration[service],
                    "runtime_identity_sha256": self.runtime_identity[service],
                    "compatible": True,
                    "state": "running",
                    "health": "healthy",
                    "readiness": {"status": "READY", "observed_at_epoch": now},
                }
                for service in SERVICES
            },
        }

    def _runtime(self):
        if self.runtime_override:
            return self.runtime_override()
        return self._runtime_default()

    def _verify_artifacts(self, artifacts):
        if self.verify_override:
            return self.verify_override(artifacts)
        self.verify_calls.append(artifacts)
        if artifacts != self.artifacts:
            raise ValueError("artifact mismatch")

    def _capture(self, **kwargs):
        with (
            patch("scripts.restore_snapshot._filesystem_type", return_value="ext4"),
            patch("scripts.project_lock._filesystem_type", return_value="ext4"),
        ):
            return capture_snapshot(
                self.root,
                "speech-platform-fixture",
                self.paths,
                allowed_source_roots=[self.source_root],
                validate_configuration=self._contract,
                render_captured=self._render,
                collect_runtime=self._runtime,
                verify_artifacts=self._verify_artifacts,
                lock_root=self.lock_root,
                filesystem_type=lambda _path: "ext4",
                tracked_source_revision="a" * 40,
                tracked_source_validator=lambda _paths, _content: {
                    role: "b" * 40 for role in TRACKED_SOURCE_FILES
                },
                **kwargs,
            )

    def _verify_published(self, result):
        return verify_retained_snapshot(
            self.root,
            "stt",
            result["snapshot_sha256"],
            project_name="speech-platform-fixture",
            expected_artifacts_by_service={
                service: set(references)
                for service, references in self.artifacts.items()
            },
        )

    def test_valid_complete_snapshot_interoperates_with_verifier(self):
        result = self._capture()
        manifest = self._verify_published(result)
        self.assertEqual(set(manifest["files"]), PROJECT_FILES)
        self.assertEqual(manifest["source_revision"], "a" * 40)
        self.assertEqual(
            manifest["source_git_blob_ids"],
            {role: "b" * 40 for role in TRACKED_SOURCE_FILES},
        )
        self.assertEqual(
            result["snapshot_reference"],
            "private://snapshots/sha256/" + result["snapshot_sha256"],
        )
        self.assertTrue(result["staging_retained"])
        self.assertEqual(len(self.verify_calls), 1)

    def test_declared_local_image_evidence_is_part_of_complete_snapshot(self):
        role = "image-build-evidence.json"
        self.assertIn(role, OPTIONAL_ARTIFACT_EVIDENCE_FILES)
        self.optional_roles = [role]
        self.paths[role] = self.source_root / role
        self.paths[role].write_text('{"evidence":"fixture"}')
        self.paths[role].chmod(0o600)
        result = self._capture()
        manifest = self._verify_published(result)
        self.assertEqual(manifest["optional_file_roles"], [role])
        self.assertIn(role, manifest["files"])

    def test_source_outside_approved_roots_is_never_read(self):
        outside = self.base / "outside.yaml"
        outside.write_text("sentinel")
        outside.chmod(0o600)
        self.paths["gateway.yaml"] = outside
        with self.assertRaisesRegex(SnapshotCaptureError, "outside approved"):
            self._capture()

    def test_symlinked_configuration_source_is_rejected(self):
        source = self.paths["gateway.yaml"]
        target = self.source_root / "gateway-retained.yaml"
        target.write_bytes(source.read_bytes())
        target.chmod(0o600)
        source.unlink()
        source.symlink_to(target)
        with self.assertRaisesRegex(SnapshotCaptureError, "unavailable or unsafe"):
            self._capture()

    def test_hard_linked_configuration_source_is_rejected(self):
        source = self.paths["gateway.yaml"]
        link = self.source_root / "gateway-link.yaml"
        link.hardlink_to(source)
        with self.assertRaisesRegex(SnapshotCaptureError, "link count"):
            self._capture()

    def test_rendered_compose_identity_must_match_runtime(self):
        def mismatch(files):
            result = self._render_default(files)
            result["compose_service_hashes"]["stt"] = "f" * 64
            return result

        self.render_override = mismatch
        with self.assertRaisesRegex(
            SnapshotCaptureError, "does not match fresh runtime"
        ):
            self._capture()

    def test_missing_configuration_input_blocks_before_lock_and_writes(self):
        del self.paths["gateway.yaml"]
        with self.assertRaisesRegex(SnapshotCaptureError, "input set is incomplete"):
            self._capture()
        self.assertFalse((self.root / "staging").exists())

    def test_unexpected_environment_key_is_rejected(self):
        path = self.paths["compose.env"]
        path.write_bytes(path.read_bytes() + b'UNAPPROVED="value"\n')
        with self.assertRaisesRegex(SnapshotCaptureError, "allowlist"):
            self._capture()

    def test_secret_like_content_is_rejected(self):
        self.paths["gateway.yaml"].write_text("api_token: raw-value\n")
        with self.assertRaisesRegex(
            SnapshotCaptureError, "forbidden sensitive content"
        ):
            self._capture()

    def test_incomplete_transitive_dependency_blocks(self):
        self.validation_override = lambda _files: (_ for _ in ()).throw(
            ValueError("configuration references an uncaptured dependency")
        )
        with self.assertRaisesRegex(SnapshotCaptureError, "strict validation"):
            self._capture()

    def test_source_mutation_during_capture_aborts_without_manifest(self):
        def render(files):
            self.paths["gateway.yaml"].write_text("changed during capture\n")
            return self._render_default(files)

        self.render_override = render
        with self.assertRaisesRegex(SnapshotCaptureError, "changed during snapshot"):
            self._capture()
        self.assertFalse(
            list((self.root / "snapshots" / "sha256").glob("*/manifest.json"))
        )

    def test_failure_before_blob_publication_never_activates_manifest(self):
        def fail(stage, _role):
            if stage == "before_blob":
                raise RuntimeError("injected failure")

        with self.assertRaises(SnapshotCaptureError):
            self._capture(before_publish=fail)
        self.assertFalse(
            list((self.root / "snapshots" / "sha256").glob("*/manifest.json"))
        )

    def test_failure_after_blob_publication_never_activates_manifest(self):
        published = []

        def fail(stage, role):
            if stage == "blob_published":
                published.append(role)
                raise RuntimeError("injected failure")

        with self.assertRaises(SnapshotCaptureError):
            self._capture(before_publish=fail)
        self.assertEqual(len(published), 1)
        self.assertTrue(list((self.root / "objects" / "sha256").iterdir()))
        self.assertFalse(
            list((self.root / "snapshots" / "sha256").glob("*/manifest.json"))
        )

    def test_failure_before_manifest_activation_leaves_only_ineligible_data(self):
        def fail(stage, _role):
            if stage == "before_manifest":
                raise RuntimeError("injected failure")

        with self.assertRaises(SnapshotCaptureError):
            self._capture(before_publish=fail)
        self.assertTrue(list((self.root / "objects" / "sha256").iterdir()))
        snapshot_dirs = list((self.root / "snapshots" / "sha256").iterdir())
        self.assertEqual(len(snapshot_dirs), 1)
        self.assertEqual(list(snapshot_dirs[0].iterdir()), [])

    def test_duplicate_immutable_snapshot_is_idempotent(self):
        first = self._capture()
        second = self._capture()
        self.assertEqual(first["snapshot_sha256"], second["snapshot_sha256"])
        self._verify_published(second)

    def test_corrupt_blob_blocks_duplicate_capture_and_verification(self):
        result = self._capture()
        manifest = self._verify_published(result)
        blob_digest = next(iter(manifest["files"].values()))["sha256"]
        blob = self.root / "objects" / "sha256" / blob_digest
        blob.write_bytes(b"corrupt")
        with self.assertRaises((SnapshotCaptureError, ValueError)):
            self._verify_published(result)
        with self.assertRaises(SnapshotCaptureError):
            self._capture()

    def test_missing_blob_is_rejected_by_verifier(self):
        result = self._capture()
        manifest = self._verify_published(result)
        blob_digest = next(iter(manifest["files"].values()))["sha256"]
        (self.root / "objects" / "sha256" / blob_digest).unlink()
        with self.assertRaises(ValueError):
            self._verify_published(result)

    def test_concurrent_capture_contention_is_refused(self):
        lock = ProjectLock("speech-platform-fixture", self.lock_root)
        with (
            patch("scripts.project_lock._filesystem_type", return_value="ext4"),
            lock,
        ):
            with self.assertRaisesRegex(
                SnapshotCaptureError, "lock could not be acquired"
            ):
                self._capture()

    def test_invalid_runtime_freshness_is_refused(self):
        def stale():
            value = self._runtime_default()
            value["observed_at_epoch"] = time.time() - 600
            return value

        self.runtime_override = stale
        with self.assertRaisesRegex(SnapshotCaptureError, "stale"):
            self._capture()

    def test_unresolved_uncertainty_marker_blocks_capture(self):
        marker = self.lock_root / "speech-platform-fixture.uncertain"
        marker.write_text("unresolved\n")
        marker.chmod(0o600)
        with self.assertRaisesRegex(SnapshotCaptureError, "lock could not be acquired"):
            self._capture()

    def test_unavailable_model_or_image_artifact_blocks_before_publication(self):
        def unavailable(_artifacts):
            raise ValueError("artifact verification unavailable")

        self.verify_override = unavailable
        with self.assertRaisesRegex(
            SnapshotCaptureError, "artifacts failed verification"
        ):
            self._capture()
        self.assertFalse(
            list((self.root / "snapshots" / "sha256").glob("*/manifest.json"))
        )

    def test_runtime_change_during_capture_aborts(self):
        calls = 0

        def changes():
            nonlocal calls
            calls += 1
            value = self._runtime_default()
            if calls == 2:
                value["services"]["stt"]["container_id"] = "replaced-container"
            return value

        self.runtime_override = changes
        with self.assertRaisesRegex(SnapshotCaptureError, "changed during"):
            self._capture()
        self.assertFalse(
            list((self.root / "snapshots" / "sha256").glob("*/manifest.json"))
        )

    def test_no_docker_or_model_store_mutation_is_possible_through_writer(self):
        model_sentinel = self.base / "model-store-sentinel"
        model_sentinel.write_text("unchanged")
        result = self._capture()
        self.assertTrue(result["snapshot_sha256"])
        self.assertEqual(model_sentinel.read_text(), "unchanged")
        self.assertEqual(self.docker_calls, ["fake-observation", "fake-observation"])

    def test_retained_snapshot_verifies_after_source_files_are_unavailable(self):
        result = self._capture()
        for path in self.paths.values():
            path.unlink()
        manifest = self._verify_published(result)
        self.assertEqual(set(manifest["files"]), PROJECT_FILES)


if __name__ == "__main__":
    unittest.main()
