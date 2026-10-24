from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.service_deployment_profile import (
    load_gateway_config,
    load_service_profile,
)


class ServiceDeploymentProfileTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "schema_version": 1,
            "project_name": "isolated-services",
            "config_reader_gid": 988,
            "gateway": {
                "host_port": 18080,
                "memory_limit": "128m",
                "cpu_limit": 1.0,
                "pids_limit": 128,
            },
            "tts": {"memory_limit": "256m", "cpu_limit": 1.0, "pids_limit": 128},
            "readiness": {
                "timeout_seconds": 120,
                "poll_interval_seconds": 2,
                "probe_timeout_seconds": 2,
            },
        }
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "services.yaml"

    def tearDown(self):
        self.temporary.cleanup()

    def load(self, value):
        self.path.write_text(yaml.safe_dump(value), encoding="utf-8")
        return load_service_profile(self.path)

    def test_valid_profile_normalizes_cpu_and_retains_loopback_port(self):
        loaded = self.load(self.profile)
        self.assertEqual(loaded["project_name"], "isolated-services")
        self.assertEqual(loaded["gateway"]["host_port"], 18080)
        self.assertEqual(loaded["gateway"]["cpu_limit"], 1.0)
        self.assertEqual(loaded["config_reader_gid"], 988)

    def test_unknown_and_missing_profile_fields_fail(self):
        unknown = copy.deepcopy(self.profile)
        unknown["credential"] = "not-a-secret"
        with self.assertRaisesRegex(ValueError, "unsupported credential"):
            self.load(unknown)
        missing = copy.deepcopy(self.profile)
        del missing["readiness"]
        with self.assertRaisesRegex(ValueError, "missing readiness"):
            self.load(missing)

    def test_invalid_project_port_group_and_resources_fail(self):
        cases = (
            ("project_name", "../foreign", "project_name"),
            ("config_reader_gid", 0, "config_reader_gid"),
        )
        for key, value, message in cases:
            with self.subTest(key=key):
                invalid = copy.deepcopy(self.profile)
                invalid[key] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.load(invalid)
        for port in (80, 65536, True):
            with self.subTest(port=port):
                invalid = copy.deepcopy(self.profile)
                invalid["gateway"]["host_port"] = port
                with self.assertRaisesRegex(ValueError, "host_port"):
                    self.load(invalid)
        invalid = copy.deepcopy(self.profile)
        invalid["tts"]["memory_limit"] = "0m"
        with self.assertRaisesRegex(ValueError, "memory_limit"):
            self.load(invalid)

    def test_readiness_timeout_relationship_is_validated(self):
        invalid = copy.deepcopy(self.profile)
        invalid["readiness"]["probe_timeout_seconds"] = 3
        with self.assertRaisesRegex(ValueError, "cannot exceed"):
            self.load(invalid)

    def test_tracked_gateway_configuration_is_strictly_validated(self):
        config = load_gateway_config("configs/gateway.yaml")
        self.assertEqual(config["listen_host"], "0.0.0.0")
        self.assertEqual(config["listen_port"], 8080)
        self.assertEqual(config["warmup_timeout"], "180s")
        self.assertFalse(config["groq_stt"]["enabled"])
        self.assertEqual(config["groq_stt"]["capacity"], 2)

    def test_groq_stt_configuration_is_validated_without_secrets(self):
        path = Path(self.temporary.name) / "gateway-groq.yaml"
        body = (
            "listen_host: 0.0.0.0\nlisten_port: 8080\nmax_header_bytes: 1024\n"
            "max_request_bytes: 2048\nread_timeout: 1s\nwrite_timeout: 20s\n"
            "idle_timeout: 1s\nshutdown_timeout: 1s\n"
            "groq_stt: {enabled: false, capacity: 2, model: whisper-large-v3-turbo, "
            "api_key_env: GROQ_STT_API_KEY}\n"
        )
        path.write_text(body, encoding="utf-8")
        self.assertFalse(load_gateway_config(path)["groq_stt"]["enabled"])
        for invalid, message in (
            (
                body.replace("enabled: false", 'enabled: "yes"'),
                "enabled must be boolean",
            ),
            (body.replace("capacity: 2", "capacity: 0"), "capacity must be 1 or 2"),
            (
                body.replace("whisper-large-v3-turbo", "unknown-model"),
                "model is unsupported",
            ),
            (body.replace("GROQ_STT_API_KEY", "bad-name"), "api_key_env is invalid"),
            (
                body.replace("api_key_env: GROQ_STT_API_KEY", "extra: true"),
                "fields are invalid",
            ),
        ):
            path.write_text(invalid, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, message):
                load_gateway_config(path)

    def test_gateway_config_rejects_unknown_fields_and_non_container_bind(self):
        path = Path(self.temporary.name) / "gateway.yaml"
        path.write_text(
            "listen_host: 127.0.0.1\nlisten_port: 8080\nmax_header_bytes: 1024\n"
            "max_request_bytes: 2048\nread_timeout: 1s\nwrite_timeout: 1s\n"
            "idle_timeout: 1s\nshutdown_timeout: 1s\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "container port"):
            load_gateway_config(path)
        body = path.read_text().replace(
            "listen_host: 127.0.0.1", "listen_host: 0.0.0.0"
        )
        path.write_text(body + "unknown: true\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported unknown"):
            load_gateway_config(path)

    def test_gateway_warmup_timeout_is_bounded_by_write_timeout(self):
        path = Path(self.temporary.name) / "gateway-warmup.yaml"
        body = (
            "listen_host: 0.0.0.0\nlisten_port: 8080\nmax_header_bytes: 1024\n"
            "max_request_bytes: 2048\nread_timeout: 1s\nwrite_timeout: 180s\n"
            "idle_timeout: 1s\nshutdown_timeout: 1s\nwarmup_timeout: 120s\n"
        )
        path.write_text(body, encoding="utf-8")
        self.assertEqual(load_gateway_config(path)["warmup_timeout"], "120s")
        path.write_text(body.replace("120s", "3m"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "warmup_timeout"):
            load_gateway_config(path)


if __name__ == "__main__":
    unittest.main()
