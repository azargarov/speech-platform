"""Prerequisite outcomes and provider metadata checks use no real GPU/provider."""

import contextlib
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import preflight as preflight


class FirstTimeSetupTests(unittest.TestCase):
    def make_checkout(self, root):
        root = Path(root)
        shutil.copy(preflight.ROOT / ".env.example", root / ".env.example")
        shutil.copy(preflight.ROOT / "Makefile", root / "Makefile")
        scripts = root / "scripts"
        scripts.mkdir(exist_ok=True)
        shutil.copy(preflight.ROOT / "scripts/init.sh", scripts / "init.sh")
        return root

    def run_init(self, root, *, env=None):
        return subprocess.run(
            ["make", "init"],
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def test_clean_init_creates_private_token_and_preflight_compatible_env(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_checkout(temp)
            result = self.run_init(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("SPEECH_API_TOKEN=", result.stdout)

            env_path = root / ".env"
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
            values = dict(
                line.split("=", 1)
                for line in env_path.read_text().splitlines()
                if line and not line.startswith("#")
            )
            token = values["SPEECH_API_TOKEN"]
            self.assertEqual(len(token), 64)
            self.assertTrue(all(character in "0123456789abcdef" for character in token))
            self.assertNotIn(token, result.stdout + result.stderr)
            for relative in ("private", "private/audio", "private/deployment"):
                self.assertEqual(stat.S_IMODE((root / relative).stat().st_mode), 0o700)
            self.assertNotIn("GROQ_STT_API_KEY", values)
            loaded = preflight.load_env(root)
            preflight.validate_environment(loaded, root)
            self.assertEqual(loaded["SPEECH_API_TOKEN"], token)

    def test_tokens_are_independent_and_repeated_init_preserves_existing_env(self):
        tokens = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as temp:
                root = self.make_checkout(temp)
                first = self.run_init(root)
                self.assertEqual(first.returncode, 0, first.stderr)
                env_path = root / ".env"
                original = env_path.read_bytes()
                original_stat = env_path.stat()
                token = next(
                    line.split("=", 1)[1]
                    for line in original.decode().splitlines()
                    if line.startswith("SPEECH_API_TOKEN=")
                )
                tokens.append(token)

                second = self.run_init(root)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(env_path.read_bytes(), original)
                self.assertEqual(env_path.stat().st_mtime_ns, original_stat.st_mtime_ns)
                self.assertNotIn(token, second.stdout + second.stderr)
        self.assertNotEqual(tokens[0], tokens[1])

    def test_existing_operator_env_and_private_files_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.make_checkout(temp)
            private = root / "private"
            private.mkdir(mode=0o700)
            secret = private / "cloud.env"
            secret.write_text("SYNTHETIC_CREDENTIAL=do-not-change\n")
            config_dir = private / "deployment"
            config_dir.mkdir(mode=0o700)
            config = config_dir / "gateway.yaml"
            config.write_text("synthetic: operator-config\n")
            env_path = root / ".env"
            original = b"SPEECH_API_TOKEN=operator-owned-value\n# keep this file\n"
            env_path.write_bytes(original)
            env_path.chmod(0o600)
            original_mtime = env_path.stat().st_mtime_ns

            result = self.run_init(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(env_path.read_bytes(), original)
            self.assertEqual(env_path.stat().st_mtime_ns, original_mtime)
            self.assertEqual(secret.read_text(), "SYNTHETIC_CREDENTIAL=do-not-change\n")
            self.assertEqual(config.read_text(), "synthetic: operator-config\n")
            self.assertNotIn("operator-owned-value", result.stdout + result.stderr)

    def test_missing_openssl_fails_before_creating_configuration(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryDirectory() as bin_dir,
        ):
            root = self.make_checkout(temp)
            for tool in ("mkdir", "chmod", "mktemp", "ln", "rm"):
                executable = shutil.which(tool)
                self.assertIsNotNone(executable, f"test host lacks {tool}")
                os.symlink(executable, Path(bin_dir) / tool)
            result = subprocess.run(
                ["/bin/sh", "scripts/init.sh"],
                cwd=root,
                env={"PATH": bin_dir},
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "required system tool 'openssl' is unavailable", result.stderr
            )
            self.assertFalse((root / ".env").exists())
            self.assertFalse((root / "private").exists())

    def test_malformed_token_template_fails_before_creating_configuration(self):
        malformed_templates = (
            "SPEECH_API_TOKEN=\nSPEECH_API_TOKEN=\n",
            " SPEECH_API_TOKEN=\n",
            "SPEECH_API_TOKEN=preconfigured-value\n",
            "SPEECH_API_TOKEN\n",
        )
        for template in malformed_templates:
            with self.subTest(template=template), tempfile.TemporaryDirectory() as temp:
                root = self.make_checkout(temp)
                (root / ".env.example").write_text(template)
                result = self.run_init(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root / ".env").exists())
                self.assertFalse((root / "private").exists())
                self.assertNotIn("preconfigured-value", result.stdout + result.stderr)

    def test_concurrent_init_never_overwrites_first_published_env(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            tempfile.TemporaryDirectory() as bin_dir,
            tempfile.TemporaryDirectory() as barrier_dir,
        ):
            root = self.make_checkout(temp)
            bin_path = Path(bin_dir)
            for tool in ("mkdir", "chmod", "mktemp", "rm", "openssl", "sleep"):
                executable = shutil.which(tool)
                self.assertIsNotNone(executable, f"test host lacks {tool}")
                os.symlink(executable, bin_path / tool)

            real_ln = shutil.which("ln")
            self.assertIsNotNone(real_ln)
            wrapper = bin_path / "ln"
            wrapper.write_text(
                "#!/bin/sh\n"
                "source=$1\n"
                "destination=$2\n"
                ': > "$INIT_BARRIER/ready.$$"\n'
                "while :; do\n"
                '    set -- "$INIT_BARRIER"/ready.*\n'
                '    [ "$#" -ge 2 ] && break\n'
                "    sleep 0.01\n"
                "done\n"
                'exec "$INIT_REAL_LN" "$source" "$destination"\n'
            )
            wrapper.chmod(0o700)
            environment = os.environ.copy()
            environment.update(
                PATH=bin_dir,
                INIT_BARRIER=barrier_dir,
                INIT_REAL_LN=real_ln,
            )
            processes = [
                subprocess.Popen(
                    ["/bin/sh", "scripts/init.sh"],
                    cwd=root,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = [process.communicate(timeout=10) for process in processes]

            for process, (stdout, stderr) in zip(processes, results, strict=True):
                self.assertEqual(process.returncode, 0, stderr)
                self.assertNotIn("SPEECH_API_TOKEN=", stdout + stderr)
            env_path = root / ".env"
            values = dict(
                line.split("=", 1)
                for line in env_path.read_text().splitlines()
                if line and not line.startswith("#")
            )
            token = values["SPEECH_API_TOKEN"]
            self.assertEqual(len(token), 64)
            self.assertTrue(all(character in "0123456789abcdef" for character in token))
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o600)
            self.assertEqual(list(root.glob(".env.init.*")), [])


class PreflightTests(unittest.TestCase):
    def fixture(self, directory, *, transform=None, dirty=False, fail_model=False):
        root = Path(directory)
        self.enterContext(
            patch.object(
                preflight.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=64 * 1024**3),
            )
        )
        import yaml

        (root / "private/deployment").mkdir(parents=True)
        (root / "models").mkdir()
        (root / "configs").mkdir()
        (root / "go.mod").write_text("module fixture\n\ngo 1.24.0\n")
        shutil.copy(
            preflight.ROOT / "configs/stt-product-deployment.yaml",
            root / "configs/stt-product-deployment.yaml",
        )
        shutil.copy(preflight.ROOT / "configs/tts.yaml", root / "configs/tts.yaml")
        config = root / "private/deployment/gateway.yaml"
        config.write_text(
            yaml.safe_dump({"text_transform": transform} if transform else {})
        )
        env_values = {
            "MODEL_STORE": str(root / "models"),
            "MODEL_MANIFEST_SHA256": preflight.STT_MANIFEST_SHA256,
            "TTS_MODEL_MANIFEST_SHA256": preflight.TTS_MANIFEST_SHA256,
            "SPEECH_PORT": "",
            "SPEECH_BIND_IP": "127.0.0.1",
            "SPEECH_API_TOKEN": "synthetic-token-value-with-at-least-32-chars",
            "STT_GPU_DEVICE": "0",
            "TTS_GPU_DEVICE": "0",
            "GATEWAY_CONFIG": "private/deployment/gateway.yaml",
            "INSTALL_MIN_FREE_GIB": "20",
        }
        port_probe = socket.socket()
        port_probe.bind(("127.0.0.1", 0))
        env_values["SPEECH_PORT"] = str(port_probe.getsockname()[1])
        port_probe.close()
        env_file = root / ".env"
        env_file.write_text(
            "".join(f"{key}={value}\n" for key, value in env_values.items())
        )
        env_file.chmod(0o600)
        calls = []

        def run(args, *, root=root, timeout=60, env=None):
            calls.append(args)
            if args[:3] == ["git", "rev-parse", "HEAD"]:
                return "a" * 40
            if args[:3] == ["git", "status", "--porcelain"]:
                return " M Makefile" if dirty else ""
            if args == ["go", "version"]:
                return "go version go1.24.0 linux/amd64"
            if args[:3] == ["docker", "compose", "version"]:
                return "2.40.0"
            if args == ["docker", "info", "--format", "{{.DockerRootDir}}"]:
                return str(root)
            if args[:3] == ["docker", "context", "inspect"]:
                return (
                    '[{"Endpoints":{"docker":{"Host":"unix:///var/run/docker.sock"}}}]'
                )
            if args[:2] == ["docker", "compose"] and "ls" in args:
                return "[]"
            if args[:3] == ["docker", "inspect", "ollama"]:
                return json.dumps(
                    [
                        {
                            "State": {"Running": True},
                            "NetworkSettings": {
                                "Networks": {
                                    preflight.OLLAMA_DEFAULT_NETWORK: {
                                        "Aliases": ["ollama"],
                                        "IPAddress": "172.31.0.2",
                                    }
                                }
                            },
                        }
                    ]
                )
            if args[:4] == [
                "docker",
                "network",
                "inspect",
                preflight.OLLAMA_DEFAULT_NETWORK,
            ]:
                return json.dumps([{"Internal": True}])
            if "--probe-ollama" in args:
                return "synthetic-version"
            if "{{json .Runtimes}}" in args:
                return '{"nvidia":{}}'
            if args and args[0] == "nvidia-smi":
                return "0, 570.0, 14000 MiB, 15000 MiB"
            return ""

        self.enterContext(patch.object(preflight, "run_command", side_effect=run))
        self.enterContext(
            patch.object(
                preflight,
                "_model_metadata",
                side_effect=preflight.PreflightError("model metadata missing")
                if fail_model
                else lambda *_: True,
            )
        )
        return root, calls

    def test_success_warnings_and_disabled_optional_checks_are_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root, calls = self.fixture(temp)
            report = preflight.run_checks(root=root, service="gateway")
        self.assertFalse(report.failed)
        self.assertTrue(
            any(
                group == "GPU" and status == "SKIP"
                for group, status, *_ in report.entries
            )
        )
        self.assertTrue(
            any(
                status == "SKIP" and "credentials" in detail
                for _, status, _, detail in report.entries
            )
        )
        self.assertFalse(
            any(
                args[0] in {"nvidia-smi"}
                or "tts_model" in args
                or "provision_models" in args
                for args in calls
            )
        )
        self.assertFalse(
            any(args[:2] in (["docker", "run"], ["docker", "pull"]) for args in calls)
        )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.display()
        self.assertIn("Summary: PASS=", output.getvalue())
        self.assertTrue(output.getvalue().endswith("READY TO INSTALL\n"))
        for group in preflight.GROUPS:
            self.assertIn(group + ":", output.getvalue())

    def test_missing_enabled_optional_cloud_credentials_warn_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            config_path = root / "private/deployment/gateway.yaml"
            config_path.write_text(
                "groq_stt:\n  enabled: true\n  api_key_env: GROQ_STT_API_KEY\n"
            )
            report = preflight.run_checks(root=root, service="gateway")
        self.assertFalse(report.failed)
        entry = next(
            item
            for item in report.entries
            if item[1] == "WARN" and "credentials" in item[2]
        )
        self.assertIn("unavailable", entry[3])

    def test_insufficient_checkout_and_docker_storage_remain_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            with patch.object(
                preflight.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1024**3),
            ):
                report = preflight.run_checks(root=root, service="gateway")
            self.assertTrue(report.failed)
            failures = [
                name
                for group, status, name, _ in report.entries
                if group == "Host" and status == "FAIL"
            ]
            self.assertTrue(
                any(name.startswith("Checkout storage") for name in failures)
            )
            self.assertTrue(any(name.startswith("Docker storage") for name in failures))

    def test_dirty_tree_warns_in_preflight_and_blocks_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp, dirty=True)
            self.assertFalse(preflight.run_checks(root=root).failed)
            self.assertTrue(preflight.run_checks(root=root, require_clean=True).failed)

    def test_missing_model_blocks_selected_worker_but_not_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp, fail_model=True)
            self.assertTrue(preflight.run_checks(root=root, service="tts").failed)
            self.assertFalse(preflight.run_checks(root=root, service="gateway").failed)

    def test_bad_env_and_unavailable_docker_still_return_grouped_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            (root / ".env").write_text("SPEECH_API_TOKEN=SECRET\n")
            (root / ".env").chmod(0o600)
            with patch.object(preflight, "run_command", side_effect=FileNotFoundError):
                report = preflight.run_checks(root=root)
        self.assertTrue(report.failed)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.display()
        self.assertNotIn("SECRET", output.getvalue())
        self.assertTrue(output.getvalue().endswith("NOT READY TO INSTALL\n"))
        self.assertIn("SKIP", output.getvalue())

    def test_preflight_compose_environment_ignores_ambient_deployment_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            values = preflight.load_env(root)
            config = preflight.gateway_config_path(root, values)
            with patch.dict(
                os.environ,
                {
                    "COMPOSE_PROJECT_NAME": "wrong-project",
                    "SOURCE_REVISION": "deadbeef",
                    "SPEECH_PORT": "9",
                    "COMPOSE_FILE": "unrelated.yaml",
                    "DOCKER_CONTEXT": "remote",
                    "DOCKER_HOST": "tcp://remote.invalid:2375",
                },
            ):
                env = preflight._compose_environment(values, "a" * 40, config, root)
        self.assertEqual(env["COMPOSE_PROJECT_NAME"], "speech-platform")
        self.assertEqual(env["SOURCE_REVISION"], "a" * 40)
        self.assertEqual(env["SPEECH_PORT"], values["SPEECH_PORT"])
        self.assertNotIn("COMPOSE_FILE", env)
        self.assertNotIn("DOCKER_CONTEXT", env)
        self.assertNotIn("DOCKER_HOST", env)

    def test_obsolete_gateway_image_pins_fail_with_migration_message(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            values = preflight.load_env(root)
            values["GATEWAY_EXPECTED_IMAGE_ID"] = "sha256:old-pin"
            with self.assertRaisesRegex(
                preflight.PreflightError, "obsolete Gateway image pin"
            ):
                preflight.validate_environment(values, root)

    def test_preflight_reports_actionable_legacy_pin_migration_without_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            env = root / ".env"
            with env.open("a") as stream:
                stream.write("GATEWAY_EXPECTED_IMAGE_ID=private-old-image-id\n")
            report = preflight.run_checks(root=root)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report.display()
        self.assertIn(
            "Remove the reviewed GATEWAY_EXPECTED_IMAGE_ID", output.getvalue()
        )
        self.assertNotIn("private-old-image-id", output.getvalue())

    def test_compose_project_override_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            values = preflight.load_env(root)
            values["COMPOSE_PROJECT_NAME"] = "another-project"
            with self.assertRaisesRegex(
                preflight.PreflightError, "fixed to speech-platform"
            ):
                preflight.validate_environment(values, root)

    def test_docker_commands_use_default_context_and_ignore_context_overrides(self):
        result = SimpleNamespace(returncode=0, stdout="ok", stderr="")
        with (
            patch.dict(
                os.environ,
                {
                    "DOCKER_CONTEXT": "remote",
                    "DOCKER_HOST": "tcp://remote.invalid:2375",
                },
            ),
            patch.object(preflight.subprocess, "run", return_value=result) as run,
        ):
            self.assertEqual(preflight.run_command(["docker", "info"]), "ok")
        args = run.call_args.args[0]
        self.assertEqual(args[:3], ["docker", "--context", "default"])
        self.assertNotIn("DOCKER_CONTEXT", run.call_args.kwargs["env"])
        self.assertNotIn("DOCKER_HOST", run.call_args.kwargs["env"])

    def test_preflight_issues_only_read_only_docker_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root, calls = self.fixture(temp)
            preflight.run_checks(root=root, service="gateway")
        mutating = {
            "build",
            "create",
            "down",
            "kill",
            "pull",
            "push",
            "rm",
            "start",
            "stop",
            "up",
            "connect",
            "disconnect",
            "prune",
        }
        for args in calls:
            if not args or args[0] != "docker":
                continue
            self.assertFalse(any(part in mutating for part in args[1:]), args)

    def test_local_ollama_preflight_only_inspects_shared_resources(self):
        transform = {
            "enabled": True,
            "selection": {"allow_cloud": False},
            "providers": [
                {
                    "id": "ollama",
                    "type": "ollama",
                    "locality": "local",
                    "endpoint": "http://ollama:11434/api/generate",
                }
            ],
            "models": [{"provider": "ollama", "model": "local:test", "enabled": True}],
        }
        with tempfile.TemporaryDirectory() as temp:
            root, calls = self.fixture(temp, transform=transform)
            preflight.run_checks(root=root, service="gateway")
        self.assertTrue(
            any(args[:3] == ["docker", "inspect", "ollama"] for args in calls)
        )
        self.assertTrue(
            any(
                args[:2] == ["docker", "network"] and "inspect" in args
                for args in calls
            )
        )
        self.assertTrue(any("--probe-ollama" in args for args in calls))
        for args in calls:
            if args and args[0] == "docker":
                self.assertNotIn("create", args)
                self.assertNotIn("connect", args)
                self.assertNotIn("disconnect", args)

    def test_conflicting_compose_project_is_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            original = preflight.run_command

            def conflicting(args, **kwargs):
                if args[:2] == ["docker", "compose"] and "ls" in args:
                    return json.dumps(
                        [
                            {
                                "Name": "speech-platform",
                                "ConfigFiles": "/other/compose.yaml",
                            }
                        ]
                    )
                return original(args, **kwargs)

            with patch.object(preflight, "run_command", side_effect=conflicting):
                report = preflight.run_checks(root=root, service="gateway")
        self.assertTrue(
            any(
                group == "Deployment"
                and status == "FAIL"
                and name == "Compose project ownership"
                for group, status, name, _ in report.entries
            )
        )

    def test_gateway_port_conflict_is_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            values = preflight.load_env(root)
            with socket.socket() as occupied:
                occupied.bind(("127.0.0.1", 0))
                values["SPEECH_PORT"] = str(occupied.getsockname()[1])
                env_path = root / ".env"
                env_path.write_text(
                    "".join(f"{key}={value}\n" for key, value in values.items())
                )
                env_path.chmod(0o600)
                report = preflight.run_checks(root=root, service="gateway")
        self.assertTrue(
            any(
                group == "Networking"
                and status == "FAIL"
                and name == "Gateway bind port"
                for group, status, name, _ in report.entries
            )
        )

    def test_model_metadata_checks_manifest_file_set_and_size_without_hashing(self):
        digest = "a" * 64
        model = {
            "manifest_sha256": digest,
            "manifest_path": "releases/artifacts/test.yaml",
        }
        manifest = {
            "files": [{"path": "weights.bin", "size_bytes": 4, "sha256": "b" * 64}]
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            artifact = store / digest / "artifact"
            artifact.mkdir(parents=True)
            (store / digest / "manifest.yaml").write_text("pinned manifest")
            weights = artifact / "weights.bin"
            weights.write_bytes(b"good")
            with (
                patch.object(
                    preflight,
                    "load_release",
                    return_value={
                        "services": {"stt": {"required_model_artifacts": [model]}}
                    },
                ),
                patch.object(
                    preflight, "load_artifact_manifest", return_value=manifest
                ) as load_manifest,
            ):
                self.assertTrue(preflight._model_metadata(str(store), "stt", root))
                load_manifest.assert_any_call(
                    root / "releases/artifacts/test.yaml", digest
                )
                weights.write_bytes(b"evil")
                self.assertTrue(preflight._model_metadata(str(store), "stt", root))
                (artifact / "extra.bin").write_bytes(b"x")
                with self.assertRaisesRegex(ValueError, "file set"):
                    preflight._model_metadata(str(store), "stt", root)
                (artifact / "extra.bin").unlink()
                weights.write_bytes(b"bad")
                with self.assertRaisesRegex(ValueError, "file sizes"):
                    preflight._model_metadata(str(store), "stt", root)

    def test_model_metadata_rejects_bad_manifest_and_missing_files(self):
        digest = "c" * 64
        model = {
            "manifest_sha256": digest,
            "manifest_path": "releases/artifacts/test.yaml",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = root / "store"
            (store / digest / "artifact").mkdir(parents=True)
            (store / digest / "manifest.yaml").write_text("bad")
            with (
                patch.object(
                    preflight,
                    "load_release",
                    return_value={
                        "services": {"stt": {"required_model_artifacts": [model]}}
                    },
                ),
                patch.object(
                    preflight,
                    "load_artifact_manifest",
                    side_effect=ValueError("bad pinned manifest"),
                ),
            ):
                with self.assertRaisesRegex(ValueError, "manifest"):
                    preflight._model_metadata(str(store), "stt", root)

    def test_secret_symlink_is_rejected(self):
        config = {"groq_stt": {"enabled": True, "api_key_env": "GROQ_STT_API_KEY"}}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "private"
            private.mkdir()
            target = private / "actual.env"
            target.write_text("GROQ_STT_API_KEY=synthetic-credential-value\n")
            target.chmod(0o600)
            (private / "cloud.env").symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                preflight.cloud_credentials(
                    root, {}, config, preflight.credential_env_names
                )

    def test_report_requires_remediation_and_counts_all_statuses(self):
        r = preflight.Report()
        with self.assertRaises(ValueError):
            r.add("Host", "FAIL", "missing")
        for s in preflight.STATUSES:
            r.add(
                "Host", s, "check", "Install prerequisite or disable optional feature."
            )
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            r.display()
        self.assertIn("PASS=1 WARN=1 FAIL=1 SKIP=1", output.getvalue())

    def test_cloud_disabled_needs_no_credentials(self):
        self.assertFalse(
            preflight.cloud_credentials(
                Path("/not-present"),
                {},
                {
                    "groq_stt": {"enabled": False},
                    "text_transform": {
                        "enabled": True,
                        "selection": {"allow_cloud": False},
                    },
                },
                preflight.credential_env_names,
            )
        )

    def test_enabled_cloud_private_credentials_are_checked_and_never_printed(self):
        t = {
            "enabled": True,
            "selection": {"allow_cloud": True},
            "models": [{"provider": "cloud", "enabled": True}],
            "providers": [
                {"id": "cloud", "locality": "cloud", "api_key_env": "TEST_KEY"}
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            secret = root / "private/cloud.env"
            with self.assertRaises(OSError):
                preflight.cloud_credentials(
                    root,
                    {},
                    {"text_transform": t},
                    preflight.credential_env_names,
                )
            secret.write_text("TEST_KEY=synthetic-test-credential\n")
            secret.chmod(0o600)
            self.assertTrue(
                preflight.cloud_credentials(
                    root,
                    {},
                    {"text_transform": t},
                    preflight.credential_env_names,
                )
            )
            secret.chmod(0o644)
            with self.assertRaises(ValueError):
                preflight.cloud_credentials(
                    root,
                    {},
                    {"text_transform": t},
                    preflight.credential_env_names,
                )
            secret.chmod(0o600)
            secret.write_text("TEST_KEY=bad whitespace\n")
            with self.assertRaises(ValueError):
                preflight.cloud_credentials(
                    root,
                    {},
                    {"text_transform": t},
                    preflight.credential_env_names,
                )
            secret.write_text("OTHER_KEY=synthetic-test-credential\n")
            with self.assertRaises(ValueError):
                preflight.cloud_credentials(
                    root,
                    {},
                    {"text_transform": t},
                    preflight.credential_env_names,
                )

    def test_groq_and_cloud_text_credentials_are_independent(self):
        cloud_text = {
            "enabled": True,
            "selection": {"allow_cloud": True},
            "models": [{"provider": "text-cloud", "enabled": True}],
            "providers": [
                {
                    "id": "text-cloud",
                    "locality": "cloud",
                    "api_key_env": "TEXT_API_KEY",
                }
            ],
        }
        groq = {"enabled": True, "api_key_env": "GROQ_STT_API_KEY"}
        combinations = {
            "groq only": (
                {"groq_stt": groq, "text_transform": {"enabled": False}},
                "GROQ_STT_API_KEY=synthetic-groq-credential\n",
            ),
            "cloud text only": (
                {"groq_stt": {"enabled": False}, "text_transform": cloud_text},
                "TEXT_API_KEY=synthetic-text-credential\n",
            ),
            "both": (
                {"groq_stt": groq, "text_transform": cloud_text},
                "GROQ_STT_API_KEY=synthetic-groq-credential\nTEXT_API_KEY=synthetic-text-credential\n",
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private").mkdir()
            secret = root / "private/cloud.env"
            for name, (document, contents) in combinations.items():
                with self.subTest(name=name):
                    secret.write_text(contents)
                    secret.chmod(0o600)
                    self.assertTrue(
                        preflight.cloud_credentials(
                            root, {}, document, preflight.credential_env_names
                        )
                    )
            secret.write_text("GROQ_STT_API_KEY=synthetic-groq-credential\n")
            secret.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "every enabled"):
                preflight.cloud_credentials(
                    root,
                    {},
                    combinations["both"][0],
                    preflight.credential_env_names,
                )


class OllamaMetadataTests(unittest.TestCase):
    def test_valid_and_invalid_metadata_endpoints_without_inference(self):
        paths = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                self.send_response(200)
                self.end_headers()
                body = (
                    {"version": "test"}
                    if self.path == "/api/version"
                    else {"models": [{"name": "local:test"}]}
                )
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            self.assertEqual(preflight.probe_ollama(origin, ["local:test"]), "test")
            with self.assertRaisesRegex(ValueError, "missing"):
                preflight.probe_ollama(origin, ["missing:test"])
            self.assertEqual(set(paths), {"/api/version", "/api/tags"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)
        with self.assertRaises(OSError):
            preflight.probe_ollama(origin, [], timeout=0.1)

    def test_bounded_and_malformed_metadata(self):
        for body in (b"not-json", b"{}", b"x" * (1024 * 1024 + 1)):
            response = io.BytesIO(body)
            response.status = 200
            with self.assertRaises((ValueError, json.JSONDecodeError)):
                preflight.probe_ollama(
                    "http://invalid", [], opener=lambda *a, **k: response
                )


if __name__ == "__main__":
    unittest.main()


class ModelStoreAccessTests(unittest.TestCase):
    def test_store_parent_requires_traverse_but_not_directory_listing(self):
        with patch.object(
            preflight.os,
            "access",
            side_effect=lambda _path, mode: mode == os.X_OK,
        ) as access:
            self.assertTrue(preflight._model_store_traversable("/model-store"))
        access.assert_called_once_with("/model-store", os.X_OK)


class OllamaNameValidationTests(unittest.TestCase):
    def test_read_only_ollama_names_accept_defaults_and_reject_invalid_values(self):
        preflight.validate_ollama_names(
            preflight.OLLAMA_DEFAULT_NETWORK, preflight.OLLAMA_DEFAULT_CONTAINER
        )
        for network, container in (
            ("bad/name", "ollama"),
            (preflight.OLLAMA_DEFAULT_NETWORK, "bad name"),
        ):
            with self.subTest(network=network, container=container):
                with self.assertRaises(preflight.PreflightError):
                    preflight.validate_ollama_names(network, container)

    def test_store_without_traverse_permission_is_rejected(self):
        with patch.object(preflight.os, "access", return_value=False) as access:
            self.assertFalse(preflight._model_store_traversable("/model-store"))
        access.assert_called_once_with("/model-store", os.X_OK)


class PreflightCLITests(unittest.TestCase):
    def test_blocked_preflight_returns_nonzero_and_ends_with_readiness(self):
        report = preflight.Report()
        report.add("Host", "FAIL", "Configuration", "Correct the configuration.")
        output = io.StringIO()
        with (
            patch("sys.argv", ["preflight"]),
            patch.object(preflight, "run_checks", return_value=report),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(preflight.main(), 2)
        self.assertTrue(output.getvalue().endswith("NOT READY TO INSTALL\n"))


class AdditionalBoundaryTests(unittest.TestCase):
    fixture = PreflightTests.fixture

    def test_gpu_unavailable_blocks_workers_and_does_not_block_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            root, _ = self.fixture(temp)
            original = preflight.run_command

            def no_gpu(args, **kw):
                if args[0] == "nvidia-smi":
                    raise FileNotFoundError()
                return original(args, **kw)

            with patch.object(preflight, "run_command", side_effect=no_gpu):
                self.assertTrue(preflight.run_checks(root=root, service="tts").failed)
                self.assertFalse(
                    preflight.run_checks(root=root, service="gateway").failed
                )

    def test_reserved_cloud_key_is_rejected_before_reading_secret(self):
        t = {
            "enabled": True,
            "selection": {"allow_cloud": True},
            "models": [{"provider": "cloud", "enabled": True}],
            "providers": [
                {"id": "cloud", "locality": "cloud", "api_key_env": "SPEECH_API_TOKEN"}
            ],
        }
        with self.assertRaisesRegex(ValueError, "reserved"):
            preflight.cloud_credentials(
                Path("/unused"),
                {},
                {"text_transform": t},
                preflight.credential_env_names,
            )

    def test_ollama_request_has_bounded_timeout(self):
        release = threading.Event()
        entered = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                entered.set()
                release.wait(2)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(OSError):
                preflight.probe_ollama(
                    f"http://127.0.0.1:{server.server_port}", [], timeout=0.05
                )
            self.assertTrue(entered.is_set())
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(2)
