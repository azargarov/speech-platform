from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.model_artifacts import ModelProvisionError
from scripts.stt_deployment import (
    _ensure_selected_models,
    _ensure_service_image,
    _install_service_command,
    _wait_service_readiness,
    _service_matches,
    run_deployment,
)


class ServiceScopedDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.project = "isolated-services"
        self.release = {
            "release_version": "v-test",
            "git_source_revision": "a" * 40,
            "services": {
                "gateway": self._entry("gateway", []),
                "stt": self._entry("stt", []),
                "tts": self._entry("tts", ["gateway", "stt"]),
            },
        }
        self.profile = {
            "project_name": self.project,
            "config_reader_gid": 988,
            "gateway": {
                "host_port": 18080,
                "memory_limit": "128m",
                "cpu_limit": 1.0,
                "pids_limit": 128,
            },
            "tts": {"memory_limit": "256m", "cpu_limit": 1.0, "pids_limit": 128},
            "readiness": {
                "timeout_seconds": 5,
                "poll_interval_seconds": 1,
                "probe_timeout_seconds": 1,
            },
        }
        self.gateway = {"listen_port": 8080}
        self.tts = {"listen_port": 8082}
        self.paths = (
            Path("/private/gateway.yaml"),
            Path("/private/tts.yaml"),
        )

    @staticmethod
    def _entry(name, dependencies):
        digest = {"gateway": "1", "stt": "2", "tts": "3"}[name]
        return {
            "image": f"ghcr.io/example/{name}@sha256:{digest * 64}",
            "platform": "linux/amd64",
            "runtime_variant": {
                "gateway": "foundation",
                "stt": "cuda",
                "tts": "health-only",
            }[name],
            "dependencies": dependencies,
            "required_model_artifacts": (
                [{"id": "test-model"}] if name == "stt" else []
            ),
        }

    def _container(self, name):
        entry = self.release["services"][name]
        expected = self._rendered()["services"][name]
        host_config = {
            "ReadonlyRootfs": expected["read_only"],
            "Memory": int(expected["mem_limit"]),
            "NanoCpus": int(round(float(expected["cpus"]) * 1_000_000_000)),
            "PidsLimit": expected["pids_limit"],
            "GroupAdd": expected.get("group_add", []),
            "CapDrop": expected["cap_drop"],
            "SecurityOpt": expected["security_opt"],
            "PortBindings": {
                f"{port['target']}/tcp": [
                    {"HostIp": port["host_ip"], "HostPort": port["published"]}
                ]
                for port in expected.get("ports", [])
            },
        }
        if name == "stt":
            device = expected["deploy"]["resources"]["reservations"]["devices"][0]
            host_config["DeviceRequests"] = [{"DeviceIDs": device["device_ids"]}]
        return {
            "Id": f"{name}-id",
            "Config": {
                "Image": entry["image"],
                "User": expected["user"],
                "Cmd": expected["command"],
                "Labels": {
                    "com.docker.compose.project": self.project,
                    "com.docker.compose.service": name,
                    "com.speech-platform.deployment-identity-sha256": f"identity-{name}",
                    **{
                        key: value
                        for key, value in expected.get("labels", {}).items()
                        if key != "com.speech-platform.deployment-identity-sha256"
                    },
                },
            },
            "HostConfig": host_config,
            "NetworkSettings": {
                "Networks": {
                    f"{self.project}_{network}": {}
                    for network in expected.get("networks", {})
                },
                "Ports": {
                    f"{port['target']}/tcp": [
                        {"HostIp": port["host_ip"], "HostPort": port["published"]}
                    ]
                    for port in expected.get("ports", [])
                },
            },
            "Mounts": [
                {
                    "Source": volume["source"],
                    "Destination": volume["target"],
                    "RW": not volume["read_only"],
                }
                for volume in expected["volumes"]
            ],
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
        }

    def _rendered(self):
        return {
            "services": {
                name: {
                    "image": entry["image"],
                    "user": "65532:65532",
                    "command": ["--config", f"/config/{name}.yaml"],
                    "read_only": True,
                    "mem_limit": str(
                        {"gateway": 128, "stt": 128, "tts": 256}[name] * 1024 * 1024
                    ),
                    "cpus": 1.0,
                    "pids_limit": 128,
                    "group_add": ["988"],
                    "cap_drop": ["ALL"],
                    "security_opt": ["no-new-privileges:true"],
                    "volumes": [
                        {
                            "source": f"/private/{name}.yaml",
                            "target": f"/config/{name}.yaml",
                            "read_only": True,
                        }
                    ],
                    "ports": (
                        [
                            {
                                "target": 8080,
                                "host_ip": "127.0.0.1",
                                "published": "18080",
                                "protocol": "tcp",
                            }
                        ]
                        if name == "gateway"
                        else []
                    ),
                    "networks": {
                        "gateway": {
                            "gateway_publish": None,
                            "stt_private": None,
                            "tts_private": None,
                        },
                        "stt": {"stt_private": None},
                        "tts": {"tts_private": None},
                    }[name],
                    **(
                        {
                            "deploy": {
                                "resources": {
                                    "reservations": {"devices": [{"device_ids": ["0"]}]}
                                }
                            }
                        }
                        if name == "stt"
                        else {}
                    ),
                    "labels": {
                        "com.speech-platform.deployment-identity-sha256": f"identity-{name}",
                        **(
                            {
                                "com.speech-platform.configuration-sha256": f"config-{name}"
                            }
                            if name in {"gateway", "tts"}
                            else {}
                        ),
                    },
                }
                for name, entry in self.release["services"].items()
            }
        }

    def _run_install(self, service, enabled, existing=None):
        commands = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            stt_configs = []
            for name in (
                "profile.yaml",
                "application.yaml",
                "deployment.yaml",
                "worker.yaml",
            ):
                path = root / name
                path.write_text("fixture\n")
                stt_configs.append(str(path))
            validated = {
                "profile": {
                    "project_name": self.project,
                    "gateway": {"host_port": 18080, "listen_port": 8080},
                },
                "artifact_access": {
                    "supplementary_read_gid": 988,
                    "artifact_owner_uid": 0,
                },
                "deployment": SimpleNamespace(minimum_free_gpu_bytes_before_load=1),
                "release_root": root / ("f" * 64),
                "healthcheck": {
                    "start_period_seconds": 30,
                    "interval_seconds": 2,
                    "retries": 3,
                    "timeout_seconds": 2,
                },
            }

            def run(command, **kwargs):
                commands.append((command, kwargs))
                return ""

            stack = [
                patch("scripts.stt_deployment.load_release", return_value=self.release),
                patch(
                    "scripts.stt_deployment._load_selected_configs",
                    return_value=(self.profile, self.gateway, self.tts, *self.paths),
                ),
                patch("scripts.stt_deployment.require_private_config_paths"),
                patch("scripts.stt_deployment.require_container_config_access"),
                patch(
                    "scripts.stt_deployment.load_and_validate", return_value=validated
                ),
                patch("scripts.stt_deployment._require_release_match"),
                patch("scripts.stt_deployment._compose_environment", return_value={}),
                patch(
                    "scripts.stt_deployment._render_selected",
                    return_value=self._rendered(),
                ),
                patch(
                    "scripts.stt_deployment._ensure_service_image",
                    return_value="verified",
                ),
                patch(
                    "scripts.stt_deployment._ensure_selected_models", return_value=[]
                ),
                patch(
                    "scripts.stt_deployment._project_services",
                    return_value=existing or {},
                ),
                patch("scripts.stt_deployment._wait_service_readiness"),
            ]
            with ExitStackForTest(stack):
                result = run_deployment(
                    "install",
                    service=service,
                    enabled_services=enabled,
                    services_profile_path="private/services.yaml",
                    gateway_config_path=str(self.paths[0]),
                    tts_config_path=str(self.paths[1]),
                    profile_path=stt_configs[0],
                    application_config=stt_configs[1],
                    deployment_config=stt_configs[2],
                    worker_config=stt_configs[3],
                    release_path="release.yaml",
                    env_file="unused.env",
                    run=run,
                    gpu_probe=lambda *_: {
                        "identity_matches": True,
                        "free_bytes": 10,
                        "threshold_bytes": 1,
                        "free_mib": 10,
                    },
                    service_probe=lambda *_args, **_kwargs: True,
                )
        return result, [command for command, _kwargs in commands]

    def test_fresh_gateway_only_install_is_scoped(self):
        result, commands = self._run_install("gateway", ["gateway", "stt", "tts"])
        self.assertEqual(result, 0)
        up = [command for command in commands if "up" in command]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][-1], "gateway")
        self.assertIn("--no-deps", up[0])
        self.assertIn("--project-name", up[0])

    def test_fresh_tts_only_install_includes_declared_dependencies(self):
        result, commands = self._run_install("tts", ["gateway", "stt", "tts"])
        self.assertEqual(result, 0)
        up = [command[-1] for command in commands if "up" in command]
        self.assertEqual(up, ["gateway", "stt", "tts"])

    def test_fresh_tts_only_install_without_dependencies_is_service_scoped(self):
        self.release["services"]["tts"]["dependencies"] = []
        result, commands = self._run_install("tts", ["gateway", "stt", "tts"])
        self.assertEqual(result, 0)
        up = [command[-1] for command in commands if "up" in command]
        self.assertEqual(up, ["tts"])

    def test_default_selection_installs_all_enabled_in_dependency_order(self):
        result, commands = self._run_install(None, ["gateway", "stt", "tts"])
        self.assertEqual(result, 0)
        up = [command[-1] for command in commands if "up" in command]
        self.assertEqual(up, ["gateway", "stt", "tts"])

    def test_selective_addition_preserves_healthy_dependency_and_unrelated_stt(self):
        gateway = self._container("gateway")
        stt = self._container("stt")
        result, commands = self._run_install(
            "tts",
            ["gateway", "stt", "tts"],
            {"gateway": gateway, "stt": stt},
        )
        self.assertEqual(result, 0)
        up = [command[-1] for command in commands if "up" in command]
        self.assertEqual(up, ["tts"])

    def test_changed_selected_service_is_recreated_without_its_healthy_dependency(self):
        gateway = self._container("gateway")
        stt = self._container("stt")
        tts = self._container("tts")
        tts["Config"]["Labels"]["com.speech-platform.configuration-sha256"] = (
            "previous-config"
        )
        result, commands = self._run_install(
            "tts",
            ["gateway", "stt", "tts"],
            {"gateway": gateway, "stt": stt, "tts": tts},
        )
        self.assertEqual(result, 0)
        up = [command for command in commands if "up" in command]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][-1], "tts")
        self.assertIn("--force-recreate", up[0])

    def test_tts_runtime_mount_mismatch_forces_replacement(self):
        tts = self._container("tts")
        tts["Mounts"][0]["Source"] = "/private/other-tts.yaml"
        _, commands = self._run_install(
            "tts",
            ["gateway", "stt", "tts"],
            {
                "gateway": self._container("gateway"),
                "stt": self._container("stt"),
                "tts": tts,
            },
        )
        up = [command for command in commands if "up" in command]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][-1], "tts")
        self.assertIn("--force-recreate", up[0])

    def test_existing_healthy_selected_services_are_left_unchanged(self):
        result, commands = self._run_install(
            None,
            ["gateway", "stt", "tts"],
            {name: self._container(name) for name in ("gateway", "stt", "tts")},
        )
        self.assertEqual(result, 0)
        self.assertFalse(any("up" in command for command in commands))

    def test_existing_gateway_with_old_private_only_network_is_replaced(self):
        gateway = self._container("gateway")
        gateway["NetworkSettings"]["Networks"] = {f"{self.project}_stt_private": {}}
        self.assertFalse(
            _service_matches(gateway, "gateway", self._rendered(), self.project)
        )

    def test_gateway_config_label_mismatch_is_not_ignored(self):
        gateway = self._container("gateway")
        gateway["Config"]["Labels"]["com.speech-platform.configuration-sha256"] = (
            "different-config"
        )
        self.assertFalse(
            _service_matches(gateway, "gateway", self._rendered(), self.project)
        )

    def test_gateway_legacy_deployment_hash_does_not_override_exact_runtime(self):
        gateway = self._container("gateway")
        gateway["Config"]["Labels"][
            "com.speech-platform.deployment-identity-sha256"
        ] = "legacy-compose-hash"
        self.assertTrue(
            _service_matches(gateway, "gateway", self._rendered(), self.project)
        )

    def test_container_install_command_never_targets_other_projects_or_dependencies(
        self,
    ):
        command = _install_service_command(
            self.project, "tts", replace=False, include_stt=False
        )
        self.assertEqual(command[command.index("--project-name") + 1], self.project)
        self.assertEqual(command[-1], "tts")
        self.assertIn("--no-deps", command)
        self.assertIn("--pull", command)
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertNotIn("--remove-orphans", command)

    def test_existing_project_inspection_is_scoped_to_exact_project_label(self):
        from scripts.stt_deployment import _project_services

        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            return ""

        self.assertEqual(_project_services(self.project, run=run), {})
        self.assertEqual(commands[0][0:2], ["docker", "ps"])
        self.assertIn(f"label=com.docker.compose.project={self.project}", commands[0])
        self.assertEqual(commands[1][0:3], ["docker", "network", "ls"])
        self.assertIn(f"label=com.docker.compose.project={self.project}", commands[1])

    def test_missing_image_is_pulled_by_immutable_reference_then_verified(self):
        image = self.release["services"]["gateway"]["image"]
        source = self.release["git_source_revision"]
        inspected = {
            "Id": "sha256:" + "b" * 64,
            "RepoDigests": [image],
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "User": "65532",
                "Labels": {
                    "org.opencontainers.image.revision": source,
                    "com.speech-platform.service": "gateway",
                    "com.speech-platform.runtime-variant": "foundation",
                    "com.speech-platform.service-role": "gateway",
                },
            },
        }
        commands = []
        attempts = iter((False, True))

        def run(command, **_kwargs):
            commands.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                if not next(attempts):
                    raise subprocess.CalledProcessError(1, command)
                return json.dumps([inspected])
            return ""

        self.assertEqual(
            _ensure_service_image(
                "gateway",
                self.release["services"]["gateway"],
                action="install",
                stt_validated=None,
                source_revision=source,
                run=run,
            ),
            "verified",
        )
        self.assertEqual(
            commands[1],
            ["docker", "image", "pull", "--platform", "linux/amd64", image],
        )

    def test_image_provenance_mismatch_blocks_install(self):
        image = self.release["services"]["gateway"]["image"]
        inspected = {
            "RepoDigests": [image],
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {"User": "65532", "Labels": {}},
        }
        with self.assertRaisesRegex(ValueError, "provenance mismatch"):
            _ensure_service_image(
                "gateway",
                self.release["services"]["gateway"],
                action="install",
                stt_validated=None,
                source_revision=self.release["git_source_revision"],
                run=lambda *_args, **_kwargs: json.dumps([inspected]),
            )

    def test_missing_model_is_staged_with_profile_access_policy(self):
        model = self.release["services"]["stt"]["required_model_artifacts"][0]
        release = {"services": {"stt": self.release["services"]["stt"]}}
        release_root = Path("/private/models") / ("f" * 64)
        validated = {
            "release_root": release_root,
            "artifact_access": {
                "artifact_owner_uid": 0,
                "supplementary_read_gid": 988,
            },
        }
        with (
            patch(
                "scripts.stt_deployment.model_directory", return_value=Path("/missing")
            ),
            patch(
                "scripts.stt_deployment.provision_models",
                return_value=[
                    SimpleNamespace(artifact_id=model["id"], status="installed")
                ],
            ) as provision,
            patch("scripts.stt_deployment.check_models", return_value=[object()]),
        ):
            staged = _ensure_selected_models(release, validated, action="install")
        self.assertEqual(staged, [model["id"]])
        self.assertEqual(provision.call_args.kwargs["directory_mode"], 0o2750)
        self.assertEqual(provision.call_args.kwargs["file_mode"], 0o640)
        self.assertEqual(provision.call_args.kwargs["expected_group_gid"], 988)

    def test_existing_corrupt_model_is_not_replaced(self):
        release = {"services": {"stt": self.release["services"]["stt"]}}
        validated = {
            "release_root": Path("/private/models") / ("f" * 64),
            "artifact_access": {"artifact_owner_uid": 0, "supplementary_read_gid": 988},
        }
        with tempfile.TemporaryDirectory() as temp:
            existing = Path(temp) / "model"
            existing.mkdir()
            with (
                patch("scripts.stt_deployment.model_directory", return_value=existing),
                patch(
                    "scripts.stt_deployment.check_models",
                    side_effect=ModelProvisionError("checksum mismatch"),
                ),
                patch("scripts.stt_deployment.provision_models") as provision,
            ):
                with self.assertRaisesRegex(ModelProvisionError, "checksum mismatch"):
                    _ensure_selected_models(release, validated, action="install")
            provision.assert_not_called()

    def test_readiness_failure_and_deadline_are_reported(self):
        dead = self._container("gateway")
        dead["State"] = {"Status": "exited"}
        with patch(
            "scripts.stt_deployment._project_services", return_value={"gateway": dead}
        ):
            with self.assertRaisesRegex(ValueError, "exited before readiness"):
                _wait_service_readiness(
                    "gateway",
                    self.project,
                    self.release["services"]["gateway"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                )

    def test_exited_container_diagnostic_precedes_runtime_configuration_drift(self):
        dead = self._container("tts")
        dead["State"] = {"Status": "exited", "ExitCode": 1}
        dead["Mounts"][0]["Source"] = "/private/incorrect.yaml"
        with patch(
            "scripts.stt_deployment._project_services", return_value={"tts": dead}
        ):
            with self.assertRaisesRegex(ValueError, r"tts container exited.*exit 1"):
                _wait_service_readiness(
                    "tts",
                    self.project,
                    self.release["services"]["tts"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                )

    def test_running_tts_with_wrong_mount_reports_configuration_drift(self):
        running = self._container("tts")
        running["Mounts"][0]["Source"] = "/private/incorrect.yaml"
        with patch(
            "scripts.stt_deployment._project_services", return_value={"tts": running}
        ):
            with self.assertRaisesRegex(
                ValueError, "configuration differs from the plan"
            ):
                _wait_service_readiness(
                    "tts",
                    self.project,
                    self.release["services"]["tts"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                )

    def test_gateway_readiness_distinguishes_unpublished_unhealthy_and_no_healthcheck(
        self,
    ):
        gateway = self._container("gateway")
        gateway["NetworkSettings"]["Ports"]["8080/tcp"] = None
        with patch(
            "scripts.stt_deployment._project_services",
            return_value={"gateway": gateway},
        ):
            with self.assertRaisesRegex(ValueError, "not published by Docker"):
                _wait_service_readiness(
                    "gateway",
                    self.project,
                    self.release["services"]["gateway"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                )

        gateway = self._container("gateway")
        gateway["State"]["Health"] = {"Status": "unhealthy"}
        with patch(
            "scripts.stt_deployment._project_services",
            return_value={"gateway": gateway},
        ):
            with self.assertRaisesRegex(ValueError, "became unhealthy"):
                _wait_service_readiness(
                    "gateway",
                    self.project,
                    self.release["services"]["gateway"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                )

        gateway = self._container("gateway")
        gateway["Config"].pop("Healthcheck", None)
        now = [0]

        def sleep(seconds):
            now[0] += seconds

        with patch(
            "scripts.stt_deployment._project_services",
            return_value={"gateway": gateway},
        ):
            with self.assertRaisesRegex(
                ValueError, "Docker healthcheck is missing.*deadline"
            ):
                _wait_service_readiness(
                    "gateway",
                    self.project,
                    self.release["services"]["gateway"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                    probe=lambda *_args, **_kwargs: False,
                    sleep=sleep,
                    monotonic=lambda: now[0],
                )

        # A Docker healthcheck is not required when the existing host HTTP
        # readiness endpoint responds through the verified publication.
        with patch(
            "scripts.stt_deployment._project_services",
            return_value={"gateway": gateway},
        ):
            _wait_service_readiness(
                "gateway",
                self.project,
                self.release["services"]["gateway"]["image"],
                self._rendered(),
                self.profile,
                self.gateway,
                self.tts,
                probe=lambda *_args, **_kwargs: True,
            )

        live = self._container("gateway")
        now = [0]

        def sleep(seconds):
            now[0] += seconds

        with patch(
            "scripts.stt_deployment._project_services", return_value={"gateway": live}
        ):
            with self.assertRaisesRegex(ValueError, "did not become healthy"):
                _wait_service_readiness(
                    "gateway",
                    self.project,
                    self.release["services"]["gateway"]["image"],
                    self._rendered(),
                    self.profile,
                    self.gateway,
                    self.tts,
                    probe=lambda *_args, **_kwargs: False,
                    sleep=sleep,
                    monotonic=lambda: now[0],
                )


class ExitStackForTest:
    def __init__(self, patches):
        from contextlib import ExitStack

        self.stack = ExitStack()
        self.patches = patches

    def __enter__(self):
        for patcher in self.patches:
            self.stack.enter_context(patcher)

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


if __name__ == "__main__":
    unittest.main()
