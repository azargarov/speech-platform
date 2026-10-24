"""Prerequisite outcomes and provider metadata checks use no real GPU/provider."""

import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import installation_preflight as preflight
from scripts import product_deployment as product


class PreflightTests(unittest.TestCase):
    def fixture(self, directory, *, transform=None, dirty=False, fail_model=False):
        root = Path(directory)
        # Host capacity is an input to these offline tests, not a CI prerequisite.
        self.enterContext(
            patch.object(
                preflight.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=64 * 1024**3),
            )
        )
        (root / "go.mod").write_text("module fixture\n\ngo 1.24.0\n")
        config = root / "gateway.yaml"
        import yaml

        config.write_text(
            yaml.safe_dump({"text_transform": transform} if transform else {})
        )
        values = {
            "MODEL_STORE": directory,
            "SPEECH_PORT": "8080",
            "SPEECH_BIND_IP": "127.0.0.1",
            "STT_GPU_DEVICE": "0",
            "TTS_GPU_DEVICE": "0",
        }
        calls = []

        def run(args, **_):
            calls.append(args)
            text = ""
            if args[:3] == ["git", "rev-parse", "HEAD"]:
                text = "a" * 40
            elif args[:3] == ["git", "status", "--porcelain"]:
                text = " M Makefile" if dirty else ""
            elif args == ["go", "version"]:
                text = "go version go1.24.0 linux/amd64"
            elif args == ["docker", "info", "--format", "{{.DockerRootDir}}"]:
                text = directory
            elif args[:3] == ["docker", "compose", "version"]:
                text = "2.40.0"
            elif "{{json .Runtimes}}" in args:
                text = '{"nvidia":{}}'
            elif args[0] == "nvidia-smi":
                text = "0, 570.0, 14000 MiB, 15000 MiB"
            if (
                fail_model
                and "check" in args
                and ("scripts.tts_model" in args or "scripts.provision_models" in args)
            ):
                return SimpleNamespace(returncode=2, stdout="", stderr="not available")
            return SimpleNamespace(returncode=0, stdout=text, stderr="")

        p = SimpleNamespace(
            ROOT=root,
            run=run,
            load_env=lambda: values,
            validate_environment=lambda _: ("127.0.0.1", 8080, 0, 0),
            require_local_docker=lambda: None,
            verify_project_ownership=lambda _: False,
            check_gateway_port=lambda *_: None,
            gateway_config_path=lambda _: config,
            set_compose_env=lambda *_: None,
            compose=lambda *_, **__: SimpleNamespace(returncode=0, stdout=""),
            require_existing_workers_healthy=lambda *_: None,
            gateway_uses_local_ollama=lambda _: False,
        )
        return p, calls

    def test_success_warnings_and_disabled_optional_checks_are_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            p, calls = self.fixture(temp)
            report = preflight.collect(p, service="gateway")
        self.assertFalse(report.failed)
        self.assertIn(
            ("GPU", "SKIP", "CUDA workers", "No GPU worker selected."), report.entries
        )
        self.assertTrue(
            any(s == "SKIP" and "credentials" in d for _, s, _, d in report.entries)
        )
        self.assertFalse(
            any(a[0] == "nvidia-smi" or "scripts.tts_model" in a for a in calls)
        )
        self.assertFalse(
            any(a[:2] in (["docker", "run"], ["docker", "pull"]) for a in calls)
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report.display()
        self.assertIn("Summary: PASS=", out.getvalue())
        self.assertTrue(out.getvalue().endswith("READY TO INSTALL\n"))
        for group in preflight.GROUPS:
            self.assertIn(group + ":", out.getvalue())

    def test_insufficient_checkout_and_docker_storage_remain_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            p, _ = self.fixture(temp)
            with patch.object(
                preflight.shutil,
                "disk_usage",
                return_value=SimpleNamespace(free=1024**3),
            ):
                report = preflight.collect(p, service="gateway")
            self.assertTrue(report.failed)
            failures = [
                name
                for group, status, name, _ in report.entries
                if group == "Host" and status == "FAIL"
            ]
            self.assertTrue(any(name.startswith("Storage (") for name in failures))
            self.assertTrue(
                any(name.startswith("Docker storage (") for name in failures)
            )

    def test_dirty_tree_warns_in_preflight_and_blocks_install(self):
        with tempfile.TemporaryDirectory() as temp:
            p, _ = self.fixture(temp, dirty=True)
            self.assertFalse(preflight.collect(p).failed)
            self.assertTrue(preflight.collect(p, require_clean=True).failed)

    def test_missing_model_blocks_selected_worker_but_not_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            p, _ = self.fixture(temp, fail_model=True)
            self.assertTrue(preflight.collect(p, service="tts").failed)
            self.assertFalse(preflight.collect(p, service="gateway").failed)

    def test_bad_env_and_unavailable_docker_still_return_grouped_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            p, _ = self.fixture(temp)
            p.load_env = lambda: (_ for _ in ()).throw(
                ValueError("SECRET must not appear")
            )
            p.run = lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError())
            report = preflight.collect(p)
        self.assertTrue(report.failed)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            report.display()
        self.assertNotIn("SECRET", out.getvalue())
        self.assertTrue(out.getvalue().endswith("NOT READY TO INSTALL\n"))
        self.assertIn("SKIP", out.getvalue())

    def test_failure_exits_nonzero_before_install_side_effects(self):
        with (
            patch.object(
                product,
                "checks",
                side_effect=product.OperatorError("blocking prerequisites"),
            ),
            patch.object(product, "load_env", return_value={}),
            patch.object(product, "compose") as compose,
            patch("sys.argv", ["product", "install", "--service", "tts"]),
        ):
            self.assertEqual(product.main(), 2)
        compose.assert_not_called()

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
                {"enabled": True, "selection": {"allow_cloud": False}},
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
                preflight.cloud_credentials(root, {}, t)
            secret.write_text("TEST_KEY=synthetic-test-credential\n")
            secret.chmod(0o600)
            self.assertTrue(preflight.cloud_credentials(root, {}, t))
            secret.chmod(0o644)
            with self.assertRaises(ValueError):
                preflight.cloud_credentials(root, {}, t)
            secret.chmod(0o600)
            secret.write_text("TEST_KEY=bad whitespace\n")
            with self.assertRaises(ValueError):
                preflight.cloud_credentials(root, {}, t)
            secret.write_text("OTHER_KEY=synthetic-test-credential\n")
            with self.assertRaises(ValueError):
                preflight.cloud_credentials(root, {}, t)


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


