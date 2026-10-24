import json
import errno
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import os

from scripts import product_deployment


class ProductDeploymentTests(unittest.TestCase):
    IMAGE_ID = (
        "sha256:" + "5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159"
    )
    REVISION = "c3f0079227af573f7715640afa5b229a22c46ab6"

    def test_gateway_token_is_required_for_loopback_and_external_bind(self):
        values = {
            "MODEL_STORE": "/models",
            "MODEL_MANIFEST_SHA256": product_deployment.DIGEST,
            "TTS_MODEL_MANIFEST_SHA256": product_deployment.TTS_DIGEST,
            "SPEECH_BIND_IP": "127.0.0.1",
            "SPEECH_PORT": "8080",
            "STT_GPU_DEVICE": "0",
            "TTS_GPU_DEVICE": "0",
        }
        with self.assertRaisesRegex(
            product_deployment.OperatorError, "every deployment"
        ):
            product_deployment.validate_environment(values)
        values["SPEECH_API_TOKEN"] = "short"
        with self.assertRaisesRegex(
            product_deployment.OperatorError, "every deployment"
        ):
            product_deployment.validate_environment(values)
        values["SPEECH_API_TOKEN"] = "synthetic-deployment-token-0123456789"
        product_deployment.validate_environment(values)
        values["SPEECH_BIND_IP"] = "0.0.0.0"
        values["SPEECH_API_URL"] = "https://speech.example.test"
        product_deployment.validate_environment(values)

    def _valid_gateway_image(self, **overrides):
        image = {
            "Id": self.IMAGE_ID,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": self.REVISION,
                    "com.speech-platform.service": "gateway",
                    "com.speech-platform.service-role": "gateway",
                    "com.speech-platform.runtime-variant": "foundation",
                }
            },
        }
        image.update(overrides)
        return image

    def _verification_run(self, image_result):
        def run(args, **_kwargs):
            if args[:3] == ["git", "status", "--porcelain"]:
                return SimpleNamespace(returncode=0, stdout="")
            if args[:3] == ["git", "merge-base", "--is-ancestor"]:
                return SimpleNamespace(returncode=0, stdout="")
            if args[:3] == ["git", "diff", "--quiet"]:
                return SimpleNamespace(returncode=0, stdout="")
            if args[:3] == ["docker", "image", "inspect"]:
                return image_result
            raise AssertionError(f"unexpected command: {args}")

        return run

    def test_no_build_verifies_exact_configured_local_image(self):
        rendered = json.dumps(
            {
                "services": {
                    "gateway": {"image": f"speech-platform-gateway:{self.REVISION}"}
                }
            }
        )
        with (
            patch.object(
                product_deployment,
                "compose",
                return_value=SimpleNamespace(stdout=rendered),
            ),
            patch.object(
                product_deployment,
                "run",
                side_effect=self._verification_run(
                    SimpleNamespace(
                        returncode=0,
                        stdout=json.dumps([self._valid_gateway_image()]),
                    )
                ),
            ) as run,
        ):
            result = product_deployment.verify_gateway_image(
                {}, self.REVISION, self.IMAGE_ID, self.REVISION
            )
        self.assertEqual(
            result["reference"], f"speech-platform-gateway:{self.REVISION}"
        )
        self.assertEqual(result["image_id"], self.IMAGE_ID)
        self.assertEqual(result["revision"], self.REVISION)
        self.assertEqual(
            run.call_args.args[0],
            [
                "docker",
                "image",
                "inspect",
                f"speech-platform-gateway:{self.REVISION}",
            ],
        )

    def test_no_build_rejects_missing_or_ambiguous_image_tag(self):
        rendered = json.dumps(
            {
                "services": {
                    "gateway": {"image": f"speech-platform-gateway:{self.REVISION}"}
                }
            }
        )
        for result, message in (
            (SimpleNamespace(returncode=1, stdout=""), "not available locally"),
            (SimpleNamespace(returncode=0, stdout="[]"), "missing or ambiguous"),
            (
                SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(
                        [self._valid_gateway_image(), self._valid_gateway_image()]
                    ),
                ),
                "missing or ambiguous",
            ),
        ):
            with (
                self.subTest(message=message),
                patch.object(
                    product_deployment,
                    "compose",
                    return_value=SimpleNamespace(stdout=rendered),
                ),
                patch.object(
                    product_deployment,
                    "run",
                    side_effect=self._verification_run(result),
                ),
                self.assertRaisesRegex(product_deployment.OperatorError, message),
            ):
                product_deployment.verify_gateway_image(
                    {}, self.REVISION, self.IMAGE_ID, self.REVISION
                )

    def test_no_build_rejects_image_id_mismatch_and_invalid_inspection(self):
        rendered = json.dumps(
            {
                "services": {
                    "gateway": {"image": f"speech-platform-gateway:{self.REVISION}"}
                }
            }
        )
        cases = (
            (self._valid_gateway_image(Id="sha256:" + "0" * 64), "image ID"),
            ({"Id": self.IMAGE_ID}, "required OCI labels"),
        )
        for image, message in cases:
            with (
                self.subTest(message=message),
                patch.object(
                    product_deployment,
                    "compose",
                    return_value=SimpleNamespace(stdout=rendered),
                ),
                patch.object(
                    product_deployment,
                    "run",
                    side_effect=self._verification_run(
                        SimpleNamespace(returncode=0, stdout=json.dumps([image]))
                    ),
                ),
                self.assertRaisesRegex(product_deployment.OperatorError, message),
            ):
                product_deployment.verify_gateway_image(
                    {}, self.REVISION, self.IMAGE_ID, self.REVISION
                )

    def test_no_build_rejects_revision_role_service_and_variant_mismatches(self):
        rendered = json.dumps(
            {
                "services": {
                    "gateway": {"image": f"speech-platform-gateway:{self.REVISION}"}
                }
            }
        )
        mutations = (
            ("org.opencontainers.image.revision", "0" * 40, "revision"),
            ("com.speech-platform.service-role", "stt", "service-role"),
            ("com.speech-platform.service", "tts", "service"),
            ("com.speech-platform.runtime-variant", "other", "runtime-variant"),
        )
        for label, value, message in mutations:
            with self.subTest(label=label):
                image = self._valid_gateway_image()
                image["Config"]["Labels"][label] = value
                with (
                    patch.object(
                        product_deployment,
                        "compose",
                        return_value=SimpleNamespace(stdout=rendered),
                    ),
                    patch.object(
                        product_deployment,
                        "run",
                        side_effect=self._verification_run(
                            SimpleNamespace(returncode=0, stdout=json.dumps([image]))
                        ),
                    ),
                    self.assertRaisesRegex(product_deployment.OperatorError, message),
                ):
                    product_deployment.verify_gateway_image(
                        {}, self.REVISION, self.IMAGE_ID, self.REVISION
                    )

    def test_no_build_options_require_gateway_and_full_expected_id(self):
        cases = (
            (
                "install",
                None,
                True,
                self.IMAGE_ID,
                None,
                self.REVISION,
                None,
                "--service gateway",
            ),
            (
                "install",
                "stt",
                True,
                self.IMAGE_ID,
                None,
                self.REVISION,
                None,
                "--service gateway",
            ),
            (
                "status",
                "gateway",
                True,
                self.IMAGE_ID,
                None,
                self.REVISION,
                None,
                "plan/install",
            ),
            (
                "install",
                "gateway",
                True,
                None,
                None,
                self.REVISION,
                None,
                "requires GATEWAY_EXPECTED_IMAGE_ID",
            ),
            (
                "install",
                "gateway",
                True,
                "sha256:abcd",
                None,
                self.REVISION,
                None,
                "full sha256 image ID",
            ),
            (
                "install",
                "gateway",
                True,
                self.IMAGE_ID,
                "sha256:" + "0" * 64,
                self.REVISION,
                None,
                "conflicts",
            ),
            (
                "install",
                "gateway",
                True,
                self.IMAGE_ID,
                None,
                "c3f0079",
                None,
                "full Git revision",
            ),
            (
                "install",
                "gateway",
                False,
                self.IMAGE_ID,
                None,
                self.REVISION,
                None,
                "requires --no-build",
            ),
        )
        for (
            command,
            service,
            no_build,
            expected,
            configured,
            expected_revision,
            configured_revision,
            message,
        ) in cases:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(product_deployment.OperatorError, message),
            ):
                product_deployment.validate_no_build_options(
                    command,
                    service,
                    no_build,
                    expected,
                    configured,
                    expected_revision,
                    configured_revision,
                )

    def test_no_build_plan_reports_verified_image(self):
        values = {
            "COMPOSE_PROJECT_NAME": "speech-platform",
            "SPEECH_BIND_IP": "127.0.0.1",
            "SPEECH_PORT": "8080",
            "MODEL_STORE": "/models",
        }
        with (
            patch.object(
                sys,
                "argv",
                [
                    "product_deployment.py",
                    "plan",
                    "--service",
                    "gateway",
                    "--no-build",
                    "--expected-image-id",
                    self.IMAGE_ID,
                    "--expected-source-revision",
                    self.REVISION,
                ],
            ),
            patch.object(product_deployment, "load_env", return_value=values),
            patch.object(
                product_deployment,
                "checks",
                return_value=(values, self.REVISION, "compose", "gpu", None),
            ),
            patch.object(
                product_deployment,
                "verify_gateway_image",
                return_value={
                    "reference": f"speech-platform-gateway:{self.REVISION}",
                    "image_id": self.IMAGE_ID,
                    "revision": self.REVISION,
                    "runtime_variant": "foundation",
                },
            ),
            patch.object(
                product_deployment, "gateway_uses_local_ollama", return_value=False
            ),
            patch("builtins.print") as output,
        ):
            self.assertEqual(product_deployment.main(), 0)
        rendered = " ".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("No-build mode: enabled", rendered)
        self.assertIn(self.IMAGE_ID, rendered)
        self.assertIn(self.REVISION, rendered)

    def test_no_build_install_skips_build_never_pulls_and_preserves_gateway_checks(
        self,
    ):
        values = {"SPEECH_BIND_IP": "127.0.0.1", "SPEECH_PORT": "8080"}
        events = []

        def compose(_values, _revision, *args, **_kwargs):
            events.append(("compose", args))
            return SimpleNamespace(stdout="")

        def verify(*_args):
            events.append(("image-verify", None))
            return {
                "reference": "speech-platform-gateway:test",
                "image_id": self.IMAGE_ID,
            }

        with (
            patch.object(
                sys,
                "argv",
                [
                    "product_deployment.py",
                    "install",
                    "--service",
                    "gateway",
                    "--no-build",
                    "--expected-image-id",
                    self.IMAGE_ID,
                    "--expected-source-revision",
                    self.REVISION,
                ],
            ),
            patch.object(product_deployment, "load_env", return_value=values),
            patch.object(
                product_deployment,
                "checks",
                return_value=(values, self.REVISION, "compose", "gpu", None),
            ) as checks,
            patch.object(
                product_deployment,
                "require_existing_workers_healthy",
                side_effect=lambda *_args: events.append(("workers", None)),
            ),
            patch.object(
                product_deployment, "gateway_uses_local_ollama", return_value=True
            ),
            patch.object(
                product_deployment,
                "prepare_local_ollama",
                side_effect=lambda *_args: events.append(("network", None))
                or {
                    "network": "reused",
                    "network_name": "private",
                    "attachment": "reused",
                    "container_name": "ollama",
                },
            ),
            patch.object(
                product_deployment, "verify_gateway_image", side_effect=verify
            ),
            patch.object(product_deployment, "compose", side_effect=compose),
            patch.object(
                product_deployment,
                "wait_ready",
                side_effect=lambda *_args: events.append(("ready", None)),
            ),
            patch.object(product_deployment, "verify_running_images"),
            patch("builtins.print"),
        ):
            self.assertEqual(product_deployment.main(), 0)

        self.assertEqual(checks.call_count, 2)
        labels = [event[0] for event in events]
        self.assertEqual(labels.count("image-verify"), 2)
        self.assertLess(labels.index("image-verify"), labels.index("network"))
        up = next(
            args for kind, args in events if kind == "compose" and args[0] == "up"
        )
        self.assertIn("--no-build", up)
        self.assertIn("--pull", up)
        self.assertIn("never", up)
        self.assertIn("--no-deps", up)
        self.assertEqual(up[-1], "gateway")
        provider_check = next(
            args for kind, args in events if kind == "compose" and args[0] == "run"
        )
        self.assertIn("--pull", provider_check)
        self.assertIn("never", provider_check)
        self.assertIn("--check-ollama", provider_check)
        self.assertFalse(
            any("build" in args for kind, args in events if kind == "compose")
        )

    def test_normal_gateway_install_retains_existing_build_path(self):
        values = {"SPEECH_BIND_IP": "127.0.0.1", "SPEECH_PORT": "8080"}
        compose_calls = []
        with (
            patch.object(
                sys,
                "argv",
                ["product_deployment.py", "install", "--service", "gateway"],
            ),
            patch.object(product_deployment, "load_env", return_value=values),
            patch.object(
                product_deployment,
                "checks",
                return_value=(values, self.REVISION, "compose", "gpu", None),
            ),
            patch.object(product_deployment, "require_existing_workers_healthy"),
            patch.object(
                product_deployment, "gateway_uses_local_ollama", return_value=False
            ),
            patch.object(
                product_deployment,
                "compose",
                side_effect=lambda _values,
                _revision,
                *args,
                **_kwargs: compose_calls.append(args) or SimpleNamespace(stdout=""),
            ),
            patch.object(product_deployment, "wait_ready"),
            patch.object(product_deployment, "verify_service_images"),
            patch.object(product_deployment, "gpu_check"),
            patch.object(product_deployment, "verify_running_images"),
            patch("builtins.print"),
        ):
            self.assertEqual(product_deployment.main(), 0)
        self.assertIn(("build", "gateway"), compose_calls)
        up = next(args for args in compose_calls if args[0] == "up")
        self.assertEqual(
            up, ("up", "-d", "--no-build", "--pull", "never", "--no-deps", "gateway")
        )

    def test_plan_reports_local_ollama_requirement_from_selected_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "gateway.yaml"
            config.write_text(
                """text_transform:
  enabled: true
  providers:
    - {id: local, type: ollama, locality: local, endpoint: http://ollama:11434/api/generate}
  models:
    - {id: model, provider: local, enabled: true}
"""
            )
            values = {
                "COMPOSE_PROJECT_NAME": "speech-platform",
                "SPEECH_BIND_IP": "127.0.0.1",
                "SPEECH_PORT": "8080",
                "MODEL_STORE": "/models",
                "OLLAMA_NETWORK_NAME": "speech-platform_ollama_private",
                "OLLAMA_CONTAINER_NAME": "ollama",
            }
            with (
                patch.object(sys, "argv", ["product_deployment.py", "plan"]),
                patch.object(
                    product_deployment,
                    "checks",
                    return_value=(values, "revision", "compose", "gpu", None),
                ),
                patch.object(product_deployment, "load_env", return_value=values),
                patch.object(
                    product_deployment, "gateway_config_path", return_value=config
                ),
                patch("builtins.print") as output,
            ):
                self.assertEqual(product_deployment.main(), 0)
            rendered = " ".join(str(call.args[0]) for call in output.call_args_list)
            self.assertIn("Local Ollama: enabled", rendered)
            self.assertIn("speech-platform_ollama_private", rendered)

    def test_ollama_network_is_selected_only_for_enabled_local_ollama_models(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "gateway.yaml"
            config.write_text("listen_port: 8080\n")
            self.assertFalse(product_deployment.gateway_uses_local_ollama(config))
            config.write_text(
                """text_transform:
  enabled: false
  providers:
    - {id: local, type: ollama, locality: local, endpoint: http://ollama:11434/api/generate}
  models:
    - {id: model, provider: local, enabled: true}
"""
            )
            self.assertFalse(product_deployment.gateway_uses_local_ollama(config))
            config.write_text(
                """text_transform:
  enabled: true
  providers:
    - {id: cloud, type: openai_compatible, locality: cloud, endpoint: https://example.invalid/v1/chat/completions}
  models:
    - {id: model, provider: cloud, enabled: true}
"""
            )
            self.assertFalse(product_deployment.gateway_uses_local_ollama(config))
            config.write_text(
                """text_transform:
  enabled: true
  providers:
    - {id: local, type: ollama, locality: local, endpoint: http://ollama:11434/api/generate}
  models:
    - {id: model, provider: local, enabled: true}
"""
            )
            self.assertTrue(product_deployment.gateway_uses_local_ollama(config))

    def test_local_ollama_config_requires_the_network_alias_and_port(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "gateway.yaml"
            config.write_text(
                """text_transform:
  enabled: true
  providers:
    - {id: local, type: ollama, locality: local, endpoint: http://host.docker.internal:11434/api/generate}
  models:
    - {id: model, provider: local, enabled: true}
"""
            )
            with self.assertRaisesRegex(
                product_deployment.OperatorError, "ollama:11434"
            ):
                product_deployment.gateway_uses_local_ollama(config)

    def test_gateway_config_override_is_resolved_inside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private" / "deployment"
            private.mkdir(parents=True)
            configs = root / "configs"
            configs.mkdir()
            (configs / "gateway.yaml").write_text("listen_port: 8080\n")
            config = private / "gateway.yaml"
            config.write_text("listen_port: 8080\n")
            with patch.object(product_deployment, "ROOT", root):
                resolved = product_deployment.gateway_config_path(
                    {"GATEWAY_CONFIG": "private/deployment/gateway.yaml"}
                )
                self.assertEqual(resolved, config.resolve())
                self.assertFalse(product_deployment.gateway_uses_local_ollama(resolved))

                outside = root.parent / "outside-gateway.yaml"
                outside.write_text("listen_port: 8080\n")
                with self.assertRaisesRegex(
                    product_deployment.OperatorError, "inside the repository"
                ):
                    product_deployment.gateway_config_path(
                        {"GATEWAY_CONFIG": str(outside)}
                    )

                with self.assertRaisesRegex(
                    product_deployment.OperatorError, "parent-directory traversal"
                ):
                    product_deployment.gateway_config_path(
                        {"GATEWAY_CONFIG": "private/../configs/gateway.yaml"}
                    )

                link = private / "linked.yaml"
                link.symlink_to(config)
                with self.assertRaisesRegex(
                    product_deployment.OperatorError, "symlinks"
                ):
                    product_deployment.gateway_config_path(
                        {"GATEWAY_CONFIG": str(link)}
                    )

    def test_compose_uses_optional_overlay_only_for_local_ollama(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_dir = root / "configs"
            config_dir.mkdir()
            gateway_config = config_dir / "gateway.yaml"
            gateway_config.write_text("listen_port: 8080\n")
            values = {}
            with (
                patch.object(product_deployment, "ROOT", root),
                patch.object(
                    product_deployment,
                    "COMPOSE",
                    ["docker", "compose", "-f", "root.yaml"],
                ),
                patch.object(
                    product_deployment,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ) as run,
                patch.dict(os.environ, {}, clear=False),
            ):
                product_deployment.compose(values, "revision", "config", "--quiet")
                self.assertNotIn("compose.ollama.yaml", run.call_args.args[0])
                gateway_config.write_text(
                    """text_transform:
  enabled: true
  providers:
    - {id: local, type: ollama, locality: local, endpoint: http://ollama:11434/api/generate}
  models:
    - {id: model, provider: local, enabled: true}
"""
                )
                product_deployment.compose(values, "revision", "config", "--quiet")
                self.assertTrue(
                    any("compose.ollama.yaml" in arg for arg in run.call_args.args[0])
                )

                private_config = root / "private" / "gateway.yaml"
                private_config.parent.mkdir()
                private_config.write_text(gateway_config.read_text())
                values["GATEWAY_CONFIG"] = str(private_config)
                product_deployment.compose(values, "revision", "config", "--quiet")
                self.assertEqual(os.environ["GATEWAY_CONFIG"], str(private_config))
                self.assertTrue(
                    any("compose.ollama.yaml" in arg for arg in run.call_args.args[0])
                )

    def test_gateway_port_preflight_accepts_a_free_port(self):
        probe = SimpleNamespace(bind=lambda _address: None, close=lambda: None)
        with (
            patch.object(product_deployment.socket, "socket", return_value=probe),
            patch.object(product_deployment, "run") as run,
        ):
            product_deployment.check_gateway_port(
                "127.0.0.1", 8080, {}, owns_project=False
            )
        run.assert_not_called()

    def test_gateway_port_preflight_accepts_canonical_project_gateway(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compose = root / "compose.yaml"
            compose.touch()
            container = {
                "State": {"Running": True},
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": "speech-platform",
                        "com.docker.compose.service": "gateway",
                        "com.docker.compose.project.working_dir": str(root),
                        "com.docker.compose.project.config_files": str(compose),
                    }
                },
                "NetworkSettings": {
                    "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
                },
            }
            probe = SimpleNamespace(
                bind=lambda _address: (_ for _ in ()).throw(
                    OSError(errno.EADDRINUSE, "busy")
                ),
                close=lambda: None,
            )

            def docker_run(args, **_kwargs):
                if args[1] == "ps":
                    return SimpleNamespace(stdout="gateway-id\n")
                return SimpleNamespace(stdout=json.dumps([container]))

            with (
                patch.object(product_deployment, "ROOT", root),
                patch.object(product_deployment.socket, "socket", return_value=probe),
                patch.object(product_deployment, "run", side_effect=docker_run),
            ):
                product_deployment.check_gateway_port(
                    "127.0.0.1", 8080, {}, owns_project=True
                )

    def test_gateway_port_preflight_rejects_foreign_port_owner(self):
        probe = SimpleNamespace(
            bind=lambda _address: (_ for _ in ()).throw(
                OSError(errno.EADDRINUSE, "busy")
            ),
            close=lambda: None,
        )
        with (
            patch.object(product_deployment.socket, "socket", return_value=probe),
            patch.object(
                product_deployment,
                "run",
                return_value=SimpleNamespace(stdout=""),
            ),
            self.assertRaisesRegex(product_deployment.OperatorError, "already in use"),
        ):
            product_deployment.check_gateway_port(
                "127.0.0.1", 8080, {}, owns_project=False
            )

    def test_gateway_port_preflight_rejects_foreign_compose_project(self):
        probe = SimpleNamespace(
            bind=lambda _address: (_ for _ in ()).throw(
                OSError(errno.EADDRINUSE, "busy")
            ),
            close=lambda: None,
        )
        foreign = {
            "State": {"Running": True},
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "other-project",
                    "com.docker.compose.service": "gateway",
                    "com.docker.compose.project.working_dir": "/other",
                    "com.docker.compose.project.config_files": "/other/compose.yaml",
                }
            },
            "NetworkSettings": {
                "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}
            },
        }

        def docker_run(args, **_kwargs):
            if args[1] == "ps":
                return SimpleNamespace(stdout="foreign-id\n")
            return SimpleNamespace(stdout=json.dumps([foreign]))

        with (
            patch.object(product_deployment.socket, "socket", return_value=probe),
            patch.object(product_deployment, "run", side_effect=docker_run),
            self.assertRaisesRegex(product_deployment.OperatorError, "already in use"),
        ):
            product_deployment.check_gateway_port(
                "127.0.0.1", 8080, {}, owns_project=True
            )

    def test_compose_readiness_accepts_json_array(self):
        services = [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in ("gateway", "stt", "tts")
        ]
        self.assertEqual(
            product_deployment.parse_compose_readiness(json.dumps(services)), services
        )

    def test_single_selected_service_json_object_is_accepted(self):
        body = json.dumps({"Service": "tts", "State": "running", "Health": "healthy"})
        self.assertEqual(
            product_deployment.parse_compose_readiness(body, expected={"tts"})[0][
                "Service"
            ],
            "tts",
        )

    def test_compose_readiness_accepts_newline_delimited_json_objects(self):
        services = [
            {"Service": name, "State": "running", "Health": "healthy"}
            for name in ("gateway", "stt", "tts")
        ]
        output = "\n".join(json.dumps(service) for service in services) + "\n"
        self.assertEqual(product_deployment.parse_compose_readiness(output), services)

    def test_compose_readiness_rejects_malformed_output_and_wrong_services(self):
        for output in (
            '{"Service":"gateway"}\nnot-json',
            json.dumps([{"Service": "gateway"}]),
            "\n".join(
                json.dumps({"Service": name}) for name in ("gateway", "gateway", "tts")
            ),
        ):
            with (
                self.subTest(output=output),
                self.assertRaises(product_deployment.OperatorError),
            ):
                product_deployment.parse_compose_readiness(output)

    def test_env_reader_rejects_unknown_and_duplicate_settings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text("SPEECH_PORT=8080\n")
            (root / ".env").chmod(0o600)
            with patch.object(product_deployment, "ROOT", root):
                self.assertEqual(product_deployment.load_env(), {"SPEECH_PORT": "8080"})
                (root / ".env").write_text("MYSTERY=value\n")
                (root / ".env").chmod(0o600)
                with self.assertRaises(product_deployment.OperatorError):
                    product_deployment.load_env()
                (root / ".env").write_text("SPEECH_PORT=8080\nSPEECH_PORT=8081\n")
                (root / ".env").chmod(0o600)
                with self.assertRaises(product_deployment.OperatorError):
                    product_deployment.load_env()

    def test_compose_project_collision_with_another_deployment_fails(self):
        with patch.object(
            product_deployment,
            "run",
            return_value=SimpleNamespace(
                stdout=json.dumps(
                    [{"Name": "speech-platform", "ConfigFiles": "/other/compose.yaml"}]
                )
            ),
        ):
            with self.assertRaisesRegex(
                product_deployment.OperatorError, "already owned"
            ):
                product_deployment.verify_project_ownership({})

    def test_canonical_compose_project_is_recognized(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compose = root / "compose.yaml"
            compose.touch()
            with (
                patch.object(product_deployment, "ROOT", root),
                patch.object(
                    product_deployment,
                    "run",
                    return_value=SimpleNamespace(
                        stdout=json.dumps(
                            [{"Name": "speech-platform", "ConfigFiles": str(compose)}]
                        )
                    ),
                ),
            ):
                product_deployment.verify_project_ownership({})


if __name__ == "__main__":
    unittest.main()
