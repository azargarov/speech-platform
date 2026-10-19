from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.stt_deployment import (
    _check_project_conflicts,
    _install_command,
    _require_release_match,
    require_container_config_access,
    run_deployment,
    verify_registry_image,
    wait_for_container_readiness,
    _subprocess_failure,
)
from scripts.stt_deployment_profile import _fields

MODEL_MANIFEST_SHA256 = (
    "86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6"
)


class DeploymentOrchestrationTests(unittest.TestCase):
    def test_container_config_preflight_rejects_unreadable_file_without_reading_it(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o711)
            config = root / "worker.yaml"
            config.write_text("private-fixture-value\n")
            config.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "cannot read") as raised:
                require_container_config_access([config])
            self.assertNotIn("private-fixture-value", str(raised.exception))

    def test_individual_bind_mount_does_not_require_host_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hidden = root / "private"
            hidden.mkdir()
            config = hidden / "worker.yaml"
            config.write_text("fixture\n")
            config.chmod(0o640)
            # The fixture owner differs from the configured container UID;
            # its GID is the simulated supplementary reader group.
            hidden.chmod(0o700)
            require_container_config_access(
                [config], uid=12345, supplementary_gids=(config.stat().st_gid,)
            )

    def test_container_config_preflight_rejects_symlink_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target.yaml"
            target.write_text("fixture\n")
            target.chmod(0o644)
            link = root / "worker.yaml"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "not a regular file"):
                require_container_config_access([link])

    def test_container_config_preflight_rejects_symlink_parent_component(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real_parent = root / "real"
            real_parent.mkdir()
            config = real_parent / "worker.yaml"
            config.write_text("fixture\n")
            config.chmod(0o644)
            linked_parent = root / "linked"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "unsafe component"):
                require_container_config_access([linked_parent / "worker.yaml"])

    def test_container_config_preflight_accepts_readable_file_and_traversable_paths(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o711)
            config = root / "worker.yaml"
            config.write_text("fixture\n")
            config.chmod(0o644)
            require_container_config_access([config])

    def test_unreadable_config_blocks_deployment_before_docker_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            paths = []
            for name in (
                "profile.yaml",
                "application.yaml",
                "deployment.yaml",
                "worker.yaml",
            ):
                path = root / name
                path.write_text("fixture\n")
                path.chmod(0o600)
                paths.append(str(path))
            commands = []
            with (
                patch("scripts.stt_deployment.require_private_config_paths"),
                patch(
                    "scripts.stt_deployment.load_and_validate",
                    return_value={"artifact_access": {"supplementary_read_gid": 988}},
                ),
                patch("scripts.stt_deployment._require_release_match"),
                self.assertRaisesRegex(ValueError, "cannot read"),
            ):
                run_deployment(
                    "install",
                    profile_path=paths[0],
                    application_config=paths[1],
                    deployment_config=paths[2],
                    worker_config=paths[3],
                    release_path="unused",
                    env_file="unused",
                    run=lambda command, **kwargs: commands.append(command) or "",
                )
            self.assertEqual(commands, [])

    def _readiness_inspection(
        self,
        *,
        status="running",
        health="healthy",
        image="registry/stt@sha256:abc",
        exit_code=0,
    ):
        return [
            {
                "Config": {
                    "Image": image,
                    "Labels": {
                        "com.docker.compose.project": "isolated-stt",
                        "com.docker.compose.service": "stt",
                    },
                },
                "State": {
                    "Status": status,
                    "ExitCode": exit_code,
                    "Health": {"Status": health},
                },
            }
        ]

    def test_readiness_returns_for_exact_running_healthy_container_without_compose(
        self,
    ):
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            if command[1:2] == ["ps"]:
                return "container-id\n"
            return json.dumps(self._readiness_inspection())

        wait_for_container_readiness(
            "isolated-stt", "registry/stt@sha256:abc", timeout_seconds=10, run=run
        )
        self.assertEqual(commands[0][1], "ps")
        self.assertTrue(all(command[1] != "compose" for command in commands))
        self.assertIn("label=com.docker.compose.project=isolated-stt", commands[0])
        self.assertIn("label=com.docker.compose.service=stt", commands[0])

    def test_readiness_waits_until_starting_container_becomes_healthy(self):
        states = iter(("starting", "healthy"))

        def run(command, **kwargs):
            if command[1:2] == ["ps"]:
                return "container-id\n"
            return json.dumps(self._readiness_inspection(health=next(states)))

        wait_for_container_readiness(
            "isolated-stt",
            "registry/stt@sha256:abc",
            timeout_seconds=10,
            run=run,
            sleep=lambda _: None,
        )

    def test_readiness_fails_when_container_exits_early(self):
        def run(command, **kwargs):
            if command[1:2] == ["ps"]:
                return "container-id\n"
            return json.dumps(self._readiness_inspection(status="exited", exit_code=1))

        with self.assertRaisesRegex(ValueError, "exited before readiness"):
            wait_for_container_readiness(
                "isolated-stt",
                "registry/stt@sha256:abc",
                timeout_seconds=10,
                run=run,
            )

    def test_readiness_fails_when_container_becomes_unhealthy(self):
        def run(command, **kwargs):
            if command[1:2] == ["ps"]:
                return "container-id\n"
            return json.dumps(self._readiness_inspection(health="unhealthy"))

        with self.assertRaisesRegex(ValueError, "became unhealthy"):
            wait_for_container_readiness(
                "isolated-stt",
                "registry/stt@sha256:abc",
                timeout_seconds=10,
                run=run,
            )

    def test_readiness_fails_when_multiple_containers_match(self):
        def run(command, **kwargs):
            return "container-one\ncontainer-two\n"

        with self.assertRaisesRegex(ValueError, "not created or is ambiguous"):
            wait_for_container_readiness(
                "isolated-stt",
                "registry/stt@sha256:abc",
                timeout_seconds=10,
                run=run,
            )

    def test_readiness_fails_for_wrong_image_identity(self):
        def run(command, **kwargs):
            if command[1:2] == ["ps"]:
                return "container-id\n"
            return json.dumps(self._readiness_inspection(image="registry/stt:mutable"))

        with self.assertRaisesRegex(ValueError, "image does not match"):
            wait_for_container_readiness(
                "isolated-stt",
                "registry/stt@sha256:abc",
                timeout_seconds=10,
                run=run,
            )

    def test_readiness_times_out_while_container_remains_starting(self):
        elapsed = [0.0]

        def run(command, **kwargs):
            if command[1:2] == ["ps"]:
                return "container-id\n"
            return json.dumps(self._readiness_inspection(health="starting"))

        def sleep(seconds):
            elapsed[0] += seconds

        def monotonic():
            return elapsed[0]

        with self.assertRaisesRegex(ValueError, "before the deadline"):
            wait_for_container_readiness(
                "isolated-stt",
                "registry/stt@sha256:abc",
                timeout_seconds=3,
                run=run,
                sleep=sleep,
                monotonic=monotonic,
            )

    def test_called_process_error_reports_operation_and_code_without_stderr(self):
        error = subprocess.CalledProcessError(
            17, ["docker", "compose", "up"], stderr="private config value"
        )
        message = _subprocess_failure(error)
        self.assertIn("docker compose up", message)
        self.assertIn("17", message)
        self.assertNotIn("private config value", message)

    def test_make_profile_selection_maps_each_profile_to_its_private_directory(self):
        cases = (
            ("plan", None, "private/deployment/stt-cuda/"),
            ("plan", "regular", "private/deployment/stt-cuda/"),
            (
                "plan",
                "experimental",
                "private/deployment/stt-cuda-experimental/",
            ),
            (
                "install",
                "experimental",
                "private/deployment/stt-cuda-experimental/",
            ),
        )
        for target, profile, expected_directory in cases:
            with self.subTest(target=target, profile=profile):
                command = ["make", "--no-print-directory", "-n", target, "SERVICE=stt"]
                if profile is not None:
                    command.append(f"PROFILE={profile}")
                result = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                self.assertIn(
                    f'--profile "{expected_directory}profile.yaml"', result.stdout
                )
                self.assertIn(
                    f'--application-config "{expected_directory}stt-application.yaml"',
                    result.stdout,
                )
                self.assertIn(
                    f'--deployment-config "{expected_directory}stt-deployment.yaml"',
                    result.stdout,
                )
                self.assertIn(
                    f'--worker-config "{expected_directory}stt.yaml"',
                    result.stdout,
                )
                self.assertIn(
                    f'--env-file "{expected_directory}compose.env"', result.stdout
                )

    def test_make_rejects_unknown_profile_before_running_deployment_code(self):
        result = subprocess.run(
            [
                "make",
                "--no-print-directory",
                "-n",
                "plan",
                "SERVICE=stt",
                "PROFILE=unknown",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown deployment PROFILE", result.stderr)
        self.assertNotIn("scripts.stt_deployment", result.stdout)

    def test_missing_private_configuration_diagnostic_names_the_requirement(self):
        with self.assertRaisesRegex(
            ValueError,
            "required private configuration profile.yaml is missing",
        ):
            run_deployment(
                "plan",
                profile_path="private/deployment/stt-cuda/missing-profile.yaml",
                application_config="unused",
                deployment_config="unused",
                worker_config="unused",
                release_path="releases/voiceservice-v0.1.2.yaml",
                env_file="unused",
            )

    def test_schema_diagnostic_names_missing_requirements_not_values(self):
        with self.assertRaisesRegex(
            ValueError, r"deployment profile is missing required field\(s\): runtime"
        ):
            _fields(
                {"schema_version": 1},
                {"schema_version", "runtime"},
                "deployment profile",
            )

    def test_schema_diagnostic_names_unsupported_fields_without_values(self):
        with self.assertRaisesRegex(
            ValueError, r"runtime contains unsupported field\(s\): credential"
        ) as raised:
            _fields({"credential": "do-not-print"}, set(), "runtime")
        self.assertNotIn("do-not-print", str(raised.exception))

    def test_registry_image_requires_exact_identity_and_provenance(self):
        digest_ref = "ghcr.io/example/stt@sha256:" + "a" * 64
        validated = {
            "image": digest_ref,
            "image_id": "sha256:" + "b" * 64,
            "platform": "linux/amd64",
            "profile": {
                "runtime": {
                    "source_revision": "c" * 40,
                    "base_image": "python:3.13-slim@sha256:" + "d" * 64,
                    "cuda_lock_sha256": "e" * 64,
                }
            },
        }
        inspection = [
            {
                "Id": validated["image_id"],
                "RepoDigests": [digest_ref],
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "User": "65532:65532",
                    "Entrypoint": ["python", "-m"],
                    "Labels": {
                        "org.opencontainers.image.revision": "c" * 40,
                        "com.speech-platform.source-revision": "c" * 40,
                        "com.speech-platform.image-role": "stt-worker",
                        "com.speech-platform.base-image": (
                            "python:3.13-slim@sha256:" + "d" * 64
                        ),
                        "com.speech-platform.cuda-lock-sha256": "e" * 64,
                    },
                },
            }
        ]
        verify_registry_image(validated, lambda command: json.dumps(inspection))

        inspection[0]["RepoDigests"] = []
        with self.assertRaisesRegex(ValueError, "digest, platform or provenance"):
            verify_registry_image(validated, lambda command: json.dumps(inspection))

    def test_release_digest_and_model_must_match_profile(self):
        release_service = {
            "runtime_variant": "cuda",
            "image": "ghcr.io/azargarov/voiceservice-stt-cuda@sha256:"
            "31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8",
            "platform": "linux/amd64",
            "required_model_artifacts": [
                {
                    "id": "large-v3-turbo",
                    "revision": ("0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"),
                    "manifest_sha256": MODEL_MANIFEST_SHA256,
                }
            ],
        }
        validated = {
            "identity_mode": "registry_digest",
            "image": release_service["image"],
            "platform": release_service["platform"],
            "profile": {
                "model": {
                    "alias": "large-v3-turbo",
                    "revision": release_service["required_model_artifacts"][0][
                        "revision"
                    ],
                    "manifest_sha256": release_service["required_model_artifacts"][0][
                        "manifest_sha256"
                    ],
                }
            },
        }
        # Exercise release parsing against the tracked, strictly validated manifest.
        loaded = _require_release_match(
            validated, Path("releases/voiceservice-v0.1.2.yaml")
        )
        self.assertEqual(loaded["release_version"], "v0.1.2")
        validated["identity_mode"] = "local_image_id"
        with self.assertRaisesRegex(ValueError, "immutable GHCR"):
            _require_release_match(validated, "releases/voiceservice-v0.1.2.yaml")

    def test_empty_project_is_available_and_matching_project_is_reusable(self):
        rendered = {
            "services": {
                "stt": {
                    "image": "ghcr.io/example/stt@sha256:" + "a" * 64,
                    "labels": {"com.speech-platform.profile": "abc"},
                }
            }
        }

        def empty_run(command):
            self.assertIn("docker", command)
            return ""

        self.assertFalse(_check_project_conflicts("isolated-stt", rendered, empty_run))

        def exact_run(command):
            if command[1] == "ps":
                return "container-id\n"
            if command[1] == "network" and command[2] == "ls":
                return "network-id\n"
            if command[1] == "network":
                return json.dumps(
                    [
                        {
                            "Id": "network-id",
                            "Name": "isolated-stt_stt_private",
                            "Labels": {
                                "com.docker.compose.project": "isolated-stt",
                                "com.docker.compose.network": "stt_private",
                            },
                            "Internal": True,
                            "Containers": {"container-full-id": {}},
                        }
                    ]
                )
            return json.dumps(
                [
                    {
                        "Id": "container-full-id",
                        "Config": {
                            "Image": rendered["services"]["stt"]["image"],
                            "Labels": {
                                "com.docker.compose.project": "isolated-stt",
                                "com.docker.compose.service": "stt",
                                "com.speech-platform.profile": "abc",
                            },
                        },
                    }
                ]
            )

        self.assertTrue(_check_project_conflicts("isolated-stt", rendered, exact_run))

    def test_project_name_collision_with_other_service_fails_closed(self):
        rendered = {"services": {"stt": {"image": "approved", "labels": {}}}}

        def collision_run(command):
            if command[1] == "ps":
                return "foreign-container"
            if command[1] == "network" and command[2] == "ls":
                return ""
            return json.dumps(
                [
                    {
                        "Config": {
                            "Image": "ollama:latest",
                            "Labels": {
                                "com.docker.compose.project": "isolated-stt",
                                "com.docker.compose.service": "ollama",
                            },
                        }
                    }
                ]
            )

        with self.assertRaisesRegex(ValueError, "conflicts"):
            _check_project_conflicts("isolated-stt", rendered, collision_run)

    def test_existing_project_with_different_identity_fails_closed(self):
        rendered = {"services": {"stt": {"image": "approved", "labels": {"id": "new"}}}}

        def mismatch_run(command):
            if command[1] == "ps":
                return "container"
            if command[1] == "network" and command[2] == "ls":
                return ""
            return json.dumps(
                [
                    {
                        "Config": {
                            "Image": "approved",
                            "Labels": {
                                "com.docker.compose.project": "isolated-stt",
                                "com.docker.compose.service": "stt",
                                "id": "old",
                            },
                        }
                    }
                ]
            )

        with self.assertRaisesRegex(ValueError, "different deployment identity"):
            _check_project_conflicts("isolated-stt", rendered, mismatch_run)

    def test_install_command_is_scoped_to_one_project_and_one_service(self):
        command = _install_command("isolated-stt")
        self.assertEqual(command[0:2], ["docker", "compose"])
        self.assertEqual(command[command.index("--project-name") + 1], "isolated-stt")
        self.assertEqual(command[-1], "stt")
        self.assertIn("up", command)
        self.assertIn("--no-build", command)
        self.assertEqual(command[command.index("--pull") + 1], "never")
        self.assertFalse(set(command) & {"down", "rm", "prune", "build", "pull"})

    def _run_with_mocks(self, action, root, gpu_probe, run):
        config_paths = []
        for name in (
            "profile.yaml",
            "application.yaml",
            "deployment.yaml",
            "worker.yaml",
        ):
            path = root / name
            path.write_text("fixture\n")
            config_paths.append(str(path))
        release_root = root / "model-release"
        release_root.mkdir()
        validated = {
            "artifact_access": {"supplementary_read_gid": 988},
            "deployment": SimpleNamespace(minimum_free_gpu_bytes_before_load=1024**2),
            "release_root": release_root,
            "image": "ghcr.io/example/stt@sha256:" + "a" * 64,
            "model": {"alias": "large-v3-turbo", "revision": "b" * 40},
            "profile": {
                "project_name": "isolated-experimental-stt",
                "gateway": {"host_port": 18083, "listen_port": 8080},
            },
            "healthcheck": {
                "start_period_seconds": 30,
                "interval_seconds": 5,
                "retries": 3,
                "timeout_seconds": 2,
            },
        }
        release = {"release_version": "v0.1.2"}
        model_result = SimpleNamespace(directory=release_root)
        with ExitStack() as stack:
            stack.enter_context(
                patch("scripts.stt_deployment.require_private_config_paths")
            )
            stack.enter_context(
                patch("scripts.stt_deployment.require_container_config_access")
            )
            stack.enter_context(
                patch(
                    "scripts.stt_deployment.load_and_validate",
                    return_value=validated,
                )
            )
            stack.enter_context(
                patch(
                    "scripts.stt_deployment._require_release_match",
                    return_value=release,
                )
            )
            stack.enter_context(
                patch(
                    "scripts.stt_deployment.compose_environment",
                    return_value={
                        "STT_COMPOSE_PROJECT_NAME": "isolated-experimental-stt"
                    },
                )
            )
            stack.enter_context(patch("scripts.stt_deployment.verify_registry_image"))
            stack.enter_context(
                patch(
                    "scripts.stt_deployment.check_models",
                    return_value=[model_result],
                )
            )
            stack.enter_context(
                patch("scripts.stt_deployment.validate_rendered_compose")
            )
            return run_deployment(
                action,
                profile_path=config_paths[0],
                application_config=config_paths[1],
                deployment_config=config_paths[2],
                worker_config=config_paths[3],
                release_path="releases/voiceservice-v0.1.2.yaml",
                env_file=str(root / "compose.env"),
                run=run,
                gpu_probe=gpu_probe,
            )

    def test_plan_is_read_only_and_reports_ready_and_blocked_admission(self):
        for free_bytes, expected_status in (
            (2 * 1024**2, "READY"),
            (0, "BLOCKED"),
        ):
            with (
                self.subTest(expected_status=expected_status),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                env_file = root / "compose.env"
                env_file.write_text("preserve-me\n")
                before = (env_file.read_bytes(), env_file.stat().st_mtime_ns)
                baseline_dir = root / "operational-baseline"
                baseline_dir.mkdir()
                baseline_files = [
                    baseline_dir / name for name in ("profile.yaml", "stt.yaml")
                ]
                for path in baseline_files:
                    path.write_text("baseline-configuration\n")
                baseline_before = {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in baseline_files
                }
                commands = []

                def run(command, **kwargs):
                    commands.append(command)
                    if command[:2] == ["docker", "compose"]:
                        self.assertIn("STT_COMPOSE_PROJECT_NAME", kwargs["environment"])
                        return json.dumps({"services": {"stt": {}}})
                    return ""

                # gpu = lambda validated: {
                #    "free_mib": free_bytes // (1024**2),
                #    "free_bytes": free_bytes,
                #    "threshold_bytes": 1024**2,
                #    "identity_matches": True,
                # }

                def gpu(validated):
                    return {
                        "free_mib": free_bytes // (1024**2),
                        "free_bytes": free_bytes,
                        "threshold_bytes": 1024**2,
                        "identity_matches": True,
                    }

                output = StringIO()
                with redirect_stdout(output):
                    status = self._run_with_mocks("plan", root, gpu, run)
                self.assertEqual(status, 0 if expected_status == "READY" else 2)
                self.assertIn(f"admission={expected_status}", output.getvalue())
                self.assertEqual(
                    (env_file.read_bytes(), env_file.stat().st_mtime_ns), before
                )
                self.assertEqual(
                    {
                        path: (path.read_bytes(), path.stat().st_mtime_ns)
                        for path in baseline_files
                    },
                    baseline_before,
                )
                self.assertTrue(commands)
                self.assertTrue(
                    any(command[-2:] == ["--format", "json"] for command in commands)
                )
                self.assertTrue(
                    any(command[:2] == ["docker", "ps"] for command in commands)
                )
                self.assertTrue(
                    any(
                        command[:3] == ["docker", "network", "ls"]
                        for command in commands
                    )
                )
                mutating_actions = {
                    "up",
                    "pull",
                    "create",
                    "start",
                    "stop",
                    "rm",
                    "down",
                }
                self.assertFalse(
                    any(set(command) & mutating_actions for command in commands)
                )

    def test_install_rechecks_gpu_immediately_before_start(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            commands = []
            probes = iter((2 * 1024**2, 0))

            def run(command, **kwargs):
                commands.append((command, kwargs))
                if command[-2:] == ["--format", "json"]:
                    return json.dumps({"services": {"stt": {}}})
                return ""

            def gpu(validated):
                free_bytes = next(probes)
                return {
                    "free_mib": free_bytes // (1024**2),
                    "free_bytes": free_bytes,
                    "threshold_bytes": 1024**2,
                    "identity_matches": True,
                }

            with self.assertRaisesRegex(ValueError, "immediately before startup"):
                self._run_with_mocks("install", root, gpu, run)
            mutations = [command for command, _ in commands if "up" in command]
            self.assertEqual(mutations, [])

    def test_protected_operational_project_is_never_mutable(self):
        with self.assertRaisesRegex(ValueError, "protected operational STT project"):
            _check_project_conflicts(
                "speech-platform-stt-runtime-smoke-20261018", {}, lambda command: ""
            )


if __name__ == "__main__":
    unittest.main()
