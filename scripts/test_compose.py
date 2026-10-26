"""Regression checks for Compose Gateway publication and worker isolation."""

import unittest

from scripts.check_compose import validate, validate_cuda_deployment


def rendered(port=8080, bind="127.0.0.1"):
    return {
        "networks": {
            "gateway_publish": {
                "driver": "bridge",
                "driver_opts": {
                    "com.docker.network.bridge.enable_ip_masquerade": "false"
                },
            },
            "stt_private": {"internal": True},
            "tts_private": {"internal": True},
        },
        "services": {
            "gateway": {
                "environment": {"SPEECH_LISTEN_PORT": str(port)},
                "ports": [{"host_ip": bind, "published": "8080", "target": port}],
                "volumes": [{"target": "/configs/prompts", "read_only": True}],
                "read_only": True,
                "user": "65532:65532",
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "mem_limit": "134217728",
                "cpus": 1,
                "pids_limit": 128,
                "networks": {
                    "gateway_publish": None,
                    "stt_private": None,
                    "tts_private": None,
                },
            },
            "stt": worker("stt_private"),
            "tts": worker("tts_private"),
        },
    }


def worker(network):
    return {
        "profiles": ["stt" if network == "stt_private" else "tts"],
        "read_only": True,
        "user": "65532:65532",
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "mem_limit": "268435456",
        "cpus": 1,
        "pids_limit": 128,
        "group_add": ["65532"],
        "networks": {network: None},
    }


class ComposeConfig(unittest.TestCase):
    def test_default_configuration_and_loopback_binding(self):
        validate(rendered(), 8080, "127.0.0.1")

    def test_port_override(self):
        validate(rendered(8765), 8765, "127.0.0.1")

    def test_gateway_prompt_directory_must_be_read_only(self):
        config = rendered()
        config["services"]["gateway"]["volumes"][0]["read_only"] = False
        with self.assertRaisesRegex(ValueError, "prompt directory.*read-only"):
            validate(config, 8080, "127.0.0.1")

    def test_tts_requires_config_reader_group(self):
        config = rendered()
        config["services"]["tts"]["group_add"] = ["988"]
        validate(config, 8080, "127.0.0.1", "988")
        config["services"]["tts"].pop("group_add")
        with self.assertRaisesRegex(ValueError, "TTS configuration reader"):
            validate(config, 8080, "127.0.0.1", "988")

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

    def test_gateway_does_not_require_optional_compose_workers(self):
        config = rendered()
        config["services"]["gateway"]["depends_on"] = {
            "stt": {"condition": "service_healthy"}
        }
        with self.assertRaisesRegex(
            ValueError, "Gateway must not require optional workers"
        ):
            validate(config, 8080, "127.0.0.1")

    def test_each_worker_has_an_independent_profile(self):
        config = rendered()
        config["networks"]["publish"] = config["networks"].pop("gateway_publish")
        config["services"]["gateway"]["networks"]["publish"] = config["services"][
            "gateway"
        ]["networks"].pop("gateway_publish")
        config["services"]["tts"]["profiles"] = ["stt"]
        with self.assertRaisesRegex(
            ValueError, "TTS must use its independent Compose profile"
        ):
            validate(config, 8080, "127.0.0.1", require_optional_profiles=True)

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

    def test_gateway_publication_network_disables_masquerading(self):
        config = rendered()
        config["networks"]["gateway_publish"]["driver_opts"][
            "com.docker.network.bridge.enable_ip_masquerade"
        ] = "true"
        with self.assertRaisesRegex(ValueError, "disable bridge masquerading"):
            validate(config, 8080, "127.0.0.1")

    def test_network_definitions_reject_extra_unreviewed_options(self):
        config = rendered()
        config["networks"]["gateway_publish"]["attachable"] = True
        with self.assertRaisesRegex(ValueError, "disable bridge masquerading"):
            validate(config, 8080, "127.0.0.1")

        config = rendered()
        config["networks"]["stt_private"]["driver"] = "overlay"
        with self.assertRaisesRegex(ValueError, "worker networks"):
            validate(config, 8080, "127.0.0.1")

    def test_extra_network_declaration_is_rejected(self):
        config = rendered()
        config["networks"]["unexpected"] = {"internal": True}
        with self.assertRaisesRegex(ValueError, "networks are required"):
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
