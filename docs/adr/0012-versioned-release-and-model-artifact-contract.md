# ADR 0012: Versioned platform release and model artifact contract

- Status: accepted for M01D implementation
- Date: 2026-10-18

## Context

M01C publishes service images independently by immutable OCI digest and records per-image metadata. M01E and M01F need a single platform release identity that binds those images to model artifacts and compatible configuration schemas. The STT artifact manifest and verifier already validate canonical manifest identity, file inventory, sizes, SHA-256 values, path safety and symlinks. Model files must remain external to images and Git.

## Decision

- Add a strict, versioned YAML release descriptor per platform release. It binds the Git source revision, supported platform, service image digests, runtime variants, capabilities, dependencies, configuration compatibility and required model-manifest references. The descriptor selects immutable artifacts; Docker Compose remains the only service/build registry and runtime definition.
- Reuse the existing CTranslate2 artifact manifest schema as the per-model inventory, and the production STT artifact verifier for canonical identity and local file checks. The platform descriptor references the manifest by repository-relative path and canonical SHA-256 and repeats the model repository/revision so validation detects identity disagreement. No model bytes are committed.
- Provision artifacts into a private, content-addressed store at `<store>/<canonical-manifest-sha256>/{manifest.yaml,artifact/}`. A provisioner verifies a cache hit before reuse; otherwise it downloads to a same-filesystem temporary directory, verifies every file, and atomically renames the completed version into place. It never overwrites an existing version and retains previous content-addressed versions for rollback.
- Network access is an explicit local operation. A small source adapter downloads by immutable repository revision; the generic staging, cache and verification path depends only on the artifact manifest and an injected file-download function. The initial adapter supports the approved Hugging Face Hub repository. Application startup remains offline.
- Keep host paths, permissions for a non-root worker, service selection, Compose operations and installed state for M01E. The workstation default uses the repository's ignored `private/` area; no production host is contacted.

## Alternatives considered

- Embedding the model file inventory again in the platform descriptor: rejected because it duplicates the existing artifact manifest and can drift.
- Treating the release descriptor as a second Compose/service registry: rejected; `release-check` validates its service keys against the tracked Compose service names.
- Downloading models at worker startup: rejected because runtime networking and model readiness would be coupled to the upstream repository.
- Replacing or editing `stt-cuda-baseline-001.yaml`: rejected because it is historical runtime evidence, not the new release contract.

## Consequences

Release identity, model integrity and image selection can be validated offline before any later installation operation. The initial release descriptor is scoped to `linux/amd64`, the existing v0.1.2 images and the approved large-v3-turbo artifact. The provisioner does not switch an active service or delete old model versions. Host group access and production store permissions remain to be reviewed in M01E; download availability and upstream policy remain runtime prerequisites when an operator explicitly fetches a missing artifact.
