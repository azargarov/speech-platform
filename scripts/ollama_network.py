"""Prepare the externally managed Ollama connection for local Gateway use."""

from __future__ import annotations

import json
import re
import subprocess

DEFAULT_NETWORK = "speech-platform_ollama_private"
DEFAULT_CONTAINER = "ollama"
NETWORK_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
CONTAINER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class NetworkError(Exception):
    """A safe, scoped error while preparing the optional Ollama bridge."""


def _docker_run(args: list[str], *, check=False, capture=True):
    return subprocess.run(args, text=True, capture_output=capture)


def validate_names(network_name: str, container_name: str) -> None:
    if not NETWORK_NAME.fullmatch(network_name):
        raise NetworkError("OLLAMA_NETWORK_NAME is not a valid Docker network name")
    if not CONTAINER_NAME.fullmatch(container_name):
        raise NetworkError("OLLAMA_CONTAINER_NAME is not a valid Docker container name")


def _invoke(docker_run, args: list[str], purpose: str):
    try:
        result = docker_run(args, check=False, capture=True)
    except OSError as exc:
        raise NetworkError(f"{purpose} could not run Docker") from exc
    if result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        raise NetworkError(f"{purpose} failed ({result.returncode}): {details}")
    return result.stdout or ""


def _network(docker_run, network_name: str) -> dict | None:
    names = _invoke(
        docker_run,
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        "Docker network listing",
    ).splitlines()
    if network_name not in names:
        return None
    raw = _invoke(
        docker_run,
        ["docker", "network", "inspect", "--format", "{{json .}}", network_name],
        f"Inspecting network {network_name!r}",
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NetworkError("Docker returned invalid network inspection JSON") from exc
    if not isinstance(value, dict):
        raise NetworkError("Docker returned invalid network inspection data")
    return value


def _container(docker_run, container_name: str) -> dict:
    names = _invoke(
        docker_run,
        ["docker", "container", "ls", "--all", "--format", "{{.Names}}"],
        "Docker container listing",
    ).splitlines()
    if container_name not in names:
        raise NetworkError(
            f"Ollama container {container_name!r} was not found; install will not start Ollama"
        )
    raw = _invoke(
        docker_run,
        [
            "docker",
            "inspect",
            "--type",
            "container",
            "--format",
            "{{json .}}",
            container_name,
        ],
        f"Inspecting Ollama container {container_name!r}",
    )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NetworkError("Docker returned invalid container inspection JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("Name", "").lstrip("/") != container_name
    ):
        raise NetworkError("Docker returned an unexpected Ollama container identity")
    if (value.get("State") or {}).get("Running") is not True:
        raise NetworkError(
            f"Ollama container {container_name!r} is not running; install will not start it"
        )
    return value


def _validate_network(network: dict, network_name: str) -> None:
    if network.get("Name") != network_name:
        raise NetworkError("Docker returned an unexpected network identity")
    if network.get("Driver") != "bridge" or network.get("Internal") is not True:
        raise NetworkError(
            f"network {network_name!r} conflicts with required bridge/internal=true settings; it was left unchanged"
        )


def _network_aliases(container: dict, network_name: str) -> list[str] | None:
    networks = (container.get("NetworkSettings") or {}).get("Networks") or {}
    attachment = networks.get(network_name)
    if attachment is None:
        return None
    aliases = attachment.get("Aliases") or []
    return aliases


def prepare_network(
    network_name: str = DEFAULT_NETWORK,
    container_name: str = DEFAULT_CONTAINER,
    *,
    docker_run=_docker_run,
) -> dict[str, str]:
    """Ensure Ollama joins an internal bridge without changing its other networks."""
    validate_names(network_name, container_name)
    container_before = _container(docker_run, container_name)
    original_networks = set(
        ((container_before.get("NetworkSettings") or {}).get("Networks") or {}).keys()
    )
    original_ports = (container_before.get("NetworkSettings") or {}).get("Ports")

    network = _network(docker_run, network_name)
    if network is None:
        _invoke(
            docker_run,
            [
                "docker",
                "network",
                "create",
                "--driver",
                "bridge",
                "--internal",
                network_name,
            ],
            f"Creating internal Ollama network {network_name!r}",
        )
        network = _network(docker_run, network_name)
        if network is None:
            raise NetworkError("Docker did not create the requested Ollama network")
        network_action = "created"
    else:
        network_action = "reused"
    _validate_network(network, network_name)

    aliases = _network_aliases(container_before, network_name)
    if aliases is not None:
        if "ollama" not in aliases:
            raise NetworkError(
                f"Ollama is attached to {network_name!r} without alias 'ollama'; network left unchanged"
            )
        attachment_action = "reused"
    else:
        container_id = container_before.get("Id")
        if not isinstance(container_id, str) or not container_id:
            raise NetworkError("Docker did not report the Ollama container ID")
        try:
            _invoke(
                docker_run,
                [
                    "docker",
                    "network",
                    "connect",
                    "--alias",
                    "ollama",
                    network_name,
                    container_id,
                ],
                f"Attaching Ollama to {network_name!r}",
            )
        except NetworkError as exc:
            raise NetworkError(
                f"network {network_action} ({network_name!r}); Ollama attachment failed; no automatic cleanup was attempted: {exc}"
            ) from exc
        attachment_action = "attached"

    container_after = _container(docker_run, container_name)
    attached_aliases = _network_aliases(container_after, network_name)
    after_networks = set(
        ((container_after.get("NetworkSettings") or {}).get("Networks") or {}).keys()
    )
    after_ports = (container_after.get("NetworkSettings") or {}).get("Ports")
    if attached_aliases is None or "ollama" not in attached_aliases:
        raise NetworkError(
            "Ollama network alias verification failed; no cleanup was attempted"
        )
    if not original_networks.issubset(after_networks):
        raise NetworkError(
            "Ollama lost a pre-existing network attachment; no cleanup was attempted"
        )
    if original_ports != after_ports:
        raise NetworkError("Ollama published ports changed; no cleanup was attempted")

    return {
        "network": network_action,
        "attachment": attachment_action,
        "network_name": network_name,
        "container_name": container_name,
    }
