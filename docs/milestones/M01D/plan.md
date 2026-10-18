# M01D plan — release manifest and model artifact management

Status: implementation in progress; local deterministic verification is planned and user validation/closeout remain pending.

## Objective and scope

Define a strict versioned platform release contract using the published v0.1.2 OCI digests, and provide offline model verification plus an explicitly invoked, staged local model fetch. Reuse the existing STT artifact manifest and verifier. Models stay outside Git, Docker images, runtime startup and the production server.

The release descriptor binds source revision, supported platform, service image digests, runtime variants, truthful capabilities, required models, model repository/revision, artifact-manifest identity, config compatibility and service dependencies. Compose remains the service/build registry. The initial artifact is `dropbox-dash/faster-whisper-large-v3-turbo` at revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` with the exact previously verified five-file inventory.

The local content-addressed store follows the baseline's manifest-SHA-named model release convention. The provisioner verifies a cache hit; otherwise it stages and validates every file before atomic activation. Existing versions are retained. Network access is limited to explicit `make model-fetch`; there is no deployment or startup download.

## Dependencies

- M01C PASS and the v0.1.2 image digests/metadata.
- M02's previously verified model artifact manifest and existing `verify_artifact` implementation.
- Existing STT application/deployment schema loaders.

## Deliverables

- `releases/voiceservice-v0.1.2.yaml` and a reference to the existing-format artifact manifest.
- Strict offline `make release-check`, included in `make verify`.
- Read-only `make model-check` for the local private cache and explicit-network `make model-fetch` for staged provisioning.
- Synthetic regression tests for identity/schema failures, missing/corrupt files, cache reuse, incomplete transfers, and preservation of existing artifacts.
- ADR 0012 and updated release/M01D documentation.

## Acceptance

- Reject unknown Compose services, unsupported runtime variants/platforms/config schema versions, mutable/missing OCI identities and model identity/manifest mismatch.
- Resolve all required artifact files from the existing versioned manifest; verify file set, size and SHA-256 before activation.
- Reuse valid digest-addressed cache entries, never overwrite a corrupt/previous version, remove incomplete staging on failure and retain older verified versions.
- `make verify PYTHON=.venv/bin/python`, focused synthetic tests, formatting/lint, governance checks and `git diff --check` pass; GitHub CI passes on the implementation commit.
- User validates the contract and closeout before M01D can be marked PASS.

## Verification commands

```sh
make release-check PYTHON=.venv/bin/python
.venv/bin/python -m unittest discover -s scripts -p 'test_release_manifest.py' -v
.venv/bin/python -m unittest discover -s scripts -p 'test_model_artifacts.py' -v
make verify PYTHON=.venv/bin/python
make governance-check PYTHON=.venv/bin/python
git diff --check
```

`make model-fetch` against the real 1.62 GB artifact is not required for deterministic verification and must not be run against the production server.

## Exclusions and risks

No Docker deployment, target-server access, service startup, release selection/switching, private host configuration, worker permission changes, install/update/rollback, TTS inference, Gateway routing, model replacement or CUDA inference. The default store is local and private; M01E must review target filesystem ownership/group-read access and the explicit source-fetch policy before installation.
