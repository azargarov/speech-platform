"""Fixture-only tests for the read-only baseline adoption planner."""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.baseline_adoption import plan_baseline_adoption
from scripts.collect_baseline_adoption import _docker_json
from scripts.collect_baseline_adoption import _compose_service_hashes
from scripts.model_artifacts import ModelProvisionError
from scripts.release_manifest import DEFAULT_RELEASE, REPOSITORY_ROOT, load_release
from scripts.restore_snapshot import (
    DIGEST_ENV_KEYS,
    IMAGE_ENV_KEYS,
    IMAGE_ID_KEYS,
    INTEGER_ENV_KEYS,
    MEMORY_ENV_KEYS,
    NUMBER_ENV_KEYS,
    PATH_ENV_KEYS,
    PERSISTED_ENV_KEYS,
    PROJECT_ENV_KEYS,
    PROJECT_FILES,
    RENDER_ENV_KEYS,
    REVISION_ENV_KEYS,
    SERVICES,
    host_bindings_sha256,
    verify_retained_snapshot,
)


class BaselineAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.state_root = root / "state"
        self.lock_root = root / "locks"
        self.release = load_release(DEFAULT_RELEASE, REPOSITORY_ROOT)
        self.project = "speech-platform-m01e-fresh-v012"
        self.services = sorted(self.release["services"])
        self.restore = [self._restore(name) for name in self.services]
        self.expected = {name: self._contract(name) for name in self.services}
        self.runtime = [self._runtime(name) for name in self.services]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _restore(name):
        return {
            "service": name,
            "configuration_snapshot": {
                "kind": "private_snapshot",
                "reference": "private://snapshots/sha256/" + "d" * 64,
                "sha256": "d" * 64,
                "schema_version": 3,
            },
            "configuration_sha256": "a" * 64,
            "secret_versions": [],
            "runtime_definition": {
                "kind": "private_snapshot",
                "reference": "private://snapshots/sha256/" + "d" * 64,
                "sha256": "d" * 64,
                "schema_version": 3,
            },
            "runtime_sha256": "b" * 64,
            "available": True,
        }

    @staticmethod
    def _contract(name):
        return {
            "mounts": [
                {
                    "source": f"/private/{name}.yaml",
                    "target": f"/config/{name}.yaml",
                    "read_only": True,
                }
            ],
            "networks": ["private" if name != "gateway" else "publish", "private"],
            "ports": [18080] if name == "gateway" else [],
            "uid": 65532,
            "gid": 65532,
            "supplementary_gids": [988],
            "read_only_rootfs": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "privileged": False,
            "no_new_privileges": True,
            "configuration_sha256": "a" * 64,
            "runtime_identity_sha256": "b" * 64,
        }

    def _runtime(self, name):
        entry = self.release["services"][name]
        return {
            "service": name,
            "project_name": self.project,
            "container_id": f"container-{name}",
            "image_id": "sha256:" + "f" * 64,
            "compose_config_hash": "9" * 64,
            "state": "running",
            "health": "healthy",
            "image_reference": entry["image"],
            "image_manifest_sha256": entry["image"].split("sha256:", 1)[1],
            "platform": entry["platform"],
            "provenance": {
                "verified": True,
                "evidence_sha256": "c" * 64,
                "image_reference": entry["image"],
                "image_manifest_sha256": entry["image"].split("sha256:", 1)[1],
                "platform": entry["platform"],
            },
            "configuration_sha256": "a" * 64,
            "runtime_identity_sha256": "b" * 64,
            "model_identities": [
                {
                    "model_id": model["id"],
                    "revision": model["revision"],
                    "manifest_sha256": model["manifest_sha256"],
                }
                for model in entry["required_model_artifacts"]
            ],
            "mounts": self.expected[name]["mounts"],
            "networks": self.expected[name]["networks"],
            "ports": self.expected[name]["ports"],
            "uid": 65532,
            "gid": 65532,
            "supplementary_gids": [988],
            "read_only_rootfs": True,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "privileged": False,
            "no_new_privileges": True,
            "readiness": {
                "status": "READY",
                "capability": "readiness"
                if "readiness" in entry["capabilities"]
                else "health",
                "evidence_sha256": "d" * 64,
                "observed_at_epoch": time.time(),
            },
            "compatible": True,
        }

    def _plan(self, **overrides):
        inputs = {
            "project_name": self.project,
            "enabled_services": self.services,
            "runtime_observations": self.runtime,
            "expected_runtime_contract": self.expected,
            "restore_inputs": self.restore,
            "state_root": self.state_root,
            "lock_root": self.lock_root,
            "release_path": DEFAULT_RELEASE,
            "model_store": Path(self.temp.name) / "models",
            "repository_root": REPOSITORY_ROOT,
            "model_checker": lambda release, _store, _root: [
                SimpleNamespace(artifact_id=model["id"])
                for service in release["services"].values()
                for model in service["required_model_artifacts"]
            ],
        }
        inputs.update(overrides)
        return plan_baseline_adoption(**inputs)

    def test_eligible_plan_is_deterministic_and_does_not_initialize_state_or_lock(self):
        first = self._plan()
        second = self._plan()
        self.assertTrue(first["eligible"], first["blockers"])
        self.assertEqual(first, second)
        self.assertTrue(first["plan_fingerprint"])
        self.assertEqual(first["candidate_generation_id"][:3], "g0-")
        self.assertFalse(self.state_root.exists())
        self.assertFalse(self.lock_root.exists())

    def test_eligible_real_host_shaped_fixture(self):
        plan = self._plan()
        self.assertTrue(plan["eligible"], plan["blockers"])
        self.assertEqual(plan["project_name"], self.project)
        self.assertEqual(plan["selected_services"], ["gateway", "stt", "tts"])
        self.assertEqual(set(plan["services"]), set(self.services))
        for service in plan["services"].values():
            self.assertTrue(service["container_id"])
            self.assertTrue(service["compose_config_hash"])

    def test_correctly_observed_stt_runtime_identity_is_eligible(self):
        stt = next(item for item in self.runtime if item["service"] == "stt")
        stt["runtime_identity_sha256"] = self.expected["stt"]["runtime_identity_sha256"]
        plan = self._plan()
        self.assertTrue(plan["eligible"], plan["blockers"])

    def test_missing_stt_runtime_identity_blocks(self):
        stt = next(item for item in self.runtime if item["service"] == "stt")
        stt["runtime_identity_sha256"] = None
        plan = self._plan()
        self.assertIn("stt:runtime_verification_failed", plan["blockers"])

    def test_mismatched_stt_runtime_identity_blocks(self):
        stt = next(item for item in self.runtime if item["service"] == "stt")
        stt["runtime_identity_sha256"] = "0" * 64
        plan = self._plan()
        self.assertIn("stt:runtime_verification_failed", plan["blockers"])

    def test_incomplete_restore_snapshot_blocks(self):
        self.restore[1]["available"] = False
        plan = self._plan()
        self.assertIn("stt:restore_inputs_incomplete", plan["blockers"])

    def test_mixed_project_snapshot_references_block(self):
        self.restore[0]["configuration_snapshot"]["sha256"] = "f" * 64
        self.restore[0]["configuration_snapshot"]["reference"] = (
            "private://snapshots/sha256/" + "f" * 64
        )
        self.restore[0]["runtime_definition"]["sha256"] = "f" * 64
        self.restore[0]["runtime_definition"]["reference"] = (
            "private://snapshots/sha256/" + "f" * 64
        )
        plan = self._plan()
        self.assertIn("restore_snapshot_project_identity_mismatch", plan["blockers"])

    def test_fully_valid_retained_snapshot_fixture_is_eligible(self):
        plan = self._plan()
        self.assertTrue(plan["eligible"], plan["blockers"])
        self.assertEqual(
            plan["configuration"]["stt"]["configuration_snapshot"]["sha256"],
            "d" * 64,
        )

    @staticmethod
    def _fixture_env_value(key):
        if key in PATH_ENV_KEYS:
            names = {
                "GATEWAY_CONFIG": "gateway.yaml",
                "TTS_CONFIG": "tts.yaml",
                "STT_APPLICATION_CONFIG": "stt-application.yaml",
                "STT_DEPLOYMENT_CONFIG": "stt-deployment.yaml",
                "STT_WORKER_CONFIG": "stt.yaml",
            }
            if key == "STT_MODEL_HOST_ROOT":
                return "/private/model-store/" + "e" * 64
            return "/private/config/" + names[key]
        if key in IMAGE_ENV_KEYS:
            return "registry.invalid/service@sha256:" + "a" * 64
        if key in IMAGE_ID_KEYS:
            return "sha256:" + "b" * 64
        if key in DIGEST_ENV_KEYS:
            return "c" * 64
        if key in REVISION_ENV_KEYS:
            return "d" * 40
        if key in INTEGER_ENV_KEYS or key in {"GATEWAY_PIDS", "TTS_PIDS"}:
            return "1"
        if key in NUMBER_ENV_KEYS:
            return "1.0"
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
        raise AssertionError(f"unclassified fixture environment key: {key}")

    def _write_snapshot_fixture(
        self,
        root,
        *,
        incomplete=False,
        compose_env_override=None,
        secret_reference=False,
    ):
        root.mkdir(parents=True, mode=0o700)
        object_dir = root / "objects/sha256"
        object_dir.mkdir(parents=True, mode=0o700)
        persisted = {
            key: self._fixture_env_value(key) for key in sorted(PERSISTED_ENV_KEYS)
        }
        rendered_env = {
            key: self._fixture_env_value(key) for key in sorted(RENDER_ENV_KEYS)
        }
        blobs = {
            name: f"fixture:project:{name}".encode()
            for name in PROJECT_FILES
            - {"compose.env", "render-environment.json", "rendered-compose.json"}
        }
        blobs["compose.env"] = (
            compose_env_override
            or "".join(
                f"{key}={json.dumps(value)}\n"
                for key, value in sorted(persisted.items())
            ).encode()
        )
        blobs["render-environment.json"] = json.dumps(
            rendered_env, sort_keys=True, separators=(",", ":")
        ).encode()
        rendered_mounts = {
            "gateway": {"/config/gateway.yaml": rendered_env["GATEWAY_CONFIG"]},
            "tts": {"/config/tts.yaml": rendered_env["TTS_CONFIG"]},
            "stt": {
                "/config/stt-application.yaml": rendered_env["STT_APPLICATION_CONFIG"],
                "/config/stt-deployment.yaml": rendered_env["STT_DEPLOYMENT_CONFIG"],
                "/config/stt.yaml": rendered_env["STT_WORKER_CONFIG"],
                "/models": rendered_env["STT_MODEL_HOST_ROOT"],
            },
        }
        rendered_compose = {
            "name": "speech-platform-fixture",
            "services": {
                service: {
                    "image": "fixture",
                    "volumes": [
                        {
                            "type": "bind",
                            "source": source,
                            "target": target,
                            "read_only": True,
                        }
                        for target, source in rendered_mounts[service].items()
                    ],
                }
                for service in SERVICES
            },
        }
        blobs["rendered-compose.json"] = json.dumps(
            rendered_compose, sort_keys=True, separators=(",", ":")
        ).encode()
        files = {}
        names = sorted(PROJECT_FILES)
        if incomplete:
            names.pop()
        for name in names:
            content = blobs[name]
            blob_digest = hashlib.sha256(content).hexdigest()
            blob = object_dir / blob_digest
            blob.write_bytes(content)
            blob.chmod(0o600)
            files[name] = {
                "sha256": blob_digest,
                "size_bytes": len(content),
                "classification": "non_secret_configuration",
            }
        artifacts = {
            service: ["oci://registry.invalid/" + service + "@sha256:" + "a" * 64]
            for service in SERVICES
        }
        artifacts["stt"].append("model://fixture/model@sha256:" + "b" * 64)
        manifest = {
            "schema_version": 3,
            "project_name": "speech-platform-fixture",
            "source_revision": "c" * 40,
            "source_git_blob_ids": {
                "compose.yaml": "d" * 40,
                "compose.stt-cuda.yaml": "e" * 40,
                "release.yaml": "f" * 40,
            },
            "selected_services": list(SERVICES),
            "optional_file_roles": [],
            "files": files,
            "artifacts_by_service": {
                service: sorted(refs) for service, refs in artifacts.items()
            },
            "secret_versions_by_service": {
                service: (
                    [f"vault://unapproved/{service}/version-4"]
                    if secret_reference
                    else []
                )
                for service in SERVICES
            },
            "rendered_compose_sha256": hashlib.sha256(
                blobs["rendered-compose.json"]
            ).hexdigest(),
            "compose_service_hashes": {service: "e" * 64 for service in SERVICES},
            "configuration_sha256_by_service": {
                service: "f" * 64 for service in SERVICES
            },
            "runtime_identity_sha256_by_service": {
                service: "e" * 64 for service in SERVICES
            },
            "host_bindings_sha256": host_bindings_sha256(rendered_compose),
            "docker_engine_version": "29.1.3",
            "compose_version": "v5.6.0",
        }
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(raw).hexdigest()
        snapshots_hash = root / "snapshots/sha256"
        snapshots_hash.mkdir(parents=True, mode=0o700)
        directory = snapshots_hash / digest
        directory.mkdir(mode=0o700)
        for path in (
            root,
            root.parent,
            root.parent.parent,
            root.parent.parent.parent,
            root / "objects",
            object_dir,
            root / "snapshots",
            snapshots_hash,
        ):
            path.chmod(0o700)
        path = directory / "manifest.json"
        path.write_bytes(raw)
        path.chmod(0o600)
        return digest

    def _snapshot_root(self):
        return Path(self.temp.name) / "private/deployment/fixture/restoration"

    def _verify_snapshot(self, root, digest, expected_artifacts_by_service=None):
        return verify_retained_snapshot(
            root,
            "stt",
            digest,
            project_name="speech-platform-fixture",
            expected_artifacts_by_service=expected_artifacts_by_service,
        )

    def test_incomplete_retained_snapshot_is_rejected(self):
        root = self._snapshot_root()
        digest = self._write_snapshot_fixture(root, incomplete=True)
        with self.assertRaisesRegex(
            ValueError, "schema or project inputs are incomplete"
        ):
            self._verify_snapshot(root, digest)

    def test_fully_valid_retained_snapshot_is_verified(self):
        root = self._snapshot_root()
        digest = self._write_snapshot_fixture(root)
        artifacts = {
            service: sorted(
                ["oci://registry.invalid/" + service + "@sha256:" + "a" * 64]
                + (
                    ["model://fixture/model@sha256:" + "b" * 64]
                    if service == "stt"
                    else []
                )
            )
            for service in SERVICES
        }
        manifest = self._verify_snapshot(root, digest, artifacts)
        self.assertEqual(manifest["selected_services"], list(SERVICES))
        self.assertEqual(set(manifest["files"]), PROJECT_FILES)

    def test_snapshot_rejects_secret_key_in_compose_env(self):
        root = self._snapshot_root()
        digest = self._write_snapshot_fixture(
            root, compose_env_override=b'API_TOKEN="not-a-real-token"\n'
        )
        with self.assertRaisesRegex(ValueError, "forbidden sensitive content"):
            self._verify_snapshot(root, digest)

    def test_snapshot_rejects_unapproved_secret_reference_scheme(self):
        root = self._snapshot_root()
        digest = self._write_snapshot_fixture(root, secret_reference=True)
        with self.assertRaisesRegex(ValueError, "approved resolver"):
            self._verify_snapshot(root, digest)

    def test_snapshot_rejects_raw_secret_marker_in_yaml_blob(self):
        root = self._snapshot_root()
        digest = self._write_snapshot_fixture(root)
        manifest_path = root / "snapshots/sha256" / digest / "manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        identity = manifest["files"]["gateway.yaml"]
        old_blob = root / "objects/sha256" / identity["sha256"]
        old_blob.unlink()
        content = b"api_token: fixture-secret-value"
        identity["sha256"] = hashlib.sha256(content).hexdigest()
        identity["size_bytes"] = len(content)
        blob = root / "objects/sha256" / identity["sha256"]
        blob.write_bytes(content)
        blob.chmod(0o600)
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        new_digest = hashlib.sha256(raw).hexdigest()
        new_directory = manifest_path.parent.parent / new_digest
        new_directory.mkdir(mode=0o700)
        new_manifest = new_directory / "manifest.json"
        new_manifest.write_bytes(raw)
        new_manifest.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "forbidden sensitive content"):
            self._verify_snapshot(root, new_digest)

    def test_snapshot_rejects_hard_linked_blob(self):
        root = self._snapshot_root()
        digest = self._write_snapshot_fixture(root)
        manifest = json.loads(
            (root / "snapshots/sha256" / digest / "manifest.json").read_bytes()
        )
        identity = manifest["files"]["gateway.yaml"]
        blob = root / "objects/sha256" / identity["sha256"]
        (Path(self.temp.name) / "outside-link").hardlink_to(blob)
        with self.assertRaisesRegex(ValueError, "link count or mode"):
            self._verify_snapshot(root, digest)

    def test_expected_compose_hash_is_derived_and_validated(self):
        digest = "a" * 64
        hashes = _compose_service_hashes(
            ["stt"], {}, lambda _command, environment: digest
        )
        self.assertEqual(hashes, {"stt": digest})
        with self.assertRaisesRegex(ValueError, "invalid service hash"):
            _compose_service_hashes(["stt"], {}, lambda *_args, **_kwargs: "")

    def test_missing_model_artifact_blocks(self):
        def missing(*_args):
            raise ModelProvisionError("missing")

        plan = self._plan(model_checker=missing)
        self.assertIn("model_artifacts_missing_or_invalid", plan["blockers"])

    def test_incorrect_image_digest_blocks(self):
        self.runtime[0]["image_manifest_sha256"] = "f" * 64
        self.assertTrue(
            any("image_verification_failed" in b for b in self._plan()["blockers"])
        )

    def test_runtime_configuration_drift_blocks(self):
        self.runtime[0]["mounts"] = []
        plan = self._plan()
        self.assertTrue(
            any("runtime_mounts_verification_failed" in b for b in plan["blockers"])
        )

    def test_security_identity_drift_blocks(self):
        self.runtime[0]["cap_drop"] = []
        plan = self._plan()
        self.assertIn("gateway:runtime_cap_drop_verification_failed", plan["blockers"])

    def test_expected_observed_configuration_mismatch_blocks(self):
        self.runtime[0]["configuration_sha256"] = "f" * 64
        plan = self._plan()
        self.assertIn("gateway:configuration_verification_failed", plan["blockers"])

    def test_missing_or_contradictory_docker_observations_block(self):
        missing = self._plan(runtime_observations=self.runtime[:-1])
        self.assertIn("runtime_service_selection_mismatch", missing["blockers"])
        contradictory = [dict(value) for value in self.runtime]
        contradictory[0]["project_name"] = "another-project"
        plan = self._plan(runtime_observations=contradictory)
        self.assertIn("gateway:project_verification_failed", plan["blockers"])

    def test_docker_inspection_failure_is_rejected(self):
        def failed(_command):
            raise RuntimeError("docker unavailable")

        with self.assertRaisesRegex(ValueError, "Docker inspection failed"):
            _docker_json(failed, ["docker", "inspect", "container"])

        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            _docker_json(lambda _command: "[]", ["docker", "inspect", "container"])

    def test_stale_readiness_evidence_blocks(self):
        self.runtime[0]["readiness"]["observed_at_epoch"] = 1
        plan = self._plan(now_epoch=2_000_000_000)
        self.assertIn("gateway:health_verification_failed", plan["blockers"])

    def test_unhealthy_service_blocks(self):
        self.runtime[0]["health"] = "unhealthy"
        self.assertTrue(
            any("health_verification_failed" in b for b in self._plan()["blockers"])
        )

    def test_unknown_service_blocks(self):
        unknown = dict(self.runtime[-1], service="rogue")
        plan = self._plan(runtime_observations=self.runtime + [unknown])
        self.assertIn("runtime_service_selection_mismatch", plan["blockers"])
        self.assertIn("rogue:unknown_or_unselected_runtime_service", plan["blockers"])

    def test_missing_restore_inputs_blocks(self):
        self.restore.pop()
        self.assertTrue(
            any("restore_inputs_missing" in b for b in self._plan()["blockers"])
        )

    def test_existing_generation_blocks(self):
        with patch("scripts.baseline_adoption.StateStore") as store_type:
            store_type.return_value.inspect.return_value = {
                "status": "OK",
                "generation_ids": ["g0-old"],
                "operation_ids": [],
                "installed_generation_id": "g0-old",
                "issues": [],
            }
            (self.state_root / self.project).mkdir(parents=True)
            plan = self._plan()
        self.assertIn("installed_generation_already_present", plan["blockers"])

    def test_uncertainty_marker_blocks_without_lock_acquisition(self):
        self.lock_root.mkdir()
        marker = self.lock_root / f"{self.project}.uncertain"
        marker.write_text("unresolved", encoding="utf-8")
        marker.chmod(0o600)
        plan = self._plan()
        self.assertIn("unresolved_uncertainty_marker", plan["blockers"])
        self.assertTrue(marker.exists())

    def test_unsupported_compatibility_blocks(self):
        self.runtime[0]["compatible"] = False
        self.assertTrue(
            any(
                "compatibility_verification_failed" in b
                for b in self._plan()["blockers"]
            )
        )

    def test_unsupported_dependency_blocks(self):
        invalid_release = {
            **self.release,
            "services": {
                **self.release["services"],
                "gateway": {
                    **self.release["services"]["gateway"],
                    "dependencies": ["unpublished-service"],
                },
            },
        }
        plan = self._plan(release_loader=lambda *_args: invalid_release)
        self.assertIn("service_selection_or_registry_invalid", plan["blockers"])

    def test_stale_or_malformed_state_blocks(self):
        (self.state_root / self.project).mkdir(parents=True)
        plan = self._plan()
        self.assertIn("deployment_state_missing_parts_or_malformed", plan["blockers"])

    def test_shared_state_root_without_project_state_is_absent(self):
        self.state_root.mkdir()
        (self.state_root / "locks").mkdir()
        plan = self._plan()
        self.assertTrue(plan["eligible"], plan["blockers"])
        self.assertEqual(plan["deployment_state"]["status"], "ABSENT")

    def test_symlinked_state_root_blocks_even_without_project_directory(self):
        target = self.state_root.with_name("state-target")
        target.mkdir()
        self.state_root.symlink_to(target, target_is_directory=True)
        plan = self._plan()
        self.assertIn("deployment_state_root_malformed_or_unsafe", plan["blockers"])


if __name__ == "__main__":
    unittest.main()
