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
                    return_value=(values, "revision", "compose", "gpu", 0),
                ),
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
