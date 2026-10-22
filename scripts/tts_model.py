"""Explicitly check or fetch the pinned VoxCPM2 artifact into the shared store."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.model_artifacts import (
    ModelProvisionError,
    check_models,
    download_from_huggingface,
    provision_models,
)
from services.stt.artifacts import load_artifact_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "releases/artifacts/voxcpm2.yaml"
MANIFEST_SHA256 = "04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41"


def _model() -> dict:
    manifest = load_artifact_manifest(MANIFEST_PATH, MANIFEST_SHA256)
    model = manifest["model"]
    artifact = manifest["artifact"]
    return {
        "id": "voxcpm2",
        "source": "huggingface_hub",
        "family": model["family"],
        "repository": model["repository"],
        "revision": model["revision"],
        "artifact_format": artifact["format"],
        "manifest_path": "releases/artifacts/voxcpm2.yaml",
        "manifest_sha256": MANIFEST_SHA256,
    }


def _download(model, relative_path, destination, maximum_bytes):
    download_from_huggingface(model, relative_path, destination, maximum_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "fetch"))
    parser.add_argument("--store", default="/srv/speech-platform/models")
    parser.add_argument("--reader-gid", type=int, default=988)
    parser.add_argument("--owner-uid", type=int, default=0)
    args = parser.parse_args()
    release = {"services": {"tts": {"required_model_artifacts": [_model()]}}}
    try:
        if args.action == "check":
            results = check_models(release, args.store, ROOT)
        else:
            results = provision_models(
                release,
                args.store,
                ROOT,
                _download,
                directory_mode=0o2750,
                file_mode=0o640,
                expected_owner_uid=args.owner_uid,
                expected_group_gid=args.reader_gid,
            )
    except (ModelProvisionError, OSError, ValueError) as error:
        print(f"TTS model {args.action} failed: {error}", file=sys.stderr)
        return 2
    for result in results:
        print(f"{result.status}: {result.artifact_id} -> {result.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
