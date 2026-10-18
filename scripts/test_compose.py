"""Regression checks for Compose Gateway publication and worker isolation."""

import unittest

from scripts.check_compose import validate, validate_cuda_deployment


def rendered(port=8080, bind="127.0.0.1"):
    return {
        "networks": {
            "stt_private": {"internal": True},
            "tts_private": {"internal": True},
        },
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
                "networks": {"stt_private": None, "tts_private": None},
            },
            "stt": worker("stt_private"),
            "tts": worker("tts_private"),
        },
    }


def worker(network):
    return {
        "read_only": True,
        "user": "65532:65532",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": "268435456",
        "cpus": 1,
        "pids_limit": 128,
        "networks": {network: None},
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

    def test_workers_must_not_share_network(self):
        config = rendered()
        config["services"]["tts"]["networks"] = {"stt_private": None}
        with self.assertRaisesRegex(ValueError, "TTS must connect only"):
            validate(config, 8080, "127.0.0.1")

    def test_gateway_must_connect_to_each_private_network(self):
        config = rendered()
        config["services"]["gateway"]["networks"] = {"stt_private": None}
        with self.assertRaisesRegex(ValueError, "Gateway must connect"):
            validate(config, 8080, "127.0.0.1")

    def test_worker_networks_must_be_internal(self):
        config = rendered()
        config["networks"]["tts_private"]["internal"] = False
        with self.assertRaisesRegex(ValueError, "networks must be internal"):
            validate(config, 8080, "127.0.0.1")

    def test_cuda_static_check_rejects_broad_gpu_allocation(self):
        config = {
            "name": "speech-platform-static",
            "services": {
                "stt": {
                    "image": "registry.example.invalid/stt@sha256:" + "0" * 64,
                    "labels": {
                        "com.speech-platform.image-identity-mode": "registry_digest",
                        "com.speech-platform.image-id": "sha256:" + "3" * 64,
                    },
                    "build": None,
                    "platform": "linux/amd64",
                    "pull_policy": "never",
                    "restart": "no",
                    "user": "65532:65532",
                    "read_only": True,
                    "ports": [],
                    "networks": {"stt_private": None},
                    "group_add": ["1000"],
                    "deploy": {
                        "resources": {
                            "reservations": {
                                "devices": [
                                    {
                                        "device_ids": ["0"],
                                        "driver": "nvidia",
                                        "capabilities": ["gpu"],
                                    }
                                ]
                            }
                        }
                    },
                    "mem_limit": 1024,
                    "cpus": 1,
                    "pids_limit": 128,
                    "healthcheck": {"test": ["CMD", "python", "/healthz"]},
                    "volumes": [{"target": "/models", "read_only": True}],
                }
            },
        }
        expected = {
            "project_name": "speech-platform-static",
            "image": config["services"]["stt"]["image"],
            "identity_mode": "registry_digest",
            "image_id": "sha256:" + "3" * 64,
            "artifact_gid": "1000",
            "host_gpu": "0",
            "memory_bytes": 1024,
            "cpus": 1,
            "pids": 128,
        }
        validate_cuda_deployment(config, expected)
        config["services"]["stt"]["gpus"] = "all"
        with self.assertRaisesRegex(ValueError, "broad gpus"):
            validate_cuda_deployment(config, expected)

    def test_cuda_static_check_accepts_only_explicit_local_image_id(self):
        config = {
            "name": "speech-platform-static",
            "services": {
                "stt": {
                    "image": "sha256:" + "3" * 64,
                    "labels": {
                        "com.speech-platform.image-identity-mode": "local_image_id",
                        "com.speech-platform.image-id": "sha256:" + "3" * 64,
                    },
                    "build": None,
                    "platform": "linux/amd64",
                    "pull_policy": "never",
                    "restart": "no",
                    "user": "65532:65532",
                    "read_only": True,
                    "ports": [],
                    "networks": {"stt_private": None},
                    "group_add": ["1000"],
                    "deploy": {
                        "resources": {
                            "reservations": {
                                "devices": [
                                    {
                                        "device_ids": ["0"],
                                        "driver": "nvidia",
                                        "capabilities": ["gpu"],
                                    }
                                ]
                            }
                        }
                    },
                    "mem_limit": 1024,
                    "cpus": 1,
                    "pids_limit": 128,
                    "healthcheck": {"test": ["CMD", "python", "/healthz"]},
                    "volumes": [{"target": "/models", "read_only": True}],
                }
            },
        }
        expected = {
            "project_name": "speech-platform-static",
            "image": "sha256:" + "3" * 64,
            "identity_mode": "local_image_id",
            "image_id": "sha256:" + "3" * 64,
            "artifact_gid": "1000",
            "host_gpu": "0",
            "memory_bytes": 1024,
            "cpus": 1,
            "pids": 128,
        }
        validate_cuda_deployment(config, expected)
        expected["image"] = "speech-platform/stt:latest"
        with self.assertRaisesRegex(ValueError, "validated runtime image"):
            validate_cuda_deployment(config, expected)
        expected["image"] = "sha256:" + "3" * 64
        expected["identity_mode"] = "implicit"
        with self.assertRaisesRegex(ValueError, "unsupported CUDA image identity"):
            validate_cuda_deployment(config, expected)


if __name__ == "__main__":
    unittest.main()
