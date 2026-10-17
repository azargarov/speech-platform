"""Validate rendered Compose security and Gateway port configuration."""

import ipaddress
import json
import os
import sys
from pathlib import Path

import yaml


def validate(config, expected_port, expected_bind):
    if type(expected_port) is not int or not 1 <= expected_port <= 65535:
        raise ValueError("effective Gateway listen port must be in 1..65535")
    try:
        ipaddress.ip_address(expected_bind)
    except ValueError as exc:
        raise ValueError("Gateway bind address must be an IP address") from exc

    networks = config["networks"]
    if set(networks) != {"stt_private", "tts_private"}:
        raise ValueError("only the STT-private and TTS-private networks are allowed")
    if any(not network["internal"] for network in networks.values()):
        raise ValueError("worker networks must be internal")
    services = config["services"]
    if set(services) != {"gateway", "stt", "tts"}:
        raise ValueError("unexpected Compose service set")
    gateway = services["gateway"]
    if set(gateway["networks"]) != {"stt_private", "tts_private"}:
        raise ValueError("Gateway must connect to both private worker networks")
    if set(services["stt"]["networks"]) != {"stt_private"}:
        raise ValueError("STT must connect only to the STT-private network")
    if set(services["tts"]["networks"]) != {"tts_private"}:
        raise ValueError("TTS must connect only to the TTS-private network")
    if gateway["environment"].get("SPEECH_LISTEN_PORT") != str(expected_port):
        raise ValueError(
            "Compose Gateway listen port does not match effective configuration"
        )
    ports = gateway.get("ports", [])
    if len(ports) != 1:
        raise ValueError("Gateway must publish exactly one host port")
    published = ports[0]
    if published["target"] != expected_port or published["host_ip"] != expected_bind:
        raise ValueError(
            "Gateway published port/bind does not match effective configuration"
        )
    if not 1 <= int(published["published"]) <= 65535:
        raise ValueError("Gateway published port must be in 1..65535")

    for name, service in services.items():
        if not service["read_only"] or service["user"] != "65532:65532":
            raise ValueError(f"{name} must use a read-only filesystem and nonroot user")
        if service.get("privileged", False) or service["cap_drop"] != ["ALL"]:
            raise ValueError(f"{name} has unsafe privilege configuration")
        if "no-new-privileges:true" not in service["security_opt"]:
            raise ValueError(f"{name} must enable no-new-privileges")
        if int(service["mem_limit"]) <= 0 or float(service["cpus"]) <= 0:
            raise ValueError(f"{name} must have positive resource limits")
        if service["pids_limit"] <= 0:
            raise ValueError(f"{name} must have a positive process limit")
        if name != "gateway" and (service.get("ports") or service.get("depends_on")):
            raise ValueError(f"{name} must remain private and independent")


def main():
    rendered = json.load(sys.stdin)
    defaults = yaml.safe_load(Path("configs/gateway.yaml").read_text())
    port_value = os.environ.get("SPEECH_LISTEN_PORT") or str(defaults["listen_port"])
    try:
        port = int(port_value)
    except ValueError as exc:
        raise ValueError("SPEECH_LISTEN_PORT must be an integer") from exc
    bind = os.environ.get("SPEECH_BIND_IP") or "127.0.0.1"
    validate(rendered, port, bind)


if __name__ == "__main__":
    main()
