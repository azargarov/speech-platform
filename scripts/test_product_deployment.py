import json
import errno
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import product_deployment


class ProductDeploymentTests(unittest.TestCase):
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
