#!/usr/bin/env python3
"""Run a host-side evidence wrapper around an explicitly supplied Docker command."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

try:
    from stt_cuda_launcher import DiagnosticLauncher, SubprocessRunner
    from stt_cuda_preflight import (
        parse_free_gpu_memory_mib,
        validate_free_gpu_memory,
        verify_approved_audio,
    )
except ModuleNotFoundError:
    from scripts.stt_cuda_launcher import DiagnosticLauncher, SubprocessRunner
    from scripts.stt_cuda_preflight import (
        parse_free_gpu_memory_mib,
        validate_free_gpu_memory,
        verify_approved_audio,
    )


def _load_cuda_http_profile(
    application_config: str,
    deployment_config: str,
    model_revision: str,
    manifest_sha256: str,
):
    """Validate strict configs without importing the container HTTP runtime."""
    try:
        from stt_cuda_http_profile import validate_http_cuda_profile
    except ModuleNotFoundError:
        from scripts.stt_cuda_http_profile import validate_http_cuda_profile
    from services.stt.config import load_application_config, load_deployment_config

    app = load_application_config(application_config)
    deployment = load_deployment_config(deployment_config)
    profile = validate_http_cuda_profile(
        app, deployment, model_revision, manifest_sha256
    )
    return app, deployment, profile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-root", required=True)
    parser.add_argument(
        "--shared-gid",
        type=int,
        required=True,
        help="operator-managed supplemental group for the non-root container",
    )
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--lock-sha256")
    parser.add_argument("--lock-file")
    parser.add_argument("--model-revision")
    parser.add_argument("--model-manifest-sha256")
    parser.add_argument("--audio-file", required=True)
    parser.add_argument("--audio-checksum-file", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--grace-seconds", type=float, required=True)
    parser.add_argument("--harness-report-name", default="harness-report.json")
    parser.add_argument("--cuda-http-profile", action="store_true")
    parser.add_argument("--application-config")
    parser.add_argument("--deployment-config")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Docker argument vector after --; {attempt_dir} and {harness_dir} are substituted",
    )
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("provide a Docker command after --")
    if command[0] != "docker":
        parser.error("only the docker executable is accepted")
    try:
        verify_approved_audio(args.audio_file, args.audio_checksum_file)
    except (OSError, UnicodeError, ValueError):
        parser.error("audio failed approved checksum preflight")
    expected_gpu_index = None
    if args.cuda_http_profile:
        if not args.application_config or not args.deployment_config:
            parser.error(
                "CUDA HTTP profile requires application and deployment configs"
            )
        if args.timeout_seconds > 180:
            parser.error("CUDA HTTP deadline cannot exceed the approved 180 seconds")
        if not args.lock_file:
            parser.error("CUDA HTTP profile requires the pinned dependency lock file")
        if (
            not args.lock_sha256
            or not args.model_revision
            or not args.model_manifest_sha256
        ):
            parser.error(
                "CUDA HTTP profile requires approved lock and model identity digests"
            )
        try:
            app, deployment, _profile = _load_cuda_http_profile(
                args.application_config,
                args.deployment_config,
                args.model_revision,
                args.model_manifest_sha256,
            )
            lock_digest = hashlib.sha256(Path(args.lock_file).read_bytes()).hexdigest()
            if args.lock_sha256 and args.lock_sha256 != lock_digest:
                raise ValueError("dependency lock digest mismatch")
            args.lock_sha256 = lock_digest
            expected_gpu_index = deployment.cuda_device_index
            image_check = subprocess.run(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}|{{.Os}}/{{.Architecture}}",
                    args.image_id,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
            )
            image_identity, separator, image_platform = (
                image_check.stdout.strip().partition("|")
            )
            if (
                not separator
                or image_identity != args.image_id
                or image_platform != args.platform
            ):
                raise ValueError("local image identity or platform mismatch")
            minimum_free = deployment.minimum_free_gpu_bytes_before_load
            probe = subprocess.run(
                [
                    "nvidia-smi",
                    "--id",
                    str(expected_gpu_index),
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=args.timeout_seconds,
            )
            validate_free_gpu_memory(
                parse_free_gpu_memory_mib(probe.stdout), minimum_free
            )
        except Exception:
            parser.error("CUDA HTTP profile or host free-memory preflight failed")
    report = DiagnosticLauncher(
        args.attempt_root, SubprocessRunner(), shared_gid=args.shared_gid
    ).run(
        args.attempt_id,
        command,
        image_id=args.image_id,
        container_name=args.container_name,
        timeout_seconds=args.timeout_seconds,
        grace_seconds=args.grace_seconds,
        harness_report_name=args.harness_report_name,
        platform=args.platform,
        lock_sha256=args.lock_sha256,
        cuda_http_profile=args.cuda_http_profile,
        expected_gpu_index=expected_gpu_index,
    )
    # Print only safe summary fields, never a command, path or process output.
    print(
        json.dumps(
            {key: report[key] for key in ("attempt_id", "outcome", "container")},
            sort_keys=True,
        )
    )
    return 0 if report["outcome"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
