"""Validate the selected versioned platform release descriptor offline."""

from __future__ import annotations

import argparse
import sys

from scripts.release_manifest import DEFAULT_RELEASE, ReleaseManifestError, load_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=str(DEFAULT_RELEASE))
    args = parser.parse_args()
    try:
        release = load_release(args.release)
    except ReleaseManifestError as error:
        print(f"release check failed: {error}", file=sys.stderr)
        return 2
    print(
        f"PASS: {release['release_version']} release descriptor; "
        f"{len(release['services'])} services; "
        f"platforms={','.join(release['supported_platforms'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