class ServiceScopeTests(unittest.TestCase):
    def test_worker_install_builds_and_recreates_only_selected_service(self):
        for service in ("stt", "tts"):
            with self.subTest(service=service):
                values = {"SPEECH_BIND_IP": "127.0.0.1", "SPEECH_PORT": "8080"}
                calls = []
                with (
                    patch("sys.argv", ["product", "install", "--service", service]),
                    patch.object(product, "load_env", return_value=values),
                    patch.object(
                        product,
                        "checks",
                        return_value=(values, "a" * 40, "compose", "gpu", None),
                    ),
                    patch.object(
                        product,
                        "compose",
                        side_effect=lambda *a, **kw: calls.append(a[2:])
                        or SimpleNamespace(stdout=""),
                    ),
                    patch.object(product, "verify_service_images"),
                    patch.object(product, "verify_running_images"),
                    patch.object(product, "gpu_check"),
                    patch.object(product, "wait_ready") as ready,
                    patch.object(product, "prepare_local_ollama") as external,
                    patch("builtins.print"),
                ):
                    self.assertEqual(product.main(), 0)
                self.assertIn(("build", service), calls)
                up = next(c for c in calls if c[0] == "up")
                self.assertEqual(up[-1], service)
                self.assertIn("--no-deps", up)
                ready.assert_called_once_with(8080, "127.0.0.1", (service,))
                external.assert_not_called()

    def test_remove_never_deletes_volumes_images_or_external_infrastructure(self):
        for service in (None, "tts"):
            values = {"COMPOSE_PROJECT_NAME": "isolated"}
            argv = ["product", "remove"] + (["--service", service] if service else [])
            with (
                patch("sys.argv", argv),
                patch.object(product, "load_env", return_value=values),
                patch.object(product, "validate_environment"),
                patch.object(product, "verify_project_ownership"),
                patch.object(product, "require_local_docker"),
                patch.object(
                    product, "run", return_value=SimpleNamespace(stdout="a" * 40)
                ),
                patch.object(product, "compose") as compose,
            ):
                self.assertEqual(product.main(), 0)
            actions = [c.args[2:] for c in compose.call_args_list]
            if service:
                self.assertEqual(actions, [("stop", "tts"), ("rm", "-f", "tts")])
            else:
                self.assertEqual(actions, [("down",)])
            self.assertFalse(
                any(
                    "-v" in a or "--rmi" in a or "--remove-orphans" in a
                    for a in actions
                )
            )


