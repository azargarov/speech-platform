from __future__ import annotations

import copy
import base64
import contextlib
import errno
import hashlib
import io
import json
import os
import tempfile
import tarfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

from scripts.stt_deployment_profile import (
    compose_environment,
    configuration_set_sha256,
    load_and_validate,
    preflight_host_gpu,
    require_private_config_paths,
    validate_rendered_compose,
    validate_created_container_inspection,
    validate_local_image_inspection,
    validate_local_artifact_identity,
    validate_local_image_runtime_versions,
    verify_created_container_with_docker,
    verify_local_image_with_docker,
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
        self.release.rename(self.root / self.manifest_digest)
        self.release = self.root / self.manifest_digest

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
            "schema_version": 2,
            "project_name": "speech-platform-test",
            "gateway": {"host_port": 18080, "listen_port": 8080},
            "runtime": {
                "identity_mode": "registry_digest",
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
                "artifact_owner_uid": os.getuid(),
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
            path.chmod(0o2750)
        (self.release / "manifest.yaml").chmod(0o640)
        (self.release / "artifact" / "model.bin").chmod(0o640)
        self.profile_path = self.root / "profile.yaml"
        self._write_profile()
        self.registry_runtime = copy.deepcopy(self.profile["runtime"])

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _write_yaml(path, value):
        path.write_text(yaml.safe_dump(value, sort_keys=False))

    def _write_profile(self):
        self._write_yaml(self.profile_path, self.profile)

    def _local_image_evidence(self):
        runtime = copy.deepcopy(self.registry_runtime)
        self.profile["runtime"] = runtime
        runtime["identity_mode"] = "local_image_id"
        runtime.pop("image")
        runtime.pop("image_reference_verified")
        runtime["image_id"] = "sha256:" + "6" * 64
        archive_path = self.root / "approved-image.tar"
        layer_data = b"fixture layer data"
        diff_id = "sha256:" + hashlib.sha256(layer_data).hexdigest()
        raw_config = json.dumps(
            {
                "architecture": "amd64",
                "os": "linux",
                "config": {"User": "65532:65532", "Entrypoint": ["python", "-m"]},
                "rootfs": {"type": "layers", "diff_ids": [diff_id]},
                "history": [{"created_by": "fixture"}],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        config_digest = "sha256:" + hashlib.sha256(raw_config).hexdigest()
        config_path = f"blobs/sha256/{config_digest.split(':', 1)[1]}"
        layer_path = "layers/fixture/layer.tar"
        manifest = json.dumps(
            [{"Config": config_path, "RepoTags": None, "Layers": [layer_path]}],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        with tarfile.open(archive_path, "w:") as archive:
            for name, data in (
                ("manifest.json", manifest),
                (config_path, raw_config),
                (layer_path, layer_data),
            ):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
        runtime["image_id"] = config_digest
        identity = {
            "identity_kind": "docker_config_digest",
            "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "config_digest": config_digest,
            "raw_config_sha256": config_digest,
            "rootfs_diff_ids": [diff_id],
        }
        runtime["artifact_identity"] = identity
        runtime["image_store_evidence_sha256"] = "0" * 64
        runtime["build_evidence_sha256"] = "0" * 64
        labels = {
            "org.opencontainers.image.revision": runtime["source_revision"],
            "com.speech-platform.source-revision": runtime["source_revision"],
            "com.speech-platform.image-role": "stt-worker",
            "com.speech-platform.base-image": runtime["base_image"],
            "com.speech-platform.cuda-lock-sha256": runtime["cuda_lock_sha256"],
        }
        evidence = {
            "status": "BUILD_SUCCEEDED_IMAGE_NOT_RUN",
            "source_commit": runtime["source_revision"],
            "dependency_lock_sha256": runtime["cuda_lock_sha256"],
            "base": {
                "platform": runtime["base_image_platform"],
                "platform_manifest_digest": runtime["base_image"].rsplit("@", 1)[1],
            },
            "image": {
                "id": identity["config_digest"],
                "platform": runtime["platform"],
                "labels": labels,
            },
        }
        evidence_path = self.root / "build-evidence.json"
        evidence_path.write_text(json.dumps(evidence, sort_keys=True))
        runtime["build_evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
        store_evidence = {
            "schema_version": 1,
            "docker_image_id": runtime["image_id"],
            "platform": runtime["platform"],
            **identity,
        }
        store_path = self.root / "image-store-evidence.json"
        store_path.write_text(json.dumps(store_evidence, sort_keys=True))
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            store_path.read_bytes()
        ).hexdigest()
        self.image_archive_path = archive_path
        self.image_store_evidence_path = store_path
        self._write_profile()
        return evidence_path, evidence

    def _containerd_image_evidence(self):
        build_path, build_evidence = self._local_image_evidence()
        runtime = self.profile["runtime"]
        identity = runtime["artifact_identity"]
        layer_digest = "sha256:" + "e" * 64
        layer = {
            "digest": layer_digest,
            "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
            "size": 10,
        }
        with tarfile.open(self.image_archive_path, "r:") as archive:
            archive_manifest = json.load(archive.extractfile("manifest.json"))
            config_size = len(archive.extractfile(archive_manifest[0]["Config"]).read())
        manifest_raw = json.dumps(
            {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "config": {
                    "digest": identity["config_digest"],
                    "mediaType": "application/vnd.oci.image.config.v1+json",
                    "size": config_size,
                },
                "layers": [layer],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        manifest_digest = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
        identity.update(
            {
                "identity_kind": "containerd_oci_manifest",
                "namespace": "moby",
                "image_record_reference": "sha256:" + "a" * 64,
                "matching_image_records": 1,
                "manifest_digest": manifest_digest,
                "manifest_media_type": "application/vnd.oci.image.manifest.v1+json",
                "manifest_config_digest": identity["config_digest"],
                "manifest_config_media_type": "application/vnd.oci.image.config.v1+json",
                "manifest_config_size_bytes": config_size,
                "manifest_layers": [
                    {
                        "digest": layer_digest,
                        "media_type": layer["mediaType"],
                        "size_bytes": layer["size"],
                    }
                ],
                "verified_layer_digests": [layer_digest],
            }
        )
        runtime["image_id"] = manifest_digest
        store_evidence = {
            "schema_version": 1,
            "docker_image_id": runtime["image_id"],
            "platform": runtime["platform"],
            **identity,
            "raw_manifest_base64": base64.b64encode(manifest_raw).decode("ascii"),
        }
        self.image_store_evidence_path.write_text(
            json.dumps(store_evidence, sort_keys=True)
        )
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            self.image_store_evidence_path.read_bytes()
        ).hexdigest()
        self._write_profile()
        return build_path, build_evidence

    def _validate(
        self,
        *,
        verify_files=True,
        dockerfile_path="deployments/compose/worker-stt-cuda.Dockerfile",
        build_evidence_path=None,
    ):
        return load_and_validate(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            dockerfile_path=dockerfile_path,
            build_evidence_path=build_evidence_path,
            image_archive_path=(
                self.image_archive_path if build_evidence_path is not None else None
            ),
            image_store_evidence_path=(
                self.image_store_evidence_path
                if build_evidence_path is not None
                else None
            ),
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
                    "networks": {
                        "gateway_publish": None,
                        "stt_private": None,
                        "tts_private": None,
                    },
                    "ports": [
                        {
                            "mode": "ingress",
                            "host_ip": "127.0.0.1",
                            "target": profile["gateway"]["listen_port"],
                            "published": str(profile["gateway"]["host_port"]),
                            "protocol": "tcp",
                        }
                    ],
                },
                "tts": {
                    "networks": {"tts_private": None},
                    "group_add": [
                        str(validated["artifact_access"]["supplementary_read_gid"])
                    ],
                },
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
                    "stop_grace_period": "2m5s",
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
                        "start_period": "2m10s",
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
                        "com.speech-platform.image-identity-mode": validated[
                            "identity_mode"
                        ],
                        "com.speech-platform.image-id": validated["image_id"],
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
                        "com.speech-platform.configuration-set-sha256": validated[
                            "configuration_set_sha256"
                        ],
                    },
                },
            },
            "networks": {
                "gateway_publish": {
                    "driver": "bridge",
                    "driver_opts": {
                        "com.docker.network.bridge.enable_ip_masquerade": "false"
                    },
                },
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
        self.assertEqual(environment["STT_IMAGE_IDENTITY_MODE"], "registry_digest")
        self.assertEqual(
            environment["STT_IMAGE_ID"], self.profile["runtime"]["image_id"]
        )
        self.assertEqual(
            environment["STT_CUDA_IMAGE"], self.profile["runtime"]["image"]
        )
        self.assertEqual(
            environment["STT_CONFIGURATION_SET_SHA256"],
            configuration_set_sha256(
                self.profile_path,
                self.application_path,
                self.deployment_path,
                self.worker_path,
            ),
        )
        private = self.root / "private"
        env_path = private / "stt-compose.env"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        write_env_file(env_path, environment, repository_root=self.root)
        self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)
        self.assertIn("STT_MODEL_MANIFEST_SHA256", env_path.read_text())

    def test_local_image_id_mode_verifies_build_record_and_selects_exact_id(self):
        evidence_path, _ = self._local_image_evidence()
        validated = self._validate(build_evidence_path=evidence_path)
        self.assertEqual(validated["identity_mode"], "local_image_id")
        self.assertEqual(validated["image"], self.profile["runtime"]["image_id"])
        environment = compose_environment(
            validated,
            self.application_path,
            self.deployment_path,
            self.worker_path,
        )
        self.assertEqual(environment["STT_CUDA_IMAGE"], environment["STT_IMAGE_ID"])
        self.assertEqual(environment["STT_IMAGE_IDENTITY_MODE"], "local_image_id")
        rendered = self._compose(validated)
        validate_rendered_compose(rendered, validated)

    def test_local_image_id_render_rejects_pull_build_and_identity_overrides(self):
        evidence_path, _ = self._local_image_evidence()
        validated = self._validate(build_evidence_path=evidence_path)
        rendered = self._compose(validated)
        mutations = (
            lambda value: value["services"]["stt"].update(pull_policy="always"),
            lambda value: value["services"]["stt"].update(build={"context": "."}),
            lambda value: value["services"]["stt"].update(
                image="speech-platform/stt:latest"
            ),
            lambda value: value["services"]["stt"]["labels"].update(
                {"com.speech-platform.image-id": "sha256:" + "f" * 64}
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(rendered)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validate_rendered_compose(changed, validated)

    def test_local_image_id_mode_rejects_missing_invalid_or_cross_mode_fields(self):
        evidence_path, _ = self._local_image_evidence()
        self.profile["runtime"].pop("build_evidence_sha256")
        self._write_profile()
        with self.assertRaisesRegex(ValueError, r"missing required field\(s\)"):
            self._validate(build_evidence_path=evidence_path, verify_files=False)

        evidence_path, _ = self._local_image_evidence()
        self.profile["runtime"]["image"] = "speech-platform/stt:latest"
        self._write_profile()
        with self.assertRaisesRegex(ValueError, r"unsupported field\(s\)"):
            self._validate(build_evidence_path=evidence_path, verify_files=False)

        self.profile["runtime"].pop("image")
        self.profile["runtime"]["identity_mode"] = "unknown"
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "identity_mode"):
            self._validate(verify_files=False)

        evidence_path, _ = self._local_image_evidence()
        self.profile["runtime"]["image_id"] = "speech-platform/stt:latest"
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "exact Docker sha256 image ID"):
            self._validate(build_evidence_path=evidence_path, verify_files=False)

        evidence_path, _ = self._local_image_evidence()
        self.profile["runtime"]["base_image"] = []
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "runtime.base_image"):
            self._validate(build_evidence_path=evidence_path, verify_files=False)

    def test_local_image_build_evidence_is_bound_to_profile_and_digest(self):
        evidence_path, evidence = self._local_image_evidence()
        validated = self._validate(
            build_evidence_path=evidence_path, verify_files=False
        )
        self.assertEqual(validated["identity_mode"], "local_image_id")

        evidence["source_commit"] = "f" * 40
        evidence_path.write_text(json.dumps(evidence, sort_keys=True))
        with self.assertRaisesRegex(ValueError, "evidence digest"):
            self._validate(build_evidence_path=evidence_path, verify_files=False)

        evidence_path, evidence = self._local_image_evidence()
        evidence["image"]["id"] = "sha256:" + "f" * 64
        evidence_path.write_text(json.dumps(evidence, sort_keys=True))
        self.profile["runtime"]["build_evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "conflicts with profile"):
            self._validate(build_evidence_path=evidence_path, verify_files=False)

    def test_local_image_build_evidence_rejects_provenance_mismatches(self):
        mutations = (
            ("source", lambda value: value.update(source_commit="f" * 40)),
            (
                "lock",
                lambda value: value.update(dependency_lock_sha256="0" * 64),
            ),
            (
                "base",
                lambda value: value["base"].update(
                    platform_manifest_digest="sha256:" + "0" * 64
                ),
            ),
            (
                "label",
                lambda value: value["image"]["labels"].update(
                    {"com.speech-platform.source-revision": "f" * 40}
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(provenance=name):
                evidence_path, evidence = self._local_image_evidence()
                mutate(evidence)
                evidence_path.write_text(json.dumps(evidence, sort_keys=True))
                self.profile["runtime"]["build_evidence_sha256"] = hashlib.sha256(
                    evidence_path.read_bytes()
                ).hexdigest()
                self._write_profile()
                with self.assertRaisesRegex(ValueError, "conflicts with profile"):
                    self._validate(
                        build_evidence_path=evidence_path, verify_files=False
                    )

    def test_local_image_id_configuration_change_changes_configuration_digest(self):
        evidence_path, _ = self._local_image_evidence()
        before = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            build_evidence_path=evidence_path,
            image_store_evidence_path=self.image_store_evidence_path,
        )
        self.profile["runtime"]["image_id"] = "sha256:" + "5" * 64
        self._write_profile()
        after = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            build_evidence_path=evidence_path,
            image_store_evidence_path=self.image_store_evidence_path,
        )
        self.assertNotEqual(before, after)

    def test_containerd_manifest_identity_is_distinct_from_config_digest(self):
        build_path, _ = self._containerd_image_evidence()
        validated = self._validate(build_evidence_path=build_path, verify_files=False)
        runtime = self.profile["runtime"]
        identity = runtime["artifact_identity"]
        self.assertEqual(validated["image_id"], identity["manifest_digest"])
        self.assertEqual(identity["manifest_config_digest"], identity["config_digest"])
        self.assertNotEqual(runtime["image_id"], identity["config_digest"])

        inspection = [
            {
                "Id": runtime["image_id"],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "User": "65532:65532",
                    "Entrypoint": ["python", "-m"],
                    "Labels": {
                        "org.opencontainers.image.revision": runtime["source_revision"],
                        "com.speech-platform.source-revision": runtime[
                            "source_revision"
                        ],
                        "com.speech-platform.image-role": "stt-worker",
                        "com.speech-platform.base-image": runtime["base_image"],
                        "com.speech-platform.cuda-lock-sha256": runtime[
                            "cuda_lock_sha256"
                        ],
                    },
                },
            }
        ]
        validate_local_image_inspection(runtime, inspection)

    def test_local_artifact_identity_rejects_wrong_content_relations(self):
        self._containerd_image_evidence()
        evidence_path = self.image_store_evidence_path
        runtime = self.profile["runtime"]
        original = json.loads(evidence_path.read_text())
        mutations = (
            ("config_digest", "sha256:" + "1" * 64, "evidence conflicts"),
            ("manifest_digest", "sha256:" + "2" * 64, "evidence conflicts"),
            ("verified_layer_digests", ["sha256:" + "3" * 64], "evidence conflicts"),
            ("manifest_config_digest", "sha256:" + "4" * 64, "evidence conflicts"),
            (
                "raw_manifest_base64",
                base64.b64encode(b'{"not":"the approved manifest"}').decode("ascii"),
                "raw OCI manifest digest",
            ),
            (
                "raw_manifest_base64",
                base64.b64encode(b"[]").decode("ascii"),
                "raw OCI manifest evidence is invalid",
            ),
        )
        for key, value, message in mutations:
            with self.subTest(field=key):
                changed = copy.deepcopy(original)
                changed[key] = value
                path = self.root / f"changed-{key}.json"
                path.write_text(json.dumps(changed, sort_keys=True))
                runtime["image_store_evidence_sha256"] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                with self.assertRaisesRegex(ValueError, message):
                    validate_local_artifact_identity(
                        runtime, changed, path, self.image_archive_path
                    )

        missing = copy.deepcopy(original)
        missing.pop("raw_config_sha256")
        path = self.root / "missing-raw-config.json"
        path.write_text(json.dumps(missing, sort_keys=True))
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, r"missing required field\(s\)"):
            validate_local_artifact_identity(
                runtime, missing, path, self.image_archive_path
            )

        wrong_platform = copy.deepcopy(original)
        wrong_platform["platform"] = "linux/arm64"
        path = self.root / "wrong-platform.json"
        path.write_text(json.dumps(wrong_platform, sort_keys=True))
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "platform"):
            validate_local_artifact_identity(
                runtime, wrong_platform, path, self.image_archive_path
            )

        tampered_archive = self.root / "tampered-image.tar"
        tampered_archive.write_bytes(self.image_archive_path.read_bytes() + b"x")
        valid_evidence = json.loads(evidence_path.read_text())
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "archive SHA-256"):
            validate_local_artifact_identity(
                runtime, valid_evidence, evidence_path, tampered_archive
            )

    def test_containerd_config_descriptor_size_must_match_approved_archive(self):
        self._containerd_image_evidence()
        runtime = self.profile["runtime"]
        identity = runtime["artifact_identity"]
        evidence = json.loads(self.image_store_evidence_path.read_text())
        raw_manifest = base64.b64decode(evidence["raw_manifest_base64"])
        manifest = json.loads(raw_manifest)
        manifest["config"]["size"] += 1
        raw_manifest = json.dumps(
            manifest, sort_keys=True, separators=(",", ":")
        ).encode()
        manifest_digest = "sha256:" + hashlib.sha256(raw_manifest).hexdigest()
        identity["manifest_config_size_bytes"] = manifest["config"]["size"]
        identity["manifest_digest"] = manifest_digest
        runtime["image_id"] = manifest_digest
        evidence.update(identity)
        evidence["docker_image_id"] = manifest_digest
        evidence["raw_manifest_base64"] = base64.b64encode(raw_manifest).decode("ascii")
        self.image_store_evidence_path.write_text(json.dumps(evidence, sort_keys=True))
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            self.image_store_evidence_path.read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "configuration size"):
            validate_local_artifact_identity(
                runtime,
                evidence,
                self.image_store_evidence_path,
                self.image_archive_path,
            )

    def test_local_artifact_identity_rejects_ambiguity_and_unsupported_store(self):
        for change, message in (
            ({"matching_image_records": 2}, "ambiguous"),
            ({"identity_kind": "unrecognized_store"}, "unsupported"),
        ):
            self._containerd_image_evidence()
            evidence_path = self.image_store_evidence_path
            runtime = self.profile["runtime"]
            runtime["artifact_identity"].update(change)
            evidence = json.loads(evidence_path.read_text())
            evidence.update(change)
            path = self.root / "invalid-store-evidence.json"
            path.write_text(json.dumps(evidence, sort_keys=True))
            runtime["image_store_evidence_sha256"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(ValueError, message),
            ):
                validate_local_artifact_identity(
                    runtime, evidence, path, self.image_archive_path
                )

    def test_matching_labels_cannot_substitute_for_content_evidence(self):
        self._containerd_image_evidence()
        evidence_path = self.image_store_evidence_path
        runtime = self.profile["runtime"]
        inspection = [
            {
                "Id": runtime["image_id"],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "User": "65532:65532",
                    "Entrypoint": ["python", "-m"],
                    "Labels": {
                        "org.opencontainers.image.revision": runtime["source_revision"],
                        "com.speech-platform.source-revision": runtime[
                            "source_revision"
                        ],
                        "com.speech-platform.image-role": "stt-worker",
                        "com.speech-platform.base-image": runtime["base_image"],
                        "com.speech-platform.cuda-lock-sha256": runtime[
                            "cuda_lock_sha256"
                        ],
                    },
                },
            }
        ]
        validate_local_image_inspection(runtime, inspection)
        evidence = json.loads(evidence_path.read_text())
        evidence["raw_config_sha256"] = "sha256:" + "0" * 64
        evidence_path.write_text(json.dumps(evidence, sort_keys=True))
        with self.assertRaisesRegex(ValueError, "evidence digest"):
            validate_local_artifact_identity(
                runtime, evidence, evidence_path, self.image_archive_path
            )

    def test_local_image_preflight_checks_versions_and_docker_inspection_data(self):
        evidence_path, _ = self._local_image_evidence()
        self._validate(build_evidence_path=evidence_path, verify_files=False)
        runtime = self.profile["runtime"]
        validate_local_image_runtime_versions("29.7.2-ce", "5.6.0")
        for engine, compose in (("29.7.3-ce", "5.6.0"), ("29.7.2-ce", "5.6.1")):
            with self.subTest(engine=engine, compose=compose):
                with self.assertRaisesRegex(ValueError, "unsupported Docker"):
                    validate_local_image_runtime_versions(engine, compose)

        inspection = [
            {
                "Id": runtime["image_id"],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "User": "65532:65532",
                    "Entrypoint": ["python", "-m"],
                    "Labels": {
                        "org.opencontainers.image.revision": runtime["source_revision"],
                        "com.speech-platform.source-revision": runtime[
                            "source_revision"
                        ],
                        "com.speech-platform.image-role": "stt-worker",
                        "com.speech-platform.base-image": runtime["base_image"],
                        "com.speech-platform.cuda-lock-sha256": runtime[
                            "cuda_lock_sha256"
                        ],
                    },
                },
            }
        ]
        validate_local_image_inspection(runtime, inspection)
        changed = copy.deepcopy(inspection)
        changed[0]["Config"]["User"] = "0:0"
        with self.assertRaisesRegex(ValueError, "identity or provenance mismatch"):
            validate_local_image_inspection(runtime, changed)
        changed_id = copy.deepcopy(inspection)
        changed_id[0]["Id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ValueError, "identity or provenance mismatch"):
            validate_local_image_inspection(runtime, changed_id)

    def test_container_prestart_verification_requires_exact_id_and_created_state(self):
        expected_container = "a" * 64
        expected = "sha256:" + "b" * 64
        inspection = [
            {
                "Id": expected_container,
                "Image": expected,
                "State": {"Status": "created", "Running": False},
            }
        ]
        validate_created_container_inspection(expected_container, expected, inspection)
        for changed in (
            [
                {
                    "Id": "c" * 64,
                    "Image": expected,
                    "State": inspection[0]["State"],
                }
            ],
            [
                {
                    "Id": expected_container,
                    "Image": "sha256:" + "d" * 64,
                    "State": inspection[0]["State"],
                }
            ],
            [
                {
                    "Id": expected_container,
                    "Image": expected,
                    "State": {"Status": "running", "Running": True},
                }
            ],
        ):
            with self.assertRaisesRegex(ValueError, "image identity or state mismatch"):
                validate_created_container_inspection(
                    expected_container, expected, changed
                )

    def test_docker_image_preflight_uses_only_read_only_identity_commands(self):
        evidence_path, _ = self._local_image_evidence()
        runtime = self.profile["runtime"]
        image_data = [
            {
                "Id": runtime["image_id"],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "User": "65532:65532",
                    "Entrypoint": ["python", "-m"],
                    "Labels": {
                        "org.opencontainers.image.revision": runtime["source_revision"],
                        "com.speech-platform.source-revision": runtime[
                            "source_revision"
                        ],
                        "com.speech-platform.image-role": "stt-worker",
                        "com.speech-platform.base-image": runtime["base_image"],
                        "com.speech-platform.cuda-lock-sha256": runtime[
                            "cuda_lock_sha256"
                        ],
                    },
                },
            }
        ]

        def run(args, **_kwargs):
            if args[:3] == ["docker", "info", "--format"]:
                return mock.Mock(returncode=0, stdout="29.7.2-ce\n")
            if args == ["docker", "compose", "version", "--short"]:
                return mock.Mock(returncode=0, stdout="5.6.0\n")
            if args == ["docker", "image", "inspect", runtime["image_id"]]:
                return mock.Mock(returncode=0, stdout=json.dumps(image_data))
            raise AssertionError(f"unexpected command: {args}")

        with mock.patch(
            "scripts.stt_deployment_profile.subprocess.run", side_effect=run
        ) as call:
            verify_local_image_with_docker(runtime)
        commands = [item.args[0] for item in call.call_args_list]
        self.assertEqual(len(commands), 3)
        self.assertTrue(
            all(
                "pull" not in command and "build" not in command for command in commands
            )
        )

        with self.assertRaisesRegex(ValueError, "full hexadecimal Docker ID"):
            verify_created_container_with_docker("short", runtime["image_id"])
        container_id = "c" * 64
        container_data = [
            {
                "Id": container_id,
                "Image": runtime["image_id"],
                "State": {"Status": "created", "Running": False},
            }
        ]
        with mock.patch(
            "scripts.stt_deployment_profile.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout=json.dumps(container_data)),
        ) as container_call:
            verify_created_container_with_docker(container_id, runtime["image_id"])
        self.assertEqual(
            container_call.call_args.args[0],
            ["docker", "container", "inspect", container_id],
        )
        self.assertTrue(evidence_path.is_file())

    def test_model_release_requires_digest_root_and_group_reader_policy(self):
        validated = self._validate()
        self.assertEqual(validated["release_root"].name, self.manifest_digest)
        for mode in (0o750, 0o2770, 0o2755, 0o3750):
            with self.subTest(mode=oct(mode)):
                self.release.chmod(mode)
                with self.assertRaises(ValueError):
                    self._validate()
        self.release.chmod(0o2750)

    def test_model_release_rejects_owner_mismatch(self):
        self.profile["artifact_access"]["artifact_owner_uid"] = os.getuid() + 1
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "ownership"):
            self._validate()

    def test_model_release_rejects_acl_when_present(self):
        with mock.patch(
            "scripts.stt_deployment_profile.os.getxattr", return_value=b"acl"
        ):
            with self.assertRaisesRegex(ValueError, "must not use POSIX ACLs"):
                self._validate()

    def test_permission_validation_does_not_mutate_release_or_expose_neighbor(self):
        neighbor = self.root / "neighbor-release"
        neighbor.mkdir(mode=0o700)
        marker = neighbor / "private-marker"
        marker.write_bytes(b"not part of the selected release")

        def snapshot():
            return {
                path.relative_to(self.root): (
                    path.stat().st_uid,
                    path.stat().st_gid,
                    path.stat().st_mode,
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.is_file()
                    else None,
                )
                for path in self.release.rglob("*")
            }

        before = snapshot()
        validated = self._validate()
        self.assertEqual(before, snapshot())
        rendered = self._compose(validated)
        model_mounts = [
            mount
            for mount in rendered["services"]["stt"]["volumes"]
            if mount["target"] == "/models"
        ]
        self.assertEqual(len(model_mounts), 1)
        self.assertEqual(Path(model_mounts[0]["source"]), self.release)
        self.assertEqual(marker.read_bytes(), b"not part of the selected release")

    def test_previous_digest_named_release_can_be_selected_independently(self):
        prior_root = self.root / "prior-release"
        prior_artifact = prior_root / "artifact"
        prior_artifact.mkdir(parents=True)
        payload = b"prior immutable model bytes"
        (prior_artifact / "model.bin").write_bytes(payload)
        revision = "b" * 40
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
        prior_digest = canonical_manifest_digest(manifest)
        prior_release = self.root / prior_digest
        prior_root.rename(prior_release)
        (prior_release / "manifest.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False)
        )
        for path in (prior_release, prior_release / "artifact"):
            path.chmod(0o2750)
        (prior_release / "manifest.yaml").chmod(0o640)
        (prior_release / "artifact" / "model.bin").chmod(0o640)

        prior_app = yaml.safe_load(self.application_path.read_text())
        prior_app["models"][0]["immutable_revision"] = revision
        prior_app["models"][0]["artifacts"]["faster-whisper"]["manifest_sha256"] = (
            prior_digest
        )
        prior_app_path = self.root / "prior-application.yaml"
        self._write_yaml(prior_app_path, prior_app)
        prior_profile = copy.deepcopy(self.profile)
        prior_profile["model"].update(
            {
                "revision": revision,
                "manifest_sha256": prior_digest,
                "host_release_root": str(prior_release),
            }
        )
        prior_profile_path = self.root / "prior-profile.yaml"
        self._write_yaml(prior_profile_path, prior_profile)

        selected = load_and_validate(
            prior_profile_path,
            prior_app_path,
            self.deployment_path,
            self.worker_path,
        )
        self.assertEqual(selected["release_root"], prior_release)
        self.assertEqual(selected["model"]["manifest_sha256"], prior_digest)
        self.assertEqual(self._validate()["release_root"], self.release)

    def test_private_configuration_inputs_reject_examples_and_external_paths(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        config = private / "deployment.yaml"
        config.write_text("schema_version: 1\n")
        config.chmod(0o600)
        require_private_config_paths([config], repository_root=self.root)
        example = private / "deployment.example.yaml"
        example.write_text("schema_version: 1\n")
        example.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "explicit private file"):
            require_private_config_paths([example], repository_root=self.root)
        with self.assertRaisesRegex(ValueError, "under private"):
            require_private_config_paths([self.profile_path], repository_root=self.root)
        config.chmod(0o640)
        with self.assertRaisesRegex(ValueError, "permissions are too broad"):
            require_private_config_paths([config], repository_root=self.root)
        config_gid = config.stat().st_gid
        require_private_config_paths(
            [config], repository_root=self.root, group_read_gid=config_gid
        )
        with self.assertRaisesRegex(ValueError, "configured reader group"):
            require_private_config_paths(
                [config], repository_root=self.root, group_read_gid=config_gid + 1
            )
        config.chmod(0o660)
        with self.assertRaisesRegex(ValueError, "configured reader group"):
            require_private_config_paths(
                [config], repository_root=self.root, group_read_gid=config_gid
            )

    def test_profile_v1_keeps_the_legacy_loopback_port_default(self):
        legacy = copy.deepcopy(self.profile)
        legacy["schema_version"] = 1
        legacy.pop("gateway")
        legacy_path = self.root / "legacy-profile.yaml"
        self._write_yaml(legacy_path, legacy)

        validated = load_and_validate(
            legacy_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            verify_files=False,
        )

        self.assertEqual(
            validated["profile"]["gateway"],
            {"host_port": 8080, "listen_port": 8080},
        )

    def test_private_configuration_rejects_broad_directory_and_symlink(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        nested = private / "deployment"
        nested.mkdir(mode=0o700)
        config = nested / "profile.yaml"
        config.write_text("schema_version: 1\n")
        config.chmod(0o600)
        nested.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "directory permissions are too broad"):
            require_private_config_paths([config], repository_root=self.root)
        nested.chmod(0o700)
        link = private / "profile-link.yaml"
        link.symlink_to(config)
        with self.assertRaisesRegex(ValueError, "must not be symlinks"):
            require_private_config_paths([link], repository_root=self.root)

    def test_private_configuration_rejects_acl_on_input_or_parent(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        config = private / "deployment.yaml"
        config.write_text("schema_version: 1\\n")
        config.chmod(0o600)

        def acl_on_file(path, attribute, *, follow_symlinks):
            if Path(path) == config:
                return b"acl"
            raise OSError(errno.ENODATA, "no ACL")

        with mock.patch(
            "scripts.stt_deployment_profile.os.getxattr", side_effect=acl_on_file
        ):
            with self.assertRaisesRegex(ValueError, "must not use POSIX ACLs"):
                require_private_config_paths([config], repository_root=self.root)

        with mock.patch(
            "scripts.stt_deployment_profile.os.getxattr", return_value=b"acl"
        ):
            with self.assertRaisesRegex(ValueError, "must not use POSIX ACLs"):
                require_private_config_paths([config], repository_root=self.root)

    def test_configuration_set_identity_changes_when_any_input_changes(self):
        before = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
        )
        self.application_path.write_text(self.application_path.read_text() + "\n")
        after = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
        )
        self.assertNotEqual(before, after)

    def test_configuration_set_digest_is_deterministic_and_covers_every_input(self):
        source_paths = {
            "profile": self.profile_path,
            "application": self.application_path,
            "deployment": self.deployment_path,
            "worker": self.worker_path,
            "compose_base": Path("deployments/compose/compose.yaml").resolve(),
            "compose_cuda": Path("deployments/compose/compose.stt-cuda.yaml").resolve(),
        }
        copies = {}
        for role, source in source_paths.items():
            copy_path = self.root / f"{role}.yaml"
            copy_path.write_bytes(source.read_bytes())
            copies[role] = copy_path

        def digest():
            return configuration_set_sha256(
                copies["profile"],
                copies["application"],
                copies["deployment"],
                copies["worker"],
                compose_base_path=copies["compose_base"],
                compose_cuda_path=copies["compose_cuda"],
            )

        initial = digest()
        self.assertEqual(initial, digest())
        for role, path in copies.items():
            with self.subTest(role=role):
                original = path.read_bytes()
                path.write_bytes(original + b"\\n# reviewed content change\\n")
                self.assertNotEqual(initial, digest())
                path.write_bytes(original)

    def test_configuration_set_identity_includes_file_paths_and_compose_inputs(self):
        app_copy = self.root / "application-copy.yaml"
        app_copy.write_bytes(self.application_path.read_bytes())
        relocated = configuration_set_sha256(
            self.profile_path,
            app_copy,
            self.deployment_path,
            self.worker_path,
        )
        original = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
        )
        self.assertNotEqual(original, relocated)

        compose_copy = self.root / "compose-copy.yaml"
        compose_copy.write_bytes(Path("deployments/compose/compose.yaml").read_bytes())
        copied_identity = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            compose_base_path=compose_copy,
        )
        self.assertNotEqual(original, copied_identity)
        compose_copy.write_text(compose_copy.read_text() + "\n# reviewed change\n")
        changed_compose_identity = configuration_set_sha256(
            self.profile_path,
            self.application_path,
            self.deployment_path,
            self.worker_path,
            compose_base_path=compose_copy,
        )
        self.assertNotEqual(copied_identity, changed_compose_identity)

    def test_generated_env_rejects_output_outside_private_and_symlinks(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "under private"):
            write_env_file(
                self.root / "outside.env", {"A": "b"}, repository_root=self.root
            )
        target = private / "target.env"
        target.write_text("existing\n")
        link = private / "linked.env"
        link.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            write_env_file(link, {"A": "b"}, repository_root=self.root)

    def test_generated_env_rejects_broad_or_symlinked_parent(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        broad = private / "broad"
        broad.mkdir(mode=0o755)
        with self.assertRaisesRegex(ValueError, "permissions are too broad"):
            write_env_file(broad / "compose.env", {"A": "b"}, repository_root=self.root)
        broad.chmod(0o700)
        alias = private / "alias"
        alias.symlink_to(broad, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "must not be symlinks"):
            write_env_file(alias / "compose.env", {"A": "b"}, repository_root=self.root)

    def test_generated_env_rejects_acl_on_private_output_parent(self):
        private = self.root / "private"
        private.mkdir(mode=0o700)
        with mock.patch(
            "scripts.stt_deployment_profile.os.getxattr", return_value=b"acl"
        ):
            with self.assertRaisesRegex(ValueError, "must not use POSIX ACLs"):
                write_env_file(
                    private / "compose.env", {"A": "b"}, repository_root=self.root
                )

    def test_rendered_compose_matches_profile_and_rejects_unsafe_overrides(self):
        validated = self._validate()
        rendered = self._compose(validated)
        validate_rendered_compose(rendered, validated)
        for label_value in rendered["services"]["stt"]["labels"].values():
            self.assertNotIn("/private/", label_value)
        mutations = (
            (
                "gateway must attach to the publication network",
                lambda value: value["services"]["gateway"]["networks"].pop(
                    "gateway_publish"
                ),
            ),
            (
                "unexpected service attachment",
                lambda value: value["services"]["tts"]["networks"].update(
                    stt_private=None
                ),
            ),
            (
                "unexpected network definition",
                lambda value: value["networks"].update(untrusted={}),
            ),
            (
                "missing publication network definition",
                lambda value: value["networks"].pop("gateway_publish"),
            ),
            (
                "internal publication network",
                lambda value: value["networks"]["gateway_publish"].update(
                    internal=True
                ),
            ),
            (
                "enabled publication masquerading",
                lambda value: value["networks"]["gateway_publish"][
                    "driver_opts"
                ].update({"com.docker.network.bridge.enable_ip_masquerade": "true"}),
            ),
            (
                "non-loopback Gateway publication",
                lambda value: value["services"]["gateway"]["ports"][0].update(
                    host_ip="0.0.0.0"
                ),
            ),
            (
                "published TTS port",
                lambda value: value["services"]["tts"].update(ports=[{"target": 8082}]),
            ),
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
            (
                "artifact group identity",
                lambda value: value["services"]["stt"].update(
                    group_add=["not-the-reader-gid"]
                ),
            ),
            (
                "TTS config reader group",
                lambda value: value["services"]["tts"].update(group_add=[]),
            ),
            (
                "configuration set identity",
                lambda value: value["services"]["stt"]["labels"].update(
                    {"com.speech-platform.configuration-set-sha256": "0" * 64}
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
            ("host GPU", "device", "host_physical_index", -1, "non-negative"),
            (
                "container GPU index",
                "device",
                "container_cuda_index",
                1,
                "single-device CUDA container index",
            ),
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

    def test_worker_and_model_reader_identity_fail_closed(self):
        cases = (
            ("service_uid", 65531, "non-root image user"),
            ("service_gid", 65531, "non-root image user"),
            ("supplementary_read_gid", 65532, "explicit non-root group"),
            ("artifact_owner_uid", 65532, "distinct from worker"),
        )
        for key, value, error in cases:
            with self.subTest(key=key):
                original = self.profile["artifact_access"][key]
                self.profile["artifact_access"][key] = value
                self._write_profile()
                with self.assertRaisesRegex(ValueError, error):
                    self._validate(verify_files=False)
                self.profile["artifact_access"][key] = original

    def test_worker_cuda_selection_must_match_deployment_config(self):
        deployment = yaml.safe_load(self.deployment_path.read_text())
        deployment["device_access"]["cuda_device_index"] = 1
        self._write_yaml(self.deployment_path, deployment)
        with self.assertRaisesRegex(ValueError, "worker CUDA index"):
            self._validate(verify_files=False)

    def test_resource_bounds_and_missing_model_identity_fail_closed(self):
        cases = (
            ("cpu_limit", 0, "outside the supported range"),
            ("memory_limit_bytes", 512 * 1024**2, "1..64 GiB"),
            ("pids_limit", 15, "16..4096"),
        )
        for key, value, error in cases:
            with self.subTest(resource=key):
                original = self.profile["resources"][key]
                self.profile["resources"][key] = value
                self._write_profile()
                with self.assertRaisesRegex(ValueError, error):
                    self._validate(verify_files=False)
                self.profile["resources"][key] = original
                self._write_profile()

        manifest_identity = self.profile["model"]["manifest_sha256"]
        self.profile["model"]["manifest_sha256"] = None
        self._write_profile()
        with self.assertRaisesRegex(ValueError, "SHA-256 digest"):
            self._validate(verify_files=False)
        self.profile["model"]["manifest_sha256"] = manifest_identity
        self._write_profile()

    def test_review_attestation_must_be_explicit_boolean_true(self):
        for value in (False, "true", 1, None):
            with self.subTest(value=value):
                self.profile["resources"]["limits_reviewed"] = value
                self._write_profile()
                with self.assertRaisesRegex(ValueError, "require operator review"):
                    self._validate(verify_files=False)
        self.profile["resources"]["limits_reviewed"] = True
        self._write_profile()

    def test_artifact_permissions_and_integrity_fail_closed(self):
        model = self.release / "artifact" / "model.bin"
        model.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "insufficient or too broad"):
            self._validate()
        model.chmod(0o640)
        model.write_bytes(b"modified")
        with self.assertRaises(SpeechFailure):
            self._validate()

    def test_manifest_permissions_symlinks_and_special_files_fail_closed(self):
        manifest = self.release / "manifest.yaml"
        manifest.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "insufficient or too broad"):
            self._validate()
        manifest.chmod(0o640)

        unexpected = self.release / "artifact" / "unexpected-link"
        unexpected.symlink_to(self.release / "manifest.yaml")
        with self.assertRaisesRegex(ValueError, "ownership or symlink"):
            self._validate()
        unexpected.unlink()

        fifo = self.release / "artifact" / "unexpected-fifo"
        os.mkfifo(fifo, 0o640)
        with self.assertRaisesRegex(ValueError, "non-regular file"):
            self._validate()
        fifo.unlink()

    def test_unrelated_historical_evidence_is_not_modified_or_required(self):
        evidence = self.release / "historical-evidence"
        evidence.mkdir(mode=0o700)
        evidence_file = evidence / "record.txt"
        evidence_file.write_text("preserve this record")
        evidence_file.chmod(0o600)
        before = (evidence_file.read_bytes(), evidence_file.stat().st_mode)

        self._validate()

        self.assertEqual(
            (evidence_file.read_bytes(), evidence_file.stat().st_mode), before
        )

    def test_missing_artifact_release_is_not_accepted(self):
        self.profile["model"]["host_release_root"] = str(self.root / "absent")
        self._write_profile()
        with self.assertRaises(ValueError):
            self._validate()

    def test_untraversable_model_release_parent_fails_closed(self):
        self.root.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "parent is not traversable"):
            self._validate()

    def test_host_preflight_requires_configured_gpu_and_free_vram(self):
        validated = self._validate()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            preflight_host_gpu(
                validated,
                run=lambda *args, **kwargs: type(
                    "Result",
                    (),
                    {"stdout": "0, GPU-0123456789abcdef, 1\n"},
                )(),
            )
        self.assertIn("PASS:", output.getvalue())

        with self.assertRaisesRegex(ValueError, "identity does not match"):
            preflight_host_gpu(
                validated,
                run=lambda *args, **kwargs: type(
                    "Result", (), {"stdout": "0, GPU-wrong, 100\n"}
                )(),
            )

        with self.assertRaisesRegex(ValueError, "below the configured"):
            preflight_host_gpu(
                validated,
                run=lambda *args, **kwargs: type(
                    "Result",
                    (),
                    {"stdout": "0, GPU-0123456789abcdef, 0\n"},
                )(),
            )

    def test_host_physical_gpu_index_is_profile_configured(self):
        self.profile["device"]["host_physical_index"] = 1
        self._write_profile()
        validated = self._validate()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            preflight_host_gpu(
                validated,
                run=lambda *args, **kwargs: type(
                    "Result",
                    (),
                    {"stdout": "0, GPU-other, 0\n1, GPU-0123456789abcdef, 1\n"},
                )(),
            )
        self.assertIn("PASS:", output.getvalue())


if __name__ == "__main__":
    unittest.main()
