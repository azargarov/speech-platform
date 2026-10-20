"""Collect bounded, read-only evidence for one Compose baseline plan."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
from pathlib import Path

from scripts.baseline_adoption import plan_baseline_adoption
from scripts.deployment_state import DEFAULT_STATE_ROOT
from scripts.project_lock import DEFAULT_LOCK_ROOT
from scripts.release_manifest import DEFAULT_RELEASE, REPOSITORY_ROOT, load_release
from scripts.restore_snapshot import verify_retained_snapshot
from scripts.stt_deployment import (
    _compose_environment,
    _load_selected_configs,
    _project_services,
    _render_selected,
    _service_probe,
    _run,
    _require_release_match,
    verify_registry_image,
)
from scripts.stt_deployment_profile import load_and_validate


PROJECT = "speech-platform-m01e-fresh-v012"
PRIVATE = Path("private/deployment/m01e-fresh-v012")
MODEL_STORE = Path("/var/tmp/speech-platform-m01e-fresh-v012/model-store")
STATE_ROOT = DEFAULT_STATE_ROOT


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _docker_json(run, command: list[str]):
    """Run one bounded read-only Docker command and reject invalid evidence."""
    try:
        value = json.loads(run(command))
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as error:
        raise ValueError(
            "read-only Docker inspection failed or returned invalid JSON"
        ) from error
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError("read-only Docker inspection was missing or ambiguous")
    return value[0]


def _restore_inventory(
    services: list[str],
    release: dict,
    expected_contract: dict,
    compose_hashes: dict[str, str],
) -> list[dict]:
    # No snapshot is created here. Only the approved retained-input inventory
    # can satisfy restoration eligibility; the existing deployment directory
    # contains live configs but is not an immutable snapshot inventory.
    inventory = PRIVATE / "baseline-restoration-inputs.yaml"
    if not inventory.is_file():
        return []
    info = inventory.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        return []
    import yaml

    value = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        return []
    expected_artifacts = {
        service: sorted(
            ["oci://" + release["services"][service]["image"]]
            + [
                "model://" + model["id"] + "@sha256:" + model["manifest_sha256"]
                for model in release["services"][service]["required_model_artifacts"]
            ]
        )
        for service in services
    }
    try:
        for item in value:
            if not isinstance(item, dict) or item.get("service") not in services:
                return []
            snapshot = item.get("configuration_snapshot")
            if not isinstance(snapshot, dict):
                return []
            reference = snapshot.get("reference", "")
            prefix = "private://snapshots/sha256/"
            if not isinstance(reference, str) or not reference.startswith(prefix):
                return []
            manifest = verify_retained_snapshot(
                PRIVATE / "restoration",
                item["service"],
                snapshot.get("sha256", ""),
                project_name=PROJECT,
                expected_artifacts_by_service=expected_artifacts,
            )
            if reference != prefix + snapshot["sha256"]:
                return []
            if manifest["compose_service_hashes"] != compose_hashes:
                return []
            if manifest["configuration_sha256_by_service"] != {
                name: expected_contract[name]["configuration_sha256"]
                for name in services
            }:
                return []
            if manifest["runtime_identity_sha256_by_service"] != {
                name: expected_contract[name]["runtime_identity_sha256"]
                for name in services
            }:
                return []
            if sorted(
                manifest["secret_versions_by_service"][item["service"]]
            ) != sorted(item.get("secret_versions", [])):
                return []
    except (KeyError, OSError, ValueError, TypeError):
        return []
    return value


def _compose_service_hashes(
    services: list[str], environment: dict[str, str], run, *, compose_paths=None
) -> dict[str, str]:
    """Derive expected Compose service identities from validated inputs."""
    command = [
        "docker",
        "compose",
        "--project-directory",
        str((REPOSITORY_ROOT / "deployments/compose").resolve()),
        "--project-name",
        PROJECT,
        "--env-file",
        "/dev/null",
        "-f",
        str(
            (compose_paths or {}).get(
                "compose.yaml", "deployments/compose/compose.yaml"
            )
        ),
    ]
    if "stt" in services:
        command.extend(
            [
                "-f",
                str(
                    (compose_paths or {}).get(
                        "compose.stt-cuda.yaml",
                        "deployments/compose/compose.stt-cuda.yaml",
                    )
                ),
                "--profile",
                "cuda",
            ]
        )
    result = {}
    for service in services:
        output = run([*command, "config", "--hash", service], environment=environment)
        fields = output.strip().split()
        digest = fields[-1] if fields else ""
        if len(fields) > 2 or (len(fields) == 2 and fields[0] != service):
            raise ValueError("Compose returned ambiguous service hash evidence")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Compose returned invalid service hash evidence")
        result[service] = digest
    return result


def collect_baseline_adoption(
    *, run=_run, evidence_sink=None, compose_paths=None
) -> dict:
    release = load_release(DEFAULT_RELEASE, REPOSITORY_ROOT)
    enabled_path = PRIVATE / "enabled-services.yaml"
    import yaml

    enabled = yaml.safe_load(enabled_path.read_text(encoding="utf-8"))[
        "enabled_services"
    ]
    selected = sorted(release["services"])
    if set(enabled) != set(selected):
        selected = sorted(enabled)

    service_profile, gateway_config, tts_config, gateway_path, tts_path = (
        _load_selected_configs(
            selected,
            service_profile_path=str(PRIVATE / "services.yaml"),
            gateway_config_path=str(PRIVATE / "gateway.yaml"),
            tts_config_path=str(PRIVATE / "tts.yaml"),
        )
    )
    stt_validated = load_and_validate(
        PRIVATE / "profile.yaml",
        PRIVATE / "stt-application.yaml",
        PRIVATE / "stt-deployment.yaml",
        PRIVATE / "stt.yaml",
        verify_files=False,
    )
    _require_release_match(stt_validated, DEFAULT_RELEASE)
    verify_registry_image(stt_validated, run=run)
    compose_values = _compose_environment(
        selected,
        release,
        service_profile,
        gateway_config,
        tts_config,
        gateway_path,
        tts_path,
        stt_validated=stt_validated,
        application_config=str(PRIVATE / "stt-application.yaml"),
        deployment_config=str(PRIVATE / "stt-deployment.yaml"),
        worker_config=str(PRIVATE / "stt.yaml"),
    )
    rendered = _render_selected(
        PROJECT,
        selected,
        compose_values,
        gateway_config,
        stt_validated,
        run,
        compose_paths=compose_paths,
    )
    compose_hashes = _compose_service_hashes(
        selected, compose_values, run, compose_paths=compose_paths
    )

    # Docker labels select the exact project independently of expected config.
    containers = _project_services(
        PROJECT,
        gateway_host_port=service_profile["gateway"]["host_port"],
        gateway_listen_port=gateway_config["listen_port"],
        run=run,
    )
    observations = []
    expected = {}
    for name in selected:
        container = containers[name]
        rendered_service = rendered["services"][name]
        labels = (container.get("Config") or {}).get("Labels") or {}
        host = container.get("HostConfig") or {}
        config = container.get("Config") or {}
        image = _docker_json(run, ["docker", "image", "inspect", container["Image"]])
        image_config = image.get("Config") or {}
        image_labels = image_config.get("Labels") or {}
        ref = release["services"][name]["image"]
        observed_ref = next(
            (
                candidate
                for candidate in (image.get("RepoDigests") or [])
                if candidate == ref
            ),
            None,
        )
        digest = ref.rsplit("sha256:", 1)[1]
        image_ok = (
            image.get("Id") == container["Image"]
            and observed_ref == ref
            and image.get("Os") == "linux"
            and image.get("Architecture") == "amd64"
            and image_labels.get("org.opencontainers.image.revision")
            == release["git_source_revision"]
        )
        health = (container.get("State") or {}).get("Health", {}).get("Status", "none")
        if name in {"gateway", "tts"}:
            readiness_ok = _service_probe(
                name,
                container,
                profile=service_profile,
                gateway_config=gateway_config,
                tts_config=tts_config,
                run=run,
            )
            readiness_capability = "health"
        else:
            # Health is Docker's healthcheck; readiness is independently queried
            # inside the exact container without changing its state.
            try:
                run(
                    [
                        "docker",
                        "exec",
                        container["Id"],
                        "python",
                        "-c",
                        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/readyz', timeout=3).read()",
                    ]
                )
                readiness_ok = True
            except (OSError, subprocess.SubprocessError):
                readiness_ok = False
            readiness_capability = "readiness"

        actual_mounts = sorted(
            (
                {
                    "source": m.get("Source"),
                    "target": m.get("Destination"),
                    "read_only": not m.get("RW", True),
                }
                for m in container.get("Mounts", [])
            ),
            key=lambda m: m["target"] or "",
        )
        expected_mounts = sorted(
            (
                {
                    "source": v.get("source"),
                    "target": v.get("target"),
                    "read_only": bool(v.get("read_only")),
                }
                for v in rendered_service.get("volumes", [])
            ),
            key=lambda m: m["target"] or "",
        )
        network_labels = {}
        for network_name, network in (
            container.get("NetworkSettings", {}).get("Networks") or {}
        ).items():
            network = _docker_json(run, ["docker", "network", "inspect", network_name])
            network_labels[network_name] = (network.get("Labels") or {}).get(
                "com.docker.compose.network"
            )
        actual_networks = sorted(filter(None, network_labels.values()))
        expected_networks = sorted(rendered_service.get("networks", {}))
        port_bindings = host.get("PortBindings") or {}
        actual_ports = sorted(
            int(v["HostPort"])
            for values in port_bindings.values()
            for v in (values or [])
        )
        expected_ports = sorted(
            int(p["published"]) for p in rendered_service.get("ports", [])
        )
        groups = sorted(int(g) for g in (host.get("GroupAdd") or []))
        actual_config_sha = labels.get("com.speech-platform.configuration-sha256")
        expected_labels = rendered_service.get("labels", {})
        if name == "stt":
            actual_config_sha = labels.get(
                "com.speech-platform.configuration-set-sha256"
            )
            expected_config_sha = compose_values.get("STT_CONFIGURATION_SET_SHA256")
        else:
            expected_config_sha = expected_labels.get(
                "com.speech-platform.configuration-sha256"
            )
        if name == "stt":
            # STT has no custom deployment-identity label. Its independently
            # rendered Compose service hash is the expected identity; Docker's
            # config-hash label is the observation from the running container.
            actual_runtime_sha = labels.get("com.docker.compose.config-hash")
            expected_runtime_sha = compose_hashes[name]
        else:
            actual_runtime_sha = labels.get(
                "com.speech-platform.deployment-identity-sha256"
            )
            expected_runtime_sha = expected_labels.get(
                "com.speech-platform.deployment-identity-sha256"
            )
        compose_hash = labels.get("com.docker.compose.config-hash")
        cfg = {
            "mounts": expected_mounts,
            "networks": expected_networks,
            "ports": expected_ports,
            "uid": int(str(rendered_service.get("user", "0:0")).split(":")[0]),
            "gid": int(str(rendered_service.get("user", "0:0")).split(":")[-1]),
            "supplementary_gids": sorted(
                int(g) for g in rendered_service.get("group_add", [])
            ),
            "read_only_rootfs": rendered_service.get("read_only") is True,
            "cap_drop": rendered_service.get("cap_drop", []),
            "security_opt": rendered_service.get("security_opt", []),
            "privileged": rendered_service.get("privileged", False),
            "no_new_privileges": "no-new-privileges:true"
            in rendered_service.get("security_opt", []),
            "configuration_sha256": expected_config_sha,
            "runtime_identity_sha256": expected_runtime_sha,
        }
        expected[name] = cfg
        provenance = {
            "verified": image_ok,
            "evidence_sha256": _sha(
                json.dumps(
                    {
                        "id": image.get("Id"),
                        "repo_digests": image.get("RepoDigests"),
                        "platform": [image.get("Os"), image.get("Architecture")],
                    },
                    sort_keys=True,
                )
            ),
            "image_reference": ref,
            "image_manifest_sha256": digest,
            "platform": "linux/amd64",
        }
        observations.append(
            {
                "service": name,
                "project_name": labels.get("com.docker.compose.project"),
                "container_id": container.get("Id"),
                "image_id": container.get("Image"),
                "compose_config_hash": compose_hash,
                "state": (container.get("State") or {}).get("Status"),
                # Gateway/TTS have no Docker healthcheck; their live HTTP probe is
                # the service health evidence required by this planner contract.
                "health": "healthy"
                if readiness_ok
                and (container.get("State") or {}).get("Status") == "running"
                else health,
                "image_reference": observed_ref,
                "image_manifest_sha256": digest,
                "platform": "linux/amd64",
                "provenance": provenance,
                "configuration_sha256": actual_config_sha,
                "runtime_identity_sha256": actual_runtime_sha,
                "model_identities": [
                    {
                        "model_id": m["id"],
                        "revision": m["revision"],
                        "manifest_sha256": m["manifest_sha256"],
                    }
                    for m in release["services"][name]["required_model_artifacts"]
                ],
                "mounts": actual_mounts,
                "networks": actual_networks,
                "ports": actual_ports,
                "uid": int((config.get("User") or "0:0").split(":")[0]),
                "gid": int((config.get("User") or "0:0").split(":")[-1]),
                "supplementary_gids": groups,
                "read_only_rootfs": host.get("ReadonlyRootfs") is True,
                "cap_drop": host.get("CapDrop", []),
                "security_opt": host.get("SecurityOpt", []),
                "privileged": host.get("Privileged", False),
                "no_new_privileges": "no-new-privileges:true"
                in host.get("SecurityOpt", []),
                "readiness": {
                    "status": "READY" if readiness_ok else "NOT_READY",
                    "capability": readiness_capability,
                    "evidence_sha256": _sha(
                        f"{container.get('Id')}:{readiness_ok}:{readiness_capability}:{time.time_ns()}"
                    ),
                    "observed_at_epoch": time.time(),
                },
                "compatible": actual_mounts == expected_mounts
                and actual_networks == expected_networks
                and actual_ports == expected_ports,
            }
        )
        # Drift is carried as an explicit mismatch against an independently
        # rendered expected contract; planner eligibility will refuse it.
        if (
            actual_mounts != expected_mounts
            or actual_networks != expected_networks
            or actual_ports != expected_ports
        ):
            cfg["mounts"], cfg["networks"], cfg["ports"] = (
                expected_mounts,
                expected_networks,
                expected_ports,
            )
            observations[-1]["compatible"] = False
        if (
            actual_config_sha != expected_config_sha
            or actual_runtime_sha != expected_runtime_sha
        ):
            observations[-1]["compatible"] = False
        if any(
            observations[-1][field] != cfg[field]
            for field in (
                "uid",
                "gid",
                "supplementary_gids",
                "read_only_rootfs",
                "cap_drop",
                "security_opt",
                "privileged",
                "no_new_privileges",
            )
        ):
            observations[-1]["compatible"] = False

    plan = plan_baseline_adoption(
        project_name=PROJECT,
        enabled_services=selected,
        runtime_observations=observations,
        expected_runtime_contract=expected,
        restore_inputs=_restore_inventory(selected, release, expected, compose_hashes),
        state_root=STATE_ROOT,
        lock_root=DEFAULT_LOCK_ROOT,
        release_path=DEFAULT_RELEASE,
        model_store=MODEL_STORE,
        repository_root=REPOSITORY_ROOT,
    )
    plan["restoration_input_status"] = (
        "AVAILABLE"
        if not any(
            "restore_inputs" in b or "restore_input" in b for b in plan["blockers"]
        )
        else "MISSING_OR_INCOMPLETE"
    )
    plan["observed_runtime_drift"] = sorted(
        f"{item['service']}:runtime_configuration_mismatch"
        for item in observations
        if not item["compatible"]
    )
    if evidence_sink is not None:
        evidence_sink.clear()
        evidence_sink.update(
            {
                "release": release,
                "selected_services": selected,
                "expected_runtime_contract": expected,
                "observations": observations,
                "rendered_compose": rendered,
                "compose_service_hashes": compose_hashes,
                "render_environment": compose_values,
                "plan": plan,
                "stt_validated": stt_validated,
            }
        )
    return plan


if __name__ == "__main__":
    print(json.dumps(collect_baseline_adoption(), indent=2, sort_keys=True))
