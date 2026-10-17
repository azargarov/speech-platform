"""Lightweight validation for the approved CUDA HTTP experiment profile."""

from __future__ import annotations

import re
from pathlib import Path

try:
    from stt_cuda_diagnostic import validate_cuda_profile
except ModuleNotFoundError:
    from scripts.stt_cuda_diagnostic import validate_cuda_profile


def validate_http_cuda_profile(
    app, deployment, expected_model_revision: str, expected_manifest_sha256: str
) -> dict:
    """Validate the C.3 profile using parsed configs and no HTTP/runtime imports."""
    profile = validate_cuda_profile(app, deployment)
    compute_type = dict(app.backend_options).get("compute_type_cuda")
    if compute_type != "float16":
        raise ValueError("CUDA HTTP validation requires configured float16")
    model = app.models[0]
    if model.identity.upstream_revision != expected_model_revision:
        raise ValueError("application model revision differs from approved artifact")
    if model.manifest_sha256 != expected_manifest_sha256:
        raise ValueError("application manifest differs from approved artifact")
    if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", expected_model_revision):
        raise ValueError("approved model revision is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256):
        raise ValueError("approved model manifest digest is invalid")
    model_mount = Path("/models")
    for artifact_root in deployment.artifact_roots.values():
        if not Path(artifact_root.directory).is_relative_to(model_mount) or not Path(
            artifact_root.manifest
        ).is_relative_to(model_mount):
            raise ValueError("deployment artifact paths must be under the model mount")
    return {
        **profile,
        "compute_type": compute_type,
        "model_revision": expected_model_revision,
        "manifest_sha256": expected_manifest_sha256,
    }
