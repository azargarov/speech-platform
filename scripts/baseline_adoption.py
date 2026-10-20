"""Deterministic, read-only planning for adopting an existing Compose baseline.

This module consumes explicit read-only runtime observations. It never invokes
Docker, takes the project lock, initializes state, or writes restoration inputs.
The caller is responsible for collecting observations with read-only commands.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from pathlib import Path
from typing import Callable

import yaml

from scripts.deployment_state import StateError, StateStore, canonical_json
from scripts.model_artifacts import ModelProvisionError, check_models
from scripts.project_lock import DEFAULT_LOCK_ROOT, PROJECT_KEY
from scripts.release_manifest import REPOSITORY_ROOT, load_release
from scripts.service_selection import ServiceSelectionError, resolve_services
from services.stt.artifacts import load_artifact_manifest

SHA256 = re.compile(r"^[0-9a-f]{64}$")
REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
GENERATION_ID = "g0-"  # Followed by the plan fingerprint prefix.
RESTORE_FIELDS = frozenset(
    {
        "service",
        "configuration_snapshot",
        "configuration_sha256",
        "secret_versions",
        "runtime_definition",
        "runtime_sha256",
        "available",
    }
)
SNAPSHOT_FIELDS = frozenset({"kind", "reference", "sha256", "schema_version"})
RUNTIME_REFERENCE_FIELDS = frozenset({"kind", "reference", "sha256", "schema_version"})
RUNTIME_FIELDS = frozenset(
    {
        "service",
        "project_name",
        "container_id",
        "image_id",
        "compose_config_hash",
        "state",
        "health",
        "image_reference",
        "image_manifest_sha256",
        "platform",
        "provenance",
        "configuration_sha256",
        "runtime_identity_sha256",
        "model_identities",
        "mounts",
        "networks",
        "ports",
        "uid",
        "gid",
        "supplementary_gids",
        "read_only_rootfs",
        "cap_drop",
        "security_opt",
        "privileged",
        "no_new_privileges",
        "readiness",
        "compatible",
    }
)


def _digest(value: object) -> bool:
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _restore_inputs(values: object, required: list[str], blockers: list[str]) -> dict:
    if not isinstance(values, list):
        blockers.append("restore_inputs_missing_or_invalid")
        return {}
    by_service = {}
    for item in values:
        if not isinstance(item, dict) or set(item) != RESTORE_FIELDS:
            blockers.append("restore_input_schema_invalid")
            continue
        service = item.get("service")
        if not isinstance(service, str) or service in by_service:
            blockers.append("restore_input_service_invalid_or_duplicate")
            continue
        snapshot = item["configuration_snapshot"]
        runtime_ref = item["runtime_definition"]
        if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_FIELDS:
            blockers.append(f"{service}:configuration_snapshot_reference_invalid")
            continue
        if (
            not isinstance(runtime_ref, dict)
            or set(runtime_ref) != RUNTIME_REFERENCE_FIELDS
        ):
            blockers.append(f"{service}:runtime_definition_reference_invalid")
            continue
        valid_refs = True
        for ref in (snapshot, runtime_ref):
            if (
                ref["kind"] not in {"private_snapshot", "immutable_reference"}
                or not isinstance(ref["reference"], str)
                or not REFERENCE.fullmatch(ref["reference"])
                or not _digest(ref["sha256"])
                or type(ref["schema_version"]) is not int
                or ref["schema_version"] < 1
            ):
                valid_refs = False
        if (
            snapshot["kind"] != "private_snapshot"
            or snapshot["schema_version"] != 3
            or runtime_ref["kind"] != "private_snapshot"
            or runtime_ref["schema_version"] != 3
            or runtime_ref["reference"] != snapshot["reference"]
            or runtime_ref["sha256"] != snapshot["sha256"]
        ):
            valid_refs = False
        secrets = item["secret_versions"]
        if (
            not valid_refs
            or item["available"] is not True
            or not _digest(item["configuration_sha256"])
            or not _digest(item["runtime_sha256"])
            or not isinstance(secrets, list)
            or any(
                not isinstance(value, str) or not REFERENCE.fullmatch(value)
                for value in secrets
            )
            or len(secrets) != len(set(secrets))
        ):
            blockers.append(f"{service}:restore_inputs_incomplete")
            continue
        by_service[service] = item
    for service in required:
        if service not in by_service:
            blockers.append(f"{service}:restore_inputs_missing")
    retained = [
        by_service[name]["configuration_snapshot"]
        for name in required
        if name in by_service
    ]
    if len(retained) == len(required) and retained:
        identities = {
            (item["reference"], item["sha256"], item["schema_version"])
            for item in retained
        }
        if len(identities) != 1:
            blockers.append("restore_snapshot_project_identity_mismatch")
    for service in sorted(set(by_service) - set(required)):
        blockers.append(f"{service}:restore_input_for_unselected_service")
    return by_service


def _state_observation(state_root: Path, project: str, blockers: list[str]) -> dict:
    if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
        blockers.append("deployment_state_root_malformed_or_unsafe")
        return {
            "store_exists": True,
            "status": "STATE_INCONSISTENT",
            "installed_generation_id": None,
            "unresolved_operations": [],
        }
    project_state = state_root / project
    if not project_state.exists() and not project_state.is_symlink():
        return {
            "store_exists": False,
            "status": "ABSENT",
            "installed_generation_id": None,
            "unresolved_operations": [],
        }
    try:
        store = StateStore(state_root, project)
        inspected = store.inspect()
        if inspected["status"] != "OK":
            blockers.append("deployment_state_inconsistent")
        if inspected.get("installed_generation_id") is not None:
            blockers.append("installed_generation_already_present")
        unresolved = sorted(
            issue.split(":", 2)[1]
            for issue in inspected.get("issues", [])
            if ": unfinished" in issue
        )
        if unresolved:
            blockers.append("deployment_operation_unresolved")
        return {
            "store_exists": True,
            "status": inspected["status"],
            "installed_generation_id": inspected.get("installed_generation_id"),
            "unresolved_operations": unresolved,
        }
    except (StateError, OSError, ValueError):
        blockers.append("deployment_state_missing_parts_or_malformed")
        return {
            "store_exists": True,
            "status": "STATE_INCONSISTENT",
            "installed_generation_id": None,
            "unresolved_operations": [],
        }


def _uncertainty_observation(
    lock_root: Path, project: str, blockers: list[str]
) -> dict:
    marker = lock_root / f"{project}.uncertain"
    if not marker.exists() and not marker.is_symlink():
        return {"marker_present": False, "marker_valid": None}
    try:
        info = marker.lstat()
        valid = (
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600
        )
    except OSError:
        valid = False
    blockers.append("unresolved_uncertainty_marker")
    if not valid:
        blockers.append("uncertainty_marker_malformed_or_unsafe")
    return {"marker_present": True, "marker_valid": valid}


def plan_baseline_adoption(
    *,
    project_name: str,
    enabled_services: list[str],
    runtime_observations: list[dict],
    expected_runtime_contract: dict[str, dict],
    restore_inputs: list[dict],
    state_root: str | Path,
    lock_root: str | Path = DEFAULT_LOCK_ROOT,
    release_path: str | Path,
    model_store: str | Path,
    repository_root: Path = REPOSITORY_ROOT,
    release_loader: Callable = load_release,
    model_checker: Callable = check_models,
    now_epoch: float | None = None,
) -> dict:
    """Return a canonical adoption plan using caller-supplied read-only evidence."""
    blockers: list[str] = []
    current_epoch = time.time() if now_epoch is None else now_epoch
    if not isinstance(project_name, str) or not PROJECT_KEY.fullmatch(project_name):
        raise ValueError("Compose project identity is invalid")
    state_root = Path(state_root)
    lock_root = Path(lock_root)
    state = _state_observation(state_root, project_name, blockers)
    uncertainty = _uncertainty_observation(lock_root, project_name, blockers)

    release_identity = {"release_version": None, "descriptor_sha256": None}
    release = None
    try:
        release = release_loader(release_path, repository_root)
        release_file = Path(release_path)
        release_identity = {
            "release_version": release["release_version"],
            "descriptor_sha256": hashlib.sha256(release_file.read_bytes()).hexdigest(),
        }
    except Exception:
        blockers.append("release_descriptor_unavailable_or_invalid")

    selected: list[str] = []
    model_identities: dict[str, list[dict]] = {}
    model_artifact_details: dict[str, list[dict]] = {}
    if release is not None:
        try:
            selected = resolve_services(release["services"], enabled_services)
            if set(selected) != set(release["services"]):
                blockers.append("service_selection_not_complete_release_set")
            compose_path = repository_root / "deployments/compose/compose.yaml"
            compose_data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
            if set(compose_data["services"]) != set(release["services"]):
                blockers.append("compose_release_service_registry_mismatch")
            try:
                model_results = model_checker(release, model_store, repository_root)
                result_ids = {item.artifact_id for item in model_results}
                expected_ids = {
                    model["id"]
                    for name in selected
                    for model in release["services"][name]["required_model_artifacts"]
                }
                if result_ids != expected_ids:
                    blockers.append("model_artifact_verification_incomplete")
                for name in selected:
                    model_identities[name] = [
                        {
                            "model_id": item["id"],
                            "revision": item["revision"],
                            "manifest_sha256": item["manifest_sha256"],
                        }
                        for item in release["services"][name][
                            "required_model_artifacts"
                        ]
                    ]
                    model_artifact_details[name] = []
                    for model in release["services"][name]["required_model_artifacts"]:
                        manifest = load_artifact_manifest(
                            repository_root / model["manifest_path"],
                            model["manifest_sha256"],
                        )
                        model_artifact_details[name].append(
                            {
                                "model_id": model["id"],
                                "revision": model["revision"],
                                "manifest_sha256": model["manifest_sha256"],
                                "files": [
                                    {
                                        "path": file["path"],
                                        "size_bytes": file["size_bytes"],
                                        "sha256": file["sha256"],
                                    }
                                    for file in manifest["files"]
                                ],
                            }
                        )
            except (ModelProvisionError, OSError, ValueError):
                blockers.append("model_artifacts_missing_or_invalid")
        except (ServiceSelectionError, OSError, ValueError, KeyError, TypeError):
            blockers.append("service_selection_or_registry_invalid")

    restores = _restore_inputs(restore_inputs, selected, blockers)
    observed = {}
    if not isinstance(runtime_observations, list):
        blockers.append("runtime_observations_missing_or_invalid")
        runtime_observations = []
    for item in runtime_observations:
        if not isinstance(item, dict) or set(item) != RUNTIME_FIELDS:
            blockers.append("runtime_observation_schema_invalid")
            continue
        name = item["service"]
        if not isinstance(name, str) or name in observed:
            blockers.append("runtime_service_identity_ambiguous")
            continue
        observed[name] = item
    if set(observed) != set(selected):
        blockers.append("runtime_service_selection_mismatch")
    if not isinstance(expected_runtime_contract, dict) or set(
        expected_runtime_contract
    ) != set(selected):
        blockers.append("expected_runtime_contract_missing_or_incomplete")
        expected_runtime_contract = {}
    runtime_contract_for_plan = {}
    service_identities = {}
    for name in selected:
        item = observed.get(name)
        if item is None:
            blockers.append(f"{name}:runtime_observation_missing")
            continue
        expected_release = release["services"][name] if release else {}
        readiness = item["readiness"]
        required_probe = (
            "readiness"
            if "readiness" in expected_release.get("capabilities", [])
            else "health"
        )
        readiness_ok = (
            isinstance(readiness, dict)
            and set(readiness)
            == {"status", "capability", "evidence_sha256", "observed_at_epoch"}
            and readiness["status"] == "READY"
            and readiness["capability"] == required_probe
            and _digest(readiness["evidence_sha256"])
            and type(readiness["observed_at_epoch"]) in (int, float)
            and 0 <= current_epoch - readiness["observed_at_epoch"] <= 300
        )
        expected = expected_runtime_contract.get(name, {})
        checks = {
            "project": item["project_name"] == project_name,
            "container": isinstance(item["container_id"], str)
            and bool(item["container_id"]),
            "image_id": isinstance(item["image_id"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", item["image_id"]) is not None,
            "compose_config_hash": _digest(item["compose_config_hash"]),
            "health": item["state"] == "running"
            and item["health"] == "healthy"
            and readiness_ok,
            "image": (
                item["image_reference"] == expected_release.get("image")
                and _digest(item["image_manifest_sha256"])
                and item["image_manifest_sha256"]
                == expected_release.get("image", "").split("sha256:")[-1]
            ),
            "platform": item["platform"] == expected_release.get("platform"),
            "provenance": (
                isinstance(item["provenance"], dict)
                and set(item["provenance"])
                == {
                    "verified",
                    "evidence_sha256",
                    "image_reference",
                    "image_manifest_sha256",
                    "platform",
                }
                and item["provenance"]["verified"] is True
                and _digest(item["provenance"]["evidence_sha256"])
                and item["provenance"]["image_reference"] == item["image_reference"]
                and item["provenance"]["image_manifest_sha256"]
                == item["image_manifest_sha256"]
                and item["provenance"]["platform"] == item["platform"]
            ),
            "configuration": _digest(item["configuration_sha256"])
            and item["configuration_sha256"] == expected.get("configuration_sha256")
            and (
                name not in restores
                or item["configuration_sha256"]
                == restores.get(name, {}).get("configuration_sha256")
            ),
            "runtime": _digest(item["runtime_identity_sha256"])
            and item["runtime_identity_sha256"]
            == expected.get("runtime_identity_sha256")
            and (
                name not in restores
                or item["runtime_identity_sha256"]
                == restores.get(name, {}).get("runtime_sha256")
            ),
            "models": item["model_identities"] == model_identities.get(name, []),
            "security": item["uid"] == 65532
            and item["gid"] == 65532
            and isinstance(item["supplementary_gids"], list)
            and all(type(gid) is int for gid in item["supplementary_gids"]),
            "security_identity": item["read_only_rootfs"] is True
            and item["cap_drop"] == ["ALL"]
            and "no-new-privileges:true" in item["security_opt"]
            and item["privileged"] is False
            and item["no_new_privileges"] is True,
            "compatibility": item["compatible"] is True,
        }
        contract_fields = (
            "mounts",
            "networks",
            "ports",
            "uid",
            "gid",
            "supplementary_gids",
            "read_only_rootfs",
            "cap_drop",
            "security_opt",
            "privileged",
            "no_new_privileges",
            "configuration_sha256",
            "runtime_identity_sha256",
        )
        if not isinstance(expected, dict) or set(expected) != set(contract_fields):
            blockers.append(f"{name}:expected_runtime_contract_invalid")
            expected = {}
        for field in contract_fields:
            if field not in expected or item[field] != expected.get(field):
                checks[f"runtime_{field}"] = False
        runtime_contract_for_plan[name] = {
            field: expected.get(field) for field in contract_fields
        }
        for key, passed in checks.items():
            if not passed:
                blockers.append(f"{name}:{key}_verification_failed")
        service_identities[name] = {
            "image_reference": item["image_reference"],
            "image_manifest_sha256": item["image_manifest_sha256"],
            "platform": item["platform"],
            "provenance_evidence_sha256": item["provenance"].get("evidence_sha256")
            if isinstance(item["provenance"], dict)
            else None,
            "model_identities": item["model_identities"],
            "configuration_sha256": item["configuration_sha256"],
            "runtime_identity_sha256": item["runtime_identity_sha256"],
            "health": {
                "state": item["state"],
                "health": item["health"],
                "readiness": item["readiness"],
            },
            "container_id": item["container_id"],
            "image_id": item["image_id"],
            "compose_config_hash": item["compose_config_hash"],
            "mounts": item["mounts"],
            "networks": item["networks"],
            "ports": item["ports"],
            "uid": item["uid"],
            "gid": item["gid"],
            "supplementary_gids": item["supplementary_gids"],
            "read_only_rootfs": item["read_only_rootfs"],
            "cap_drop": item["cap_drop"],
            "security_opt": item["security_opt"],
            "privileged": item["privileged"],
            "no_new_privileges": item["no_new_privileges"],
        }
    for name in sorted(set(observed) - set(selected)):
        blockers.append(f"{name}:unknown_or_unselected_runtime_service")

    blockers = sorted(set(blockers))
    body = {
        "schema_version": 1,
        "project_name": project_name,
        "selected_services": selected,
        "release": release_identity,
        "services": service_identities,
        "models": model_artifact_details,
        "configuration": {
            name: {
                "configuration_snapshot": restores[name]["configuration_snapshot"],
                "configuration_sha256": restores[name]["configuration_sha256"],
                "secret_versions": sorted(restores[name]["secret_versions"]),
                "runtime_definition": restores[name]["runtime_definition"],
                "runtime_sha256": restores[name]["runtime_sha256"],
            }
            for name in sorted(restores)
        },
        "expected_runtime_contract": runtime_contract_for_plan,
        "runtime_observations": {
            name: service_identities[name] for name in sorted(service_identities)
        },
        "deployment_state": state,
        "uncertainty": uncertainty,
        "candidate_generation_id": GENERATION_ID + "pending",
        "required_retained_inputs": sorted(
            [f"{name}:configuration_snapshot" for name in selected]
            + [f"{name}:runtime_definition" for name in selected]
            + [
                f"{name}:secret_version:{version}"
                for name in selected
                for version in restores.get(name, {}).get("secret_versions", [])
            ]
            + [f"{name}:image_provenance" for name in selected]
            + [
                f"{name}:model_artifact"
                for name in selected
                for _ in model_identities.get(name, [])
            ]
        ),
        "eligible": not blockers,
        "blockers": blockers,
    }
    fingerprint = _fingerprint(body)
    body["candidate_generation_id"] = "g0-" + fingerprint[:16]
    # Candidate ID is part of the fingerprinted canonical plan body.
    body["plan_fingerprint"] = _fingerprint(body)
    return body