class PreflightCLITests(unittest.TestCase):
    def test_removed_gpu_ownership_guard_fails_instead_of_claiming_enforcement(self):
        with self.assertRaisesRegex(
            product.OperatorError, "process ownership is not inspected"
        ):
            product.checks(require_idle_gpu=True)

    def test_plan_does_not_claim_gpu_process_count(self):
        values = {
            "SPEECH_BIND_IP": "127.0.0.1",
            "SPEECH_PORT": "8080",
            "MODEL_STORE": "/models",
        }
        output = io.StringIO()
        with (
            patch("sys.argv", ["product", "plan", "--service", "stt"]),
            patch.object(product, "load_env", return_value=values),
            patch.object(
                product,
                "checks",
                return_value=(values, "a" * 40, "compose", "GPU 0", None),
            ),
            patch.object(product, "gateway_uses_local_ollama", return_value=False),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(product.main(), 0)
        self.assertIn("GPU process inventory: not inspected", output.getvalue())
        self.assertNotIn("Selected GPU compute processes: 0", output.getvalue())
        self.assertIn("No containers were started or changed.", output.getvalue())

    def test_blocked_preflight_returns_nonzero_and_ends_with_readiness(self):
        r = preflight.Report()
        r.add("Host", "FAIL", "Configuration", "Copy .env.example and chmod 600 .env.")
        output = io.StringIO()
        with (
            patch("sys.argv", ["product", "preflight"]),
            patch.object(preflight, "collect", return_value=r),
            patch.object(product, "load_env") as load,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(product.main(), 2)
        load.assert_not_called()
        self.assertTrue(output.getvalue().endswith("NOT READY TO INSTALL\n"))


class AdditionalBoundaryTests(unittest.TestCase):
    fixture = PreflightTests.fixture

    def test_gpu_unavailable_blocks_workers_and_does_not_block_gateway(self):
        with tempfile.TemporaryDirectory() as temp:
            p, _ = self.fixture(temp)
            original = p.run

            def no_gpu(args, **kw):
                if args[0] == "nvidia-smi":
                    raise FileNotFoundError()
                return original(args, **kw)

            p.run = no_gpu
            self.assertTrue(preflight.collect(p, service="tts").failed)
            self.assertFalse(preflight.collect(p, service="gateway").failed)

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
            preflight.cloud_credentials(Path("/unused"), {}, t)

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


class CloudComposeForwardingTests(unittest.TestCase):
    def test_private_credentials_forward_only_to_gateway(self):
        import os
        import shutil
        import subprocess

        if not shutil.which("docker"):
            self.skipTest("Docker Compose CLI unavailable")
        with tempfile.TemporaryDirectory() as temp:
            secret = Path(temp) / "cloud.env"
            secret.write_text("TEST_API_KEY=synthetic-private-credential\n")
            secret.chmod(0o600)
            env = os.environ.copy()
            env["GATEWAY_SECRETS_FILE"] = str(secret)
            env["GATEWAY_CONFIG"] = str(Path("configs/gateway.yaml").resolve())
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    ".env.example",
                    "-f",
                    "compose.yaml",
                    "config",
                    "--format",
                    "json",
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            services = json.loads(result.stdout)["services"]
            self.assertEqual(
                services["gateway"]["environment"]["TEST_API_KEY"],
                "synthetic-private-credential",
            )
            self.assertNotIn("TEST_API_KEY", services["stt"]["environment"])
            self.assertNotIn("TEST_API_KEY", services["tts"]["environment"])


class RunningImageIdentityTests(unittest.TestCase):
    def test_containerd_platform_digest_and_classic_id(self):
        for containerd in (False, True):
            image = {"Id": "sha256:index" if containerd else "sha256:config"}
            container = {"Image": "sha256:config"}
            if containerd:
                image["Descriptor"] = {
                    "mediaType": "application/vnd.oci.image.index.v1+json"
                }
                container["ImageManifestDescriptor"] = {"digest": "sha256:platform"}

            def run(args, **kw):
                value = (
                    ({"Id": "sha256:platform"} if "--platform" in args else image)
                    if args[:3] == ["docker", "image", "inspect"]
                    else container
                )
                return SimpleNamespace(stdout=json.dumps([value]))

            with (
                patch.object(product, "run", side_effect=run),
                patch.object(
                    product,
                    "compose",
                    return_value=SimpleNamespace(stdout="container-id"),
                ),
            ):
                product.verify_running_images(
                    {},
                    "revision",
                    {"gateway": {"reference": "ref", "image_id": image["Id"]}},
                )
                container["Image"] = "sha256:other"
                container["ImageManifestDescriptor"] = {"digest": "sha256:other"}
                with self.assertRaisesRegex(product.OperatorError, "running platform"):
                    product.verify_running_images(
                        {},
                        "revision",
                        {"gateway": {"reference": "ref", "image_id": image["Id"]}},
                    )


class InstallDriftTests(unittest.TestCase):
    def test_source_change_during_build_blocks_activation(self):
        values = {"SPEECH_BIND_IP": "127.0.0.1", "SPEECH_PORT": "8080"}
        observations = [
            (values, "a" * 40, "compose", "gpu", None),
            (values, "b" * 40, "compose", "gpu", None),
        ]
        with (
            patch("sys.argv", ["product", "install", "--service", "tts"]),
            patch.object(product, "load_env", return_value=values),
            patch.object(product, "checks", side_effect=observations),
            patch.object(product, "compose") as compose,
            patch.object(product, "verify_service_images", return_value={}),
            patch.object(product, "gpu_check"),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(product.main(), 2)
        self.assertTrue(any(c.args[2] == "build" for c in compose.call_args_list))
        self.assertFalse(any(c.args[2] == "up" for c in compose.call_args_list))


class OperatorEnvironmentTests(unittest.TestCase):
    def test_deployment_values_do_not_inherit_shell_overrides(self):
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "COMPOSE_PROJECT_NAME": "unrelated",
                "TTS_MODEL_STORE": "/unexpected",
                "COMPOSE_FILE": "unrelated.yaml",
                "SPEECH_API_TOKEN": "unexpected-secret",
                "GATEWAY_IMAGE": "unrelated",
            },
        ):
            product.set_compose_env({}, "a" * 40)
            self.assertEqual(os.environ["COMPOSE_PROJECT_NAME"], "speech-platform")
            for key in (
                "TTS_MODEL_STORE",
                "COMPOSE_FILE",
                "SPEECH_API_TOKEN",
                "GATEWAY_IMAGE",
            ):
                self.assertNotIn(key, os.environ)

    def test_remote_docker_endpoint_rejected_without_modifying_context(self):
        import os

        with (
            patch.dict(os.environ, {"DOCKER_HOST": "ssh://remote"}),
            patch.object(product, "run") as run,
        ):
            with self.assertRaisesRegex(product.OperatorError, "local Unix"):
                product.require_local_docker()
        run.assert_not_called()

    def test_selected_status_is_forwarded_to_compose(self):
        with (
            patch("sys.argv", ["product", "status", "--service", "tts"]),
            patch.object(product, "load_env", return_value={}),
            patch.object(product, "operational_values", return_value=({}, "a" * 40)),
            patch.object(product, "compose") as compose,
        ):
            self.assertEqual(product.main(), 0)
        self.assertEqual(compose.call_args.args[2:], ("ps", "tts"))


class DockerContextPrecedenceTests(unittest.TestCase):
    def test_remote_context_cannot_hide_behind_local_docker_host(self):
        import os

        with (
            patch.dict(
                os.environ,
                {
                    "DOCKER_HOST": "unix:///var/run/docker.sock",
                    "DOCKER_CONTEXT": "remote",
                },
            ),
            patch.object(
                product,
                "run",
                return_value=SimpleNamespace(
                    stdout=json.dumps(
                        [{"Endpoints": {"docker": {"Host": "ssh://remote"}}}]
                    )
                ),
            ) as run,
        ):
            with self.assertRaises(product.OperatorError):
                product.require_local_docker()
        self.assertEqual(
            run.call_args.args[0], ["docker", "context", "inspect", "remote"]
        )


class GPUProbeCleanupTests(unittest.TestCase):
    def test_failed_probe_only_cleans_its_unique_container(self):
        rendered = {"services": {"tts": {"image": "qualified-image"}}}
        calls = []

        def run(args, **kw):
            calls.append(args)
            if args[:2] == ["docker", "run"]:
                raise product.OperatorError("deadline")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            patch.object(
                product,
                "compose",
                return_value=SimpleNamespace(stdout=json.dumps(rendered)),
            ),
            patch.object(product, "run", side_effect=run),
        ):
            with self.assertRaisesRegex(
                product.OperatorError, "services were not started"
            ):
                product.gpu_check({}, "revision", ["tts"])
        name = calls[0][calls[0].index("--name") + 1]
        self.assertTrue(name.startswith("speech-platform-gpu-check-"))
        self.assertEqual(calls[1], ["docker", "rm", "-f", name])

    def test_unconfirmed_probe_cleanup_is_explicit(self):
        def run(args, **kw):
            if args[:2] == ["docker", "run"]:
                raise product.OperatorError("deadline")
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon unavailable")

        with (
            patch.object(
                product,
                "compose",
                return_value=SimpleNamespace(
                    stdout=json.dumps(
                        {"services": {"stt": {"image": "qualified-image"}}}
                    )
                ),
            ),
            patch.object(product, "run", side_effect=run),
        ):
            with self.assertRaisesRegex(product.OperatorError, "cleanup unconfirmed"):
                product.gpu_check({}, "revision", ["stt"])
