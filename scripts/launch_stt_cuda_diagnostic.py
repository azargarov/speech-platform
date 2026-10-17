#!/usr/bin/env python3
"""Run a host-side evidence wrapper around an explicitly supplied Docker command."""

from __future__ import annotations

import argparse
import json
import sys

try:
    from stt_cuda_launcher import DiagnosticLauncher, SubprocessRunner
    from stt_cuda_preflight import verify_approved_audio
except ModuleNotFoundError:
    from scripts.stt_cuda_launcher import DiagnosticLauncher, SubprocessRunner
    from scripts.stt_cuda_preflight import verify_approved_audio


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
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--lock-sha256")
    parser.add_argument("--audio-file", required=True)
    parser.add_argument("--audio-checksum-file", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--grace-seconds", type=float, default=5)
    parser.add_argument("--harness-report-name", default="harness-report.json")
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
