import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import product_deployment


class ProductDeploymentTests(unittest.TestCase):
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
