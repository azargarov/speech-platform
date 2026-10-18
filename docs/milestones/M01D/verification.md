# M01D verification record

Status: local deterministic checks and GitHub CI pass; user validation is pending. No production artifact was fetched and no deployment was performed.

## OBSERVED — workstation checks (2026-10-18)

- `make release-check PYTHON=.venv/bin/python` — exit 0; validated the v0.1.2 descriptor, three Compose service names, immutable image references, architecture and referenced model artifact manifest.
- `.venv/bin/python -m unittest discover -s scripts -p 'test_release_manifest.py' -v` — 9 tests pass, including valid current and CPU STT variants, missing/mutable OCI references, unknown services/variants, unsupported config versions, mismatched model revision/manifest, missing manifest, invalid dependency graph and health-only TTS capability.
- `.venv/bin/python -m unittest discover -s scripts -p 'test_model_artifacts.py' -v` — 11 synthetic tests pass, including missing/corrupt files, size/hash rejection, cache reuse, interrupted transfer and keyboard-interrupt cleanup, preservation of a previously verified artifact, retention of prior versions, and reuse by another service. HTTP adapter tests use mocked responses and make no network request.
- `make verify PYTHON=.venv/bin/python` — exit 0. Ruff lint/format, Go vet/tests/build, config and Compose checks, release check, all script/STT unit tests, governance and STT lock validation passed.
- `git diff --check` — exit 0 at the final local check; rerun before commit.
- `cmp -s private/models/faster-whisper-large-v3-turbo-manifest.yaml releases/artifacts/stt-large-v3-turbo.yaml` — byte-identical. Its raw SHA-256 is `423411b48c216a5d921b6b97a762dc7341c945dc31de036904c39ff74ce81b96`; canonical SHA-256 is `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`, matching the baseline. The inventory totals 1,621,665,983 bytes and retains each historical file hash/size.
- `sha256sum releases/stt-cuda-baseline-001.yaml` — `0c585d62d7d4cf3cf7c74bcf2b9693909cf68ec4529036695c24e882268f0627`, unchanged from the recorded M01C baseline hash.
- `make model-check` against a temporary empty store — returned the expected missing-cache error without creating the store or performing a download. `make -n model-fetch` shows the explicit network invocation; no fetch was executed.
- GitHub Actions `verify` — PASS on implementation commit `b089e1456c8d09073759395f13ae4fe67873ffcc`; [run 39167849767](https://github.com/azargarov/speech-platform/actions/runs/39167849767). `make verify`, `make image`, and `make image VARIANT=cuda` all completed successfully.

## NOT ESTABLISHED

- Download/availability of the real upstream model from this implementation. The prior approved identity and checksums are reused, but no model download was performed in M01D.
- Target-host storage permissions, worker group access, disk capacity, Docker deployment or runtime readiness; these belong to later authorized milestones.
- User validation; pending. M01D remains incomplete until the user validates the implementation.
