import json
import unittest
from types import SimpleNamespace

from scripts.ollama_network import NetworkError, prepare_network


NETWORK = "speech-platform_ollama_private"
CONTAINER = "ollama"
CONTAINER_ID = "container-id"


def make_network(*, driver="bridge", internal=True):
    return {
        "Name": NETWORK,
        "Id": "network-id",
        "Driver": driver,
        "Internal": internal,
        "IPAM": {"Config": [{"Subnet": "172.31.0.0/16"}]},
    }


def make_container(networks=None):
    return {
        "Name": f"/{CONTAINER}",
        "Id": CONTAINER_ID,
        "State": {"Running": True},
        "NetworkSettings": {
            "Networks": networks or {"bridge": {"Aliases": None}},
            "Ports": {"11434/tcp": [{"HostIp": "0.0.0.0", "HostPort": "11434"}]},
        },
    }


class FakeDocker:
    def __init__(
        self,
        *,
        network=None,
        container=None,
        missing_container=False,
        fail_connect=False,
    ):
        self.network = network
        self.container = None if missing_container else (container or make_container())
        self.fail_connect = fail_connect
        self.calls = []

    def __call__(self, args, *, check=False, capture=True):
        self.calls.append(list(args))
        if args[:3] == ["docker", "container", "ls"]:
            names = [CONTAINER] if self.container is not None else []
            return self.result("\n".join(names) + ("\n" if names else ""))
        if args[:3] == ["docker", "network", "ls"]:
            names = [NETWORK] if self.network is not None else []
            return self.result("\n".join(names) + ("\n" if names else ""))
        if args[:2] == ["docker", "inspect"]:
            return self.result(json.dumps(self.container))
        if args[:3] == ["docker", "network", "inspect"]:
            return self.result(json.dumps(self.network))
        if args[:3] == ["docker", "network", "create"]:
            self.network = make_network()
            return self.result("network-id\n")
        if args[:3] == ["docker", "network", "connect"]:
            if self.fail_connect:
                return self.result("", 1, "synthetic attach failure")
            networks = self.container["NetworkSettings"]["Networks"]
            networks[NETWORK] = {"Aliases": ["ollama", "container-id"]}
            return self.result("")
        return self.result("", 2, "unexpected Docker command")

    @staticmethod
    def result(stdout="", returncode=0, stderr=""):
        return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


class OllamaNetworkTests(unittest.TestCase):
    def test_missing_network_is_created_and_existing_container_is_attached(self):
        docker = FakeDocker()
        result = prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertEqual(result["network"], "created")
        self.assertEqual(result["attachment"], "attached")
        self.assertIn("bridge", docker.container["NetworkSettings"]["Networks"])
        self.assertEqual(
            docker.container["NetworkSettings"]["Ports"]["11434/tcp"][0]["HostPort"],
            "11434",
        )
        self.assertIn(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--internal",
                NETWORK,
            ],
            docker.calls,
        )
        self.assertIn(
            [
                "docker",
                "network",
                "connect",
                "--alias",
                "ollama",
                NETWORK,
                CONTAINER_ID,
            ],
            docker.calls,
        )

    def test_valid_existing_network_and_attachment_are_reused(self):
        docker = FakeDocker(
            network=make_network(),
            container=make_container(
                {
                    "bridge": {"Aliases": None},
                    NETWORK: {"Aliases": ["ollama", CONTAINER_ID]},
                }
            ),
        )
        result = prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertEqual(result["network"], "reused")
        self.assertEqual(result["attachment"], "reused")
        self.assertFalse(any(call[2:3] == ["create"] for call in docker.calls))
        self.assertFalse(any(call[2:3] == ["connect"] for call in docker.calls))

    def test_conflicting_network_configuration_is_rejected_without_mutation(self):
        for network in (make_network(driver="overlay"), make_network(internal=False)):
            docker = FakeDocker(network=network)
            with (
                self.subTest(network=network),
                self.assertRaisesRegex(NetworkError, "conflicts"),
            ):
                prepare_network(NETWORK, CONTAINER, docker_run=docker)
            self.assertFalse(
                any("create" in call or "connect" in call for call in docker.calls)
            )

    def test_attached_without_alias_is_rejected_without_disconnect(self):
        docker = FakeDocker(
            network=make_network(),
            container=make_container({NETWORK: {"Aliases": [CONTAINER_ID]}}),
        )
        with self.assertRaisesRegex(NetworkError, "without alias"):
            prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertFalse(any("disconnect" in call for call in docker.calls))

    def test_repeated_execution_makes_no_additional_changes(self):
        docker = FakeDocker()
        first = prepare_network(NETWORK, CONTAINER, docker_run=docker)
        mutation_count = sum(call[2] in {"create", "connect"} for call in docker.calls)
        second = prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertEqual(mutation_count, 2)
        self.assertEqual(
            sum(call[2] in {"create", "connect"} for call in docker.calls), 2
        )
        self.assertEqual(first["network"], "created")
        self.assertEqual(second["network"], "reused")
        self.assertEqual(second["attachment"], "reused")

    def test_missing_ollama_fails_before_creating_network(self):
        docker = FakeDocker(missing_container=True)
        with self.assertRaisesRegex(NetworkError, "was not found"):
            prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertFalse(any("create" in call for call in docker.calls))

    def test_attachment_failure_preserves_existing_resources(self):
        docker = FakeDocker(fail_connect=True)
        with self.assertRaisesRegex(NetworkError, "synthetic attach failure"):
            prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertIn("bridge", docker.container["NetworkSettings"]["Networks"])
        self.assertFalse(
            any("disconnect" in call or "rm" in call for call in docker.calls)
        )

    def test_post_attach_verification_rejects_changed_published_ports(self):
        class PortChangingDocker(FakeDocker):
            def __call__(self, args, **kwargs):
                result = super().__call__(args, **kwargs)
                if args[:3] == ["docker", "network", "connect"]:
                    self.container["NetworkSettings"]["Ports"] = {}
                return result

        docker = PortChangingDocker()
        with self.assertRaisesRegex(NetworkError, "published ports changed"):
            prepare_network(NETWORK, CONTAINER, docker_run=docker)
        self.assertFalse(
            any("disconnect" in call or "rm" in call for call in docker.calls)
        )

    def test_invalid_names_are_rejected(self):
        with self.assertRaises(NetworkError):
            prepare_network("bad network", CONTAINER, docker_run=FakeDocker())


if __name__ == "__main__":
    unittest.main()
