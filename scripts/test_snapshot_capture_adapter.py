"""Offline tests for production snapshot selection and writer handoff."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import snapshot_capture_adapter as adapter
from scripts.restore_snapshot import CAPTURE_SOURCE_FILES
from scripts.restore_snapshot import SnapshotCaptureError
from scripts.snapshot_capture_adapter import (
    PROJECT,
    SOURCE_PATHS,
    capture_project_snapshot,
)


class SnapshotCaptureAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.paths = {name: self.base / name for name in SOURCE_PATHS}
        self.callbacks = {
            "validate_configuration": lambda _files: {},
            "render_captured": lambda _files: {},
            "collect_runtime": lambda: {},
            "verify_artifacts": lambda _artifacts: None,
        }
        self.writer_calls = []

    def tearDown(self):
        self.temp.cleanup()

    def _preflight(self, paths, *, project_name, approved_source_revision):
        self.assertTrue(approved_source_revision)
        return {
            "project_name": project_name,
            "selected_services": ["gateway", "stt", "tts"],
        }

    def _writer(self, *args, **kwargs):
        self.writer_calls.append((args, kwargs))
        return {"snapshot_sha256": "a" * 64}

    def test_complete_service_selection_is_forwarded_to_snapshot_writer(self):
        result = capture_project_snapshot(
            **self.callbacks,
            source_paths=self.paths,
            root=self.base / "restoration",
            lock_root=self.base / "locks",
            run_preflight=self._preflight,
            writer=self._writer,
        )
        self.assertEqual(result["snapshot_sha256"], "a" * 64)
        args, kwargs = self.writer_calls[0]
        self.assertEqual(args[1], PROJECT)
        self.assertEqual(set(args[2]), set(SOURCE_PATHS))
        self.assertEqual(
            kwargs["validate_configuration"], self.callbacks["validate_configuration"]
        )
        self.assertEqual(kwargs["collect_runtime"], self.callbacks["collect_runtime"])

    def test_missing_compose_input_blocks_before_lock_or_writer(self):
        paths = dict(self.paths)
        del paths["compose.yaml"]
        with self.assertRaisesRegex(SnapshotCaptureError, "source set is incomplete"):
            capture_project_snapshot(
                **self.callbacks,
                source_paths=paths,
                root=self.base / "restoration",
                lock_root=self.base / "locks",
                writer=self._writer,
            )
        self.assertEqual(self.writer_calls, [])

    def test_incomplete_preflight_blocks_writer(self):
        def incomplete(_paths, *, project_name, approved_source_revision):
            self.assertTrue(approved_source_revision)
            return {"project_name": project_name, "selected_services": ["stt"]}

        with self.assertRaisesRegex(SnapshotCaptureError, "preflight is incomplete"):
            capture_project_snapshot(
                **self.callbacks,
                source_paths=self.paths,
                root=self.base / "restoration",
                lock_root=self.base / "locks",
                run_preflight=incomplete,
                writer=self._writer,
            )
        self.assertEqual(self.writer_calls, [])

    def test_production_artifact_check_uses_retained_model_store(self):
        release = {
            "git_source_revision": "f" * 40,
            "services": {
                service: {
                    "image": f"example/{service}@sha256:{service}",
                    "required_model_artifacts": (
                        [{"id": "large-v3-turbo", "manifest_sha256": "a" * 64}]
                        if service == "stt"
                        else []
                    ),
                }
                for service in ("gateway", "stt", "tts")
            },
        }
        expected_artifacts = {
            service: sorted(
                ["oci://" + release["services"][service]["image"]]
                + [
                    "model://" + model["id"] + "@sha256:" + model["manifest_sha256"]
                    for model in release["services"][service][
                        "required_model_artifacts"
                    ]
                ]
            )
            for service in ("gateway", "stt", "tts")
        }
        store = Path("/srv/speech-platform/models")
        callbacks = adapter.production_callbacks(retained_model_store=store)
        with (
            patch.object(adapter, "load_release", return_value=release),
            patch.object(adapter, "load_and_validate"),
            patch.object(adapter, "_require_release_match"),
            patch.object(adapter, "verify_registry_image"),
            patch.object(adapter, "_inspect_service_image"),
            patch.object(adapter, "check_models") as check_models,
        ):
            callbacks["verify_artifacts"](expected_artifacts)
        check_models.assert_called_once_with(release, store, adapter.REPOSITORY_ROOT)

    def test_production_callbacks_keep_expected_and_observed_evidence_separate(self):
        source_paths = {}
        for role in CAPTURE_SOURCE_FILES:
            path = self.base / role
            path.write_bytes(("captured:" + role).encode())
            source_paths[role] = path

        release = {
            "services": {
                service: {
                    "image": f"registry.invalid/{service}@sha256:{service[0] * 64}",
                    "platform": "linux/amd64",
                    "required_model_artifacts": [],
                }
                for service in ("gateway", "stt", "tts")
            },
            "git_source_revision": "f" * 40,
        }
        observed = {
            service: {
                "service": service,
                "container_id": "container-" + service,
                "project_name": PROJECT,
                "image_id": "sha256:" + service[0] * 64,
                "image_reference": release["services"][service]["image"],
                "platform": "linux/amd64",
                "compose_config_hash": "1" * 64,
                "configuration_sha256": "2" * 64,
                "runtime_identity_sha256": "3" * 64,
                "compatible": True,
                "state": "running",
                "health": "healthy",
                "readiness": {
                    "status": "READY",
                    "capability": "health",
                    "evidence_sha256": "4" * 64,
                    "observed_at_epoch": time.time(),
                },
            }
            for service in ("gateway", "stt", "tts")
        }
        rendered = {"name": PROJECT, "services": {}}
        evidence_payload = {
            "release": release,
            "selected_services": ["gateway", "stt", "tts"],
            "expected_runtime_contract": {
                service: {
                    "configuration_sha256": "2" * 64,
                    "runtime_identity_sha256": "3" * 64,
                }
                for service in observed
            },
            "observations": list(observed.values()),
            "rendered_compose": rendered,
            "compose_service_hashes": {service: "1" * 64 for service in observed},
            "render_environment": {"captured": "environment"},
            "plan": {
                "blockers": [
                    f"{service}:restore_inputs_missing" for service in observed
                ]
            },
        }

        def fake_collect(*, run, evidence_sink, compose_paths=None):
            if compose_paths is not None:
                self.assertEqual(
                    compose_paths["compose.yaml"].read_bytes(),
                    b"captured:compose.yaml",
                )
                self.assertEqual(
                    compose_paths["compose.stt-cuda.yaml"].read_bytes(),
                    b"captured:compose.stt-cuda.yaml",
                )
            evidence_sink.update(evidence_payload)
            return evidence_payload["plan"]

        with (
            patch.object(adapter, "SOURCE_PATHS", source_paths),
            patch.object(adapter, "collect_baseline_adoption", fake_collect),
            patch.object(adapter, "host_bindings_sha256", return_value="5" * 64),
        ):
            callbacks = adapter.production_callbacks(
                retained_model_store=self.base / "retained-models",
                run=lambda command, **_kwargs: {
                    "docker version": "29.1.3\n",
                    "docker compose": "v2.39.2\n",
                }["docker version" if command[1] == "version" else "docker compose"],
            )
            files = {role: path.read_bytes() for role, path in source_paths.items()}
            contract = callbacks["validate_configuration"](files)
            self.assertEqual(contract["selected_services"], ["gateway", "stt", "tts"])
            self.assertEqual(
                contract["runtime_identity_sha256_by_service"]["stt"], "3" * 64
            )
            rendered_result = callbacks["render_captured"](files)
            self.assertEqual(rendered_result["compose_service_hashes"]["stt"], "1" * 64)
            runtime = callbacks["collect_runtime"]()
            self.assertEqual(
                runtime["services"]["stt"]["runtime_identity_sha256"], "3" * 64
            )

    def test_production_preflight_rejects_unapproved_tracked_source_paths(self):
        for role in CAPTURE_SOURCE_FILES:
            path = self.base / role
            path.write_text("fixture", encoding="utf-8")
            path.chmod(
                0o644
                if role in {"compose.yaml", "compose.stt-cuda.yaml", "release.yaml"}
                else 0o600
            )
        paths = {role: self.base / role for role in CAPTURE_SOURCE_FILES}
        (self.base / "compose.yaml").chmod(0o664)
        with self.assertRaisesRegex(SnapshotCaptureError, "tracked Compose or release"):
            adapter.validate_project_inputs(paths)

    def test_production_artifact_callback_requires_images_and_complete_model_set(self):
        release = {
            "git_source_revision": "f" * 40,
            "services": {
                service: {
                    "image": f"registry.invalid/{service}@sha256:{service[0] * 64}",
                    "required_model_artifacts": [],
                }
                for service in ("gateway", "stt", "tts")
            },
        }
        references = {
            service: ["oci://" + release["services"][service]["image"]]
            for service in ("gateway", "stt", "tts")
        }
        callbacks = adapter.production_callbacks(
            retained_model_store=self.base / "retained-models",
            run=lambda *_args, **_kwargs: "",
        )
        with (
            patch.object(adapter, "load_release", return_value=release),
            patch.object(adapter, "load_and_validate", return_value={}),
            patch.object(adapter, "_require_release_match"),
            patch.object(adapter, "verify_registry_image"),
            patch.object(adapter, "_inspect_service_image"),
            patch.object(adapter, "check_models") as check_models,
        ):
            callbacks["verify_artifacts"](references)
            check_models.assert_called_once()
            with patch.object(adapter, "check_models", side_effect=OSError):
                with self.assertRaisesRegex(
                    SnapshotCaptureError, "immutable image or model verification failed"
                ):
                    callbacks["verify_artifacts"](references)


if __name__ == "__main__":
    unittest.main()
