"""Check the local release model cache or explicitly fetch pinned artifacts."""

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
from scripts.release_manifest import (
    DEFAULT_RELEASE,
    REPOSITORY_ROOT,
    ReleaseManifestError,
    load_release,
)

DEFAULT_STORE = REPOSITORY_ROOT / "private/model-store"


def _download(model: dict, relative_path: str, destination: Path, maximum_bytes: int):
    if model["source"] != "huggingface_hub":
        raise ModelProvisionError("model source has no configured downloader")
    download_from_huggingface(model, relative_path, destination, maximum_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "fetch"))
    parser.add_argument("--release", default=str(DEFAULT_RELEASE))
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    args = parser.parse_args()
    try:
        release = load_release(args.release)
        if args.action == "check":
            results = check_models(release, args.store, REPOSITORY_ROOT)
        else:
            results = provision_models(release, args.store, REPOSITORY_ROOT, _download)
    except (ModelProvisionError, ReleaseManifestError, OSError) as error:
        print(f"model {args.action} failed: {error}", file=sys.stderr)
        return 2
    for result in results:
        print(f"{result.status}: {result.artifact_id} -> {result.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
