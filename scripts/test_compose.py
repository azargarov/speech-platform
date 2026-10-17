"""Regression checks for Compose Gateway publication and worker isolation."""

import unittest

from scripts.check_compose import validate


def rendered(port=8080, bind="127.0.0.1"):
    return {
        "networks": {"speech": {"internal": True}},
        "services": {
            "gateway": {
                "environment": {"SPEECH_LISTEN_PORT": str(port)},
                "ports": [{"host_ip": bind, "published": "8080", "target": port}],
                "read_only": True,
                "user": "65532:65532",
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "mem_limit": "134217728",
                "cpus": 1,
                "pids_limit": 128,
                "networks": {"speech": None},
            },
            "stt": worker(),
            "tts": worker(),
        },
    }


def worker():
    return {
        "read_only": True,
        "user": "65532:65532",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": "268435456",
        "cpus": 1,
        "pids_limit": 128,
        "networks": {"speech": None},
    }


class ComposeConfig(unittest.TestCase):
    def test_default_configuration_and_loopback_binding(self):
        validate(rendered(), 8080, "127.0.0.1")

    def test_port_override(self):
        validate(rendered(8765), 8765, "127.0.0.1")

    def test_invalid_port(self):
        with self.assertRaisesRegex(ValueError, "1..65535"):
            validate(rendered(0), 0, "127.0.0.1")

    def test_inconsistent_port_mapping(self):
        config = rendered(8765)
        config["services"]["gateway"]["ports"][0]["target"] = 8080
        with self.assertRaisesRegex(ValueError, "published port/bind"):
            validate(config, 8765, "127.0.0.1")

    def test_invalid_bind_address(self):
        with self.assertRaisesRegex(ValueError, "IP address"):
            validate(rendered(bind="not an ip"), 8080, "not an ip")

    def test_worker_isolation(self):
        config = rendered()
        config["services"]["stt"]["ports"] = [
            {"host_ip": "127.0.0.1", "published": "8081", "target": 8081}
        ]
        with self.assertRaisesRegex(ValueError, "private and independent"):
            validate(config, 8080, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
