"""Tests for the minimal Make/Compose deployment path using mocked Docker."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import compose, deploy_images


class ComposeInvocationTests(unittest.TestCase):
    def checkout(self, temp, *, config="{}\n"):
        root = Path(temp)
        (root / "configs").mkdir()
        (root / "deployments/compose").mkdir(parents=True)
        (root / "configs/gateway.yaml").write_text(config)
        (root / "compose.yaml").write_text("name: speech-platform\n")
        (root / "deployments/compose/compose.ollama.yaml").write_text("services: {}\n")
        (root / ".env").write_text(
            "SPEECH_API_TOKEN=synthetic-token-value-with-at-least-32-chars\n"
        )
        (root / ".env").chmod(0o600)
        return root

    def test_fixed_local_compose_and_sanitized_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.checkout(temp)
            original_env = (root / ".env").read_bytes()
            with (
                patch.object(
                    compose.subprocess,
                    "run",
                    return_value=SimpleNamespace(stdout="a" * 40, returncode=0),
                ),
                patch.dict(
                    os.environ,
                    {
                        "COMPOSE_PROJECT_NAME": "wrong-project",
                        "COMPOSE_FILE": "foreign.yaml",
                        "SOURCE_REVISION": "deadbeef",
                        "GATEWAY_IMAGE": "untrusted-image",
                        "SPEECH_API_TOKEN": "ambient-secret-that-must-not-win",
                        "DOCKER_HOST": "tcp://remote.invalid:2375",
                        "DOCKER_CONTEXT": "remote",
                    },
                ),
                patch.object(
                    compose.preflight,
                    "gateway_config_path",
                    return_value=root / "configs/gateway.yaml",
                ),
            ):
                command, env = compose.setup(root)
                self.assertEqual((root / ".env").read_bytes(), original_env)
        self.assertIn("--context", command)
        self.assertEqual(command[command.index("--context") + 1], "default")
        self.assertEqual(
            command[command.index("--project-name") + 1], "speech-platform"
        )
        self.assertNotIn("-f", command[command.index("-f") + 2 :])
        self.assertEqual(env["COMPOSE_PROJECT_NAME"], "speech-platform")
        self.assertEqual(
            env["SPEECH_API_TOKEN"], "synthetic-token-value-with-at-least-32-chars"
        )
        for key in ("COMPOSE_FILE", "GATEWAY_IMAGE", "DOCKER_HOST", "DOCKER_CONTEXT"):
            self.assertNotIn(key, env)
        self.assertEqual(env["SOURCE_REVISION"], "a" * 40)

    def test_log_collection_arguments_are_limited_to_known_services_and_five_minutes(
        self,
    ):
        for service in compose.SERVICES:
            compose.validate_args(["logs", "--since", "300s", "--tail", "100", service])
        for args in (
            ["logs", "--since", "301s", "--tail", "100", "gateway"],
            ["logs", "--since", "5m", "--tail", "101", "gateway"],
            ["logs", "--since", "5m", "--tail", "100", "ollama"],
            ["logs", "--since", "0s", "--tail", "100", "gateway"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                compose.validate_args(args)

    def test_ollama_overlay_is_selected_only_for_local_ollama(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temp:
                root = self.checkout(temp)
                with (
                    patch.object(
                        compose.subprocess,
                        "run",
                        return_value=SimpleNamespace(stdout="a" * 40, returncode=0),
                    ),
                    patch.object(
                        compose.preflight,
                        "gateway_config_path",
                        return_value=root / "configs/gateway.yaml",
                    ),
                    patch.object(
                        compose.preflight, "uses_local_ollama", return_value=enabled
                    ),
                ):
                    command, _ = compose.setup(root)
                self.assertEqual("compose.ollama.yaml" in " ".join(command), enabled)

    def test_project_owner_mismatch_blocks_mutating_compose_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.checkout(temp)
            with (
                patch.object(compose, "setup", return_value=([], {})),
                patch.object(
                    compose.subprocess,
                    "run",
                    return_value=SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps(
                            [
                                {
                                    "Name": "speech-platform",
                                    "ConfigFiles": "/tmp/other.yaml",
                                }
                            ]
                        ),
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "belongs to another"),
            ):
                compose.verify_project(root)

    def test_compose_wrapper_refuses_destructive_or_unknown_commands(self):
        for args in (
            ("down",),
            ("rm",),
            ("pull",),
            ("config",),
            ("up", "--remove-orphans"),
            ("stop", "--timeout", "1"),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                compose.run(list(args))

    def test_build_and_up_accept_only_explicit_unique_component_selections(self):
        for args in (
            ["build", "gateway"],
            ["build", "gateway", "stt"],
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--force-recreate",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "240",
                "gateway",
            ],
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--force-recreate",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "240",
                "gateway",
                "tts",
            ],
        ):
            with self.subTest(args=args):
                compose.validate_args(args)
        for args in (
            ["build", "gateway", "gateway"],
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--force-recreate",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "240",
            ],
            [
                "up",
                "-d",
                "--no-build",
                "--pull",
                "never",
                "--force-recreate",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "240",
                "gateway",
                "ollama",
            ],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                compose.validate_args(args)

    def test_global_compose_inventory_enables_profiles_for_read_only_ps(self):
        with (
            patch.object(compose, "setup", return_value=(["docker", "compose"], {})),
            patch.object(compose, "verify_project"),
            patch.object(
                compose.subprocess, "run", return_value=SimpleNamespace(returncode=0)
            ) as run,
        ):
            compose.run(["ps", "--all", "--format", "json"])
        command = run.call_args.args[0]
        self.assertIn("--profile", command)
        self.assertEqual(command[command.index("--profile") + 1], "stt")

    def test_unscoped_logs_and_stop_include_all_profiles(self):
        for args in (["logs", "--tail", "100"], ["stop"]):
            with (
                self.subTest(args=args),
                patch.object(
                    compose, "setup", return_value=(["docker", "compose"], {})
                ),
                patch.object(compose, "verify_project"),
                patch.object(
                    compose.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
            ):
                compose.run(args)
                command = run.call_args.args[0]
                self.assertIn("--profile", command)
                self.assertEqual(command[command.index("--profile") + 1], "stt")

    def test_service_scoped_stop_logs_status_do_not_expand_project_scope(self):
        for args in (
            ("stop", "tts"),
            ("logs", "--tail", "100", "stt"),
            ("ps", "--all", "gateway"),
        ):
            with self.subTest(args=args):
                with (
                    patch.object(
                        compose,
                        "setup",
                        return_value=(
                            [
                                "docker",
                                "--context",
                                "default",
                                "compose",
                                "--project-name",
                                "speech-platform",
                            ],
                            {},
                        ),
                    ),
                    patch.object(compose, "verify_project"),
                    patch.object(
                        compose.subprocess,
                        "run",
                        return_value=SimpleNamespace(returncode=0),
                    ) as run,
                ):
                    compose.run(list(args))
                self.assertEqual(run.call_args.args[0][-len(args) :], list(args))
                self.assertNotIn("down", run.call_args.args[0])


class ImageSafetyTests(unittest.TestCase):
    def image(self, *, service="gateway", revision="a" * 40, role=None, variant=None):
        role = (
            role
            or {"gateway": "gateway", "stt": "stt-worker", "tts": "tts-worker"}[service]
        )
        variant = variant or ("foundation" if service == "gateway" else "cuda")
        return {
            "Id": "sha256:" + "b" * 64,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": revision,
                    "com.speech-platform.service": service,
                    "com.speech-platform.service-role": role,
                    "com.speech-platform.runtime-variant": variant,
                }
            },
        }

    def test_build_verification_checks_revision_service_role_and_platform(self):
        def inspect(args, **_kwargs):
            service = args[-1].split(":", 1)[0].removeprefix("speech-platform-")
            if service == "stt-cuda":
                service = "stt"
            return SimpleNamespace(stdout=json.dumps([self.image(service=service)]))

        with (
            patch.object(deploy_images, "revision", return_value="a" * 40),
            patch.object(deploy_images, "docker", side_effect=inspect),
        ):
            result = deploy_images.built_images()
        self.assertEqual(set(result), {"gateway", "stt", "tts"})

        bad = self.image(role="wrong")
        with (
            patch.object(deploy_images, "revision", return_value="a" * 40),
            patch.object(
                deploy_images,
                "docker",
                return_value=SimpleNamespace(stdout=json.dumps([bad])),
            ),
            self.assertRaisesRegex(deploy_images.DeployError, "validation failed"),
        ):
            deploy_images.built_images()

    def test_source_check_rejects_dirty_or_missing_committed_source(self):
        with (
            patch.object(
                deploy_images.preflight,
                "run_command",
                side_effect=["a" * 40, " M Makefile"],
            ),
            self.assertRaisesRegex(deploy_images.DeployError, "clean Git worktree"),
        ):
            deploy_images.source_check()
        with (
            patch.object(
                deploy_images.preflight,
                "run_command",
                side_effect=["a" * 40, ""],
            ),
            patch("builtins.print") as output,
        ):
            deploy_images.source_check()
        self.assertIn("a" * 40, output.call_args.args[0])

    def test_source_check_accepts_full_sha256_git_revision(self):
        with (
            patch.object(
                deploy_images.preflight,
                "run_command",
                side_effect=["a" * 64, ""],
            ),
            patch("builtins.print") as output,
        ):
            deploy_images.source_check()
        self.assertIn("a" * 64, output.call_args.args[0])

    def test_retain_tags_exact_container_image_ids(self):
        container = {"Image": "sha256:" + "b" * 64}
        with (
            patch.object(
                deploy_images,
                "project_containers",
                return_value=[("gateway", container)],
            ),
            patch.object(
                deploy_images,
                "docker",
                side_effect=[
                    SimpleNamespace(returncode=1, stdout="", stderr=""),
                    SimpleNamespace(returncode=0, stdout="", stderr=""),
                ],
            ) as run,
            patch("builtins.print"),
        ):
            deploy_images.retain()
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["image", "inspect", "speech-platform-rollback-gateway:" + "b" * 64],
        )
        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "image",
                "tag",
                container["Image"],
                "speech-platform-rollback-gateway:" + "b" * 64,
            ],
        )

    def test_retain_is_scoped_to_selected_components(self):
        with (
            patch.object(
                deploy_images, "project_containers", return_value=[]
            ) as inspect,
            patch("builtins.print"),
        ):
            deploy_images.retain(("gateway", "stt"))
        inspect.assert_called_once_with(("gateway", "stt"))

    def test_running_rejects_old_image_from_rebuilt_revision_tag(self):
        revision = "a" * 40
        old_container = {
            "Image": "sha256:" + "b" * 64,
            "State": {"Status": "running"},
        }
        with (
            patch.object(
                deploy_images,
                "built_images",
                return_value={
                    "gateway": (
                        "speech-platform-gateway:" + revision,
                        "sha256:" + "c" * 64,
                    )
                },
            ),
            patch.object(
                deploy_images,
                "compose_run",
                return_value=SimpleNamespace(stdout="gateway-container\n"),
            ),
            patch.object(
                deploy_images, "inspect_container", return_value=old_container
            ),
            patch.object(deploy_images, "check_owner"),
            self.assertRaisesRegex(
                deploy_images.DeployError, "differs from the verified build"
            ),
        ):
            deploy_images.running(("gateway",))

    def test_component_selection_validation(self):
        self.assertEqual(
            deploy_images.parse_components("gateway,stt"), ("gateway", "stt")
        )
        for raw in ("", "stt", "gateway,stt,stt", "gateway,ollama"):
            with self.subTest(raw=raw), self.assertRaises(deploy_images.DeployError):
                deploy_images.parse_components(raw)

    def test_retained_containers_must_belong_to_this_project_and_checkout(self):
        container = {
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "speech-platform",
                    "com.docker.compose.service": "gateway",
                    "com.docker.compose.project.working_dir": str(
                        deploy_images.ROOT.resolve()
                    ),
                    "com.docker.compose.project.config_files": str(
                        (deploy_images.ROOT / "compose.yaml").resolve()
                    ),
                }
            }
        }
        deploy_images.check_owner(container, "gateway")
        foreign = json.loads(json.dumps(container))
        foreign["Config"]["Labels"]["com.docker.compose.project"] = "other"
        with self.assertRaisesRegex(deploy_images.DeployError, "not owned"):
            deploy_images.check_owner(foreign, "gateway")
        foreign = json.loads(json.dumps(container))
        foreign["Config"]["Labels"]["com.docker.compose.project.config_files"] = (
            "/tmp/other.yaml"
        )
        with self.assertRaisesRegex(
            deploy_images.DeployError, "unexpected Compose file"
        ):
            deploy_images.check_owner(foreign, "gateway")

    def test_cuda_probe_is_network_isolated_and_cleans_its_named_container_on_failure(
        self,
    ):
        values = {"STT_GPU_DEVICE": "0", "TTS_GPU_DEVICE": "0"}
        identities = {
            "stt": ("speech-platform-stt-cuda:" + "a" * 40, "sha256:" + "b" * 64),
            "tts": ("speech-platform-tts:" + "a" * 40, "sha256:" + "c" * 64),
        }
        with (
            patch.object(deploy_images.preflight, "load_env", return_value=values),
            patch.object(deploy_images.preflight, "validate_environment"),
            patch.object(deploy_images, "built_images", return_value=identities),
            patch.object(
                deploy_images,
                "docker",
                side_effect=[
                    SimpleNamespace(returncode=1, stderr="probe failed"),
                    SimpleNamespace(returncode=1, stderr="No such container"),
                ],
            ) as docker,
            self.assertRaisesRegex(
                deploy_images.DeployError, "services were not replaced"
            ),
        ):
            deploy_images.cuda_probe()
        self.assertIn("--network", docker.call_args_list[0].args[0])
        self.assertIn("none", docker.call_args_list[0].args[0])
        cleanup_args = docker.call_args_list[1].args[0]
        self.assertEqual(cleanup_args[:2], ["rm", "-f"])
        self.assertTrue(cleanup_args[2].startswith("speech-platform-cuda-probe-stt-"))

    def test_make_install_stops_before_up_when_validation_build_or_cuda_fails(self):
        makefile = Path(__file__).resolve().parents[1] / "Makefile"
        for fail_at, must_not_reach in (
            ("scripts/deploy_images.py source", "scripts/preflight.py"),
            ("scripts/preflight.py", "scripts/deploy_images.py retain"),
            ("scripts/compose.py build", "scripts/compose.py up"),
            ("scripts/deploy_images.py verify", "scripts/compose.py up"),
            ("scripts/deploy_images.py cuda", "scripts/compose.py up"),
        ):
            with self.subTest(fail_at=fail_at), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                bin_dir = root / "bin"
                bin_dir.mkdir()
                log = root / "commands.log"
                fake_python = bin_dir / "python"
                fake_python.write_text(
                    "#!/bin/sh\n"
                    'printf \'%s\\n\' "$*" >> "$LOG_FILE"\n'
                    'case "$*" in *"$FAIL_AT"*) exit 1;; esac\n'
                )
                fake_python.chmod(0o755)
                fake_git = bin_dir / "git"
                fake_git.write_text(
                    "#!/bin/sh\ncase \"$*\" in 'status --porcelain --untracked-files=all') printf '%s' \"$DIRTY_STATUS\";; 'rev-parse --verify HEAD') printf '%040d\\n' 1;; *) exit 1;; esac\n"
                )
                fake_git.chmod(0o755)
                env = os.environ | {
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "LOG_FILE": str(log),
                    "FAIL_AT": fail_at,
                    "DIRTY_STATUS": "",
                }
                result = subprocess.run(
                    [
                        "make",
                        "-f",
                        str(makefile),
                        "install",
                        "PYTHON=" + str(fake_python),
                    ],
                    cwd=root,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                commands = log.read_text().splitlines()
                self.assertFalse(any(must_not_reach in item for item in commands))

    def test_make_install_orders_all_preconditions_before_compose_up(self):
        makefile = Path(__file__).resolve().parents[1] / "Makefile"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log = root / "commands.log"
            fake_python = bin_dir / "python"
            fake_python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$LOG_FILE"\n')
            fake_python.chmod(0o755)
            env = os.environ | {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "LOG_FILE": str(log),
            }
            result = subprocess.run(
                ["make", "-f", str(makefile), "install", "PYTHON=" + str(fake_python)],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log.read_text().splitlines()
            self.assertEqual(
                commands,
                [
                    "scripts/deploy_images.py source",
                    "scripts/preflight.py --components gateway,stt,tts",
                    "scripts/deploy_images.py retain --components gateway,stt,tts",
                    "scripts/compose.py build gateway stt tts",
                    "scripts/deploy_images.py verify --components gateway,stt,tts",
                    "scripts/deploy_images.py cuda --components gateway,stt,tts",
                    "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 stt tts",
                    "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 gateway",
                    "scripts/deploy_images.py running --components gateway,stt,tts",
                    "scripts/compose.py exec -T gateway /healthcheck http://127.0.0.1:8080/readyz",
                    'scripts/compose.py exec -T stt python -c import urllib.request; urllib.request.urlopen("http://127.0.0.1:8081/readyz", timeout=3)',
                    'scripts/compose.py exec -T tts python -c import urllib.request; urllib.request.urlopen("http://127.0.0.1:8082/readyz", timeout=3)',
                ],
            )

    def test_gateway_only_install_does_not_build_or_start_workers(self):
        makefile = Path(__file__).resolve().parents[1] / "Makefile"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log = root / "commands.log"
            fake_python = bin_dir / "python"
            fake_python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$LOG_FILE"\n')
            fake_python.chmod(0o755)
            env = os.environ | {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "LOG_FILE": str(log),
            }
            result = subprocess.run(
                [
                    "make",
                    "-f",
                    str(makefile),
                    "install",
                    "COMPONENTS=gateway",
                    "PYTHON=" + str(fake_python),
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log.read_text().splitlines()
            self.assertIn("scripts/compose.py build gateway", commands)
            self.assertIn(
                "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 gateway",
                commands,
            )
            self.assertFalse(
                any(
                    item.endswith("stt")
                    or item.endswith("tts")
                    or " stt " in item
                    or " tts " in item
                    for item in commands
                )
            )

    def test_each_partial_install_targets_only_its_selected_worker(self):
        makefile = Path(__file__).resolve().parents[1] / "Makefile"
        for selection, worker in (("gateway,stt", "stt"), ("gateway,tts", "tts")):
            with (
                self.subTest(selection=selection),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                bin_dir = root / "bin"
                bin_dir.mkdir()
                log = root / "commands.log"
                fake_python = bin_dir / "python"
                fake_python.write_text(
                    '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$LOG_FILE"\n'
                )
                fake_python.chmod(0o755)
                env = os.environ | {
                    "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                    "LOG_FILE": str(log),
                }
                result = subprocess.run(
                    [
                        "make",
                        "-f",
                        str(makefile),
                        "install",
                        "COMPONENTS=" + selection,
                        "PYTHON=" + str(fake_python),
                    ],
                    cwd=root,
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                compose_commands = [
                    line
                    for line in log.read_text().splitlines()
                    if line.startswith("scripts/compose.py")
                ]
                self.assertIn(
                    "scripts/compose.py build gateway " + worker, compose_commands
                )
                self.assertIn(
                    "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 "
                    + worker,
                    compose_commands,
                )
                self.assertIn(
                    "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 gateway",
                    compose_commands,
                )
                unselected = "tts" if worker == "stt" else "stt"
                self.assertFalse(
                    any(unselected in line.split() for line in compose_commands)
                )

    def test_install_recreates_selected_services_after_same_revision_tag_rebuild(self):
        """A rebuilt revision tag must replace old containers with that tag."""
        makefile = Path(__file__).resolve().parents[1] / "Makefile"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            log = root / "commands.log"
            fake_python = bin_dir / "python"
            fake_python.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$LOG_FILE"\n')
            fake_python.chmod(0o755)
            env = os.environ | {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "LOG_FILE": str(log),
            }
            result = subprocess.run(
                [
                    "make",
                    "-f",
                    str(makefile),
                    "install",
                    "COMPONENTS=gateway,stt",
                    "PYTHON=" + str(fake_python),
                ],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            activation = [
                line
                for line in log.read_text().splitlines()
                if line.startswith("scripts/compose.py up ")
            ]
            self.assertEqual(
                activation,
                [
                    "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 stt",
                    "scripts/compose.py up -d --no-build --pull never --force-recreate --no-deps --wait --wait-timeout 240 gateway",
                ],
            )


if __name__ == "__main__":
    unittest.main()
