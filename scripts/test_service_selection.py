from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.service_selection import ServiceSelectionError, resolve_services
from scripts.stt_deployment import run_deployment


def release(**dependencies):
    return {name: {"dependencies": requires} for name, requires in dependencies.items()}


class ServiceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.services = release(gateway=[], stt=[], tts=["gateway", "stt"])

    def test_explicit_stt_selection(self):
        self.assertEqual(resolve_services(self.services, ["stt"], "stt"), ["stt"])

    def test_explicit_tts_selection_includes_dependencies(self):
        self.assertEqual(
            resolve_services(self.services, ["gateway", "stt", "tts"], "tts"),
            ["gateway", "stt", "tts"],
        )

    def test_explicit_gateway_selection(self):
        self.assertEqual(
            resolve_services(self.services, ["gateway", "stt"], "gateway"),
            ["gateway"],
        )

    def test_default_selects_all_enabled_services(self):
        self.assertEqual(
            resolve_services(self.services, ["stt", "gateway"]),
            ["gateway", "stt"],
        )

    def test_unknown_and_disabled_services_fail(self):
        with self.assertRaisesRegex(ServiceSelectionError, "unknown service"):
            resolve_services(self.services, ["stt"], "unknown")
        with self.assertRaisesRegex(ServiceSelectionError, "disabled"):
            resolve_services(self.services, ["stt"], "gateway")

    def test_missing_and_disabled_dependencies_fail(self):
        with self.assertRaisesRegex(ServiceSelectionError, "missing"):
            resolve_services(release(app=["absent"]), ["app"], "app")
        with self.assertRaisesRegex(ServiceSelectionError, "disabled"):
            resolve_services(self.services, ["tts", "stt"], "tts")

    def test_cycles_fail(self):
        cyclic = release(gateway=["stt"], stt=["gateway"])
        with self.assertRaisesRegex(ServiceSelectionError, "cycle"):
            resolve_services(cyclic, ["gateway", "stt"], "gateway")

    def test_dependency_and_root_order_are_deterministic(self):
        graph = release(app=["z", "b"], z=[], b=["a"], a=[])
        expected = ["a", "b", "z", "app"]
        for _ in range(5):
            self.assertEqual(
                resolve_services(graph, ["app", "z", "b", "a"], "app"),
                expected,
            )
        self.assertEqual(resolve_services(graph, ["z", "app", "b", "a"]), expected)

    def test_invalid_and_disabled_selection_fail_before_profile_or_docker(self):
        for service, enabled in (("unknown", ["stt"]), ("gateway", ["stt"])):
            with self.subTest(service=service):
                with (
                    patch("scripts.stt_deployment._load_selected_configs") as profile,
                    patch("scripts.stt_deployment._run") as docker,
                    self.assertRaises(ServiceSelectionError),
                ):
                    run_deployment(
                        "install",
                        service=service,
                        enabled_services=enabled,
                        profile_path="unused",
                        application_config="unused",
                        deployment_config="unused",
                        worker_config="unused",
                        release_path="releases/voiceservice-v0.1.2.yaml",
                        env_file="unused",
                    )
                profile.assert_not_called()
                docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
