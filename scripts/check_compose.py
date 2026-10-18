"""Validate rendered Compose security and Gateway port configuration."""

import ipaddress
import json
import os
import re
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


def validate_cuda_deployment(config, expected):
    """Check the persistent CUDA overlay after ordinary Compose rendering."""
    if config.get("name") != expected["project_name"]:
        raise ValueError("CUDA Compose project identity does not match")
    stt = config["services"]["stt"]
    if stt.get("gpus"):
        raise ValueError("CUDA worker must not use broad gpus allocation")
    if stt.get("image") != expected["image"] or stt.get("build") is not None:
        raise ValueError("CUDA worker must use only its validated runtime image")
    identity_mode = expected["identity_mode"]
    image_id = expected["image_id"]
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise ValueError("CUDA expected image ID must be a Docker sha256 ID")
    if identity_mode == "registry_digest":
        if not re.fullmatch(r".+@sha256:[0-9a-f]{64}", expected["image"]):
            raise ValueError("registry_digest mode requires an immutable digest")
    elif identity_mode == "local_image_id":
        if expected["image"] != image_id:
            raise ValueError("local_image_id mode must select the exact image ID")
    else:
        raise ValueError("unsupported CUDA image identity mode")
    labels = stt.get("labels", {})
    if (
        labels.get("com.speech-platform.image-identity-mode") != identity_mode
        or labels.get("com.speech-platform.image-id") != image_id
    ):
        raise ValueError("CUDA container image identity labels do not match")
    if stt.get("platform") != "linux/amd64" or stt.get("pull_policy") != "never":
        raise ValueError("CUDA runtime platform and pull policy must be explicit")
    if stt.get("restart") != "no":
        raise ValueError("CUDA worker restart must remain operator-controlled")
    if stt.get("user") != "65532:65532" or stt.get("read_only") is not True:
        raise ValueError("CUDA worker must remain non-root with a read-only root")
    if stt.get("ports") or set(stt.get("networks", {})) != {"stt_private"}:
        raise ValueError("CUDA worker must remain private and publish no ports")
    if stt.get("group_add") != [str(expected["artifact_gid"])]:
        raise ValueError("CUDA artifact supplementary group does not match")
    devices = (
        stt.get("deploy", {})
        .get("resources", {})
        .get("reservations", {})
        .get("devices", [])
    )
    if len(devices) != 1 or devices[0].get("device_ids") != [expected["host_gpu"]]:
        raise ValueError("CUDA worker must expose exactly the configured host GPU")
    if devices[0].get("driver") != "nvidia" or "gpu" not in devices[0].get(
        "capabilities", []
    ):
        raise ValueError("CUDA worker device reservation is invalid")
    if (
        int(stt.get("mem_limit", 0)) != expected["memory_bytes"]
        or float(stt.get("cpus", 0)) != expected["cpus"]
        or int(stt.get("pids_limit", 0)) != expected["pids"]
    ):
        raise ValueError("CUDA worker resource limits do not match the profile")
    healthcheck = stt.get("healthcheck", {})
    probe = " ".join(map(str, healthcheck.get("test", [])))
    if "/healthz" not in probe or "/readyz" in probe:
        raise ValueError("CUDA Compose liveness must check healthz only")
    model_mounts = [
        volume for volume in stt.get("volumes", []) if volume.get("target") == "/models"
    ]
    if len(model_mounts) != 1 or model_mounts[0].get("read_only") is not True:
        raise ValueError("CUDA model mount must be explicit and read-only")


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
    if os.environ.get("STT_CUDA_STATIC_CHECK") == "1":
        validate_cuda_deployment(
            rendered,
            {
                "project_name": os.environ["STT_COMPOSE_PROJECT_NAME"],
                "image": os.environ["STT_CUDA_IMAGE"],
                "identity_mode": os.environ["STT_IMAGE_IDENTITY_MODE"],
                "image_id": os.environ["STT_IMAGE_ID"],
                "artifact_gid": os.environ["STT_ARTIFACT_GID"],
                "host_gpu": os.environ["STT_HOST_GPU_DEVICE_ID"],
                "memory_bytes": int(os.environ["STT_MEMORY_LIMIT_BYTES"]),
                "cpus": float(os.environ["STT_CPU_LIMIT"]),
                "pids": int(os.environ["STT_PIDS_LIMIT"]),
            },
        )


if __name__ == "__main__":
    main()
