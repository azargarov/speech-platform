# M01D implementation record

Status: implementation is in place; final local/CI evidence and user validation are being recorded. M01D is not marked PASS.

## Design and boundaries

ADR [0012](../../../docs/adr/0012-versioned-release-and-model-artifact-contract.md) records the release and artifact contract. The release descriptor selects immutable artifacts only; service definitions remain owned by tracked Compose. `release-check` reads Compose service keys rather than maintaining another service list. The generic model store handles repository/revision/file metadata and an injected downloader; source-specific HTTP behavior is isolated in the initial Hugging Face Hub adapter.

The existing artifact manifest schema, canonical digest implementation, and `verify_artifact` file/path validator remain authoritative. A public loader was factored from the existing validator so release validation uses the same shape and canonical digest checks. The exact ignored private artifact manifest was copied byte-for-byte as metadata into `releases/artifacts/`; no model files were copied. The historical CUDA baseline is unchanged.

## Changes

- Added `releases/voiceservice-v0.1.2.yaml` binding source commit `bbbeb697c1ae840e084e962fac39db0c19ab7728`, Gateway, CUDA STT and health-only TTS OCI digests, `linux/amd64`, capability and dependency declarations, and configuration schema compatibility.
- Added the existing-format `releases/artifacts/stt-large-v3-turbo.yaml`, with the approved Hub repository/revision and five exact file sizes/checksums from the previously verified private manifest.
- Added strict offline release validation, including Compose service-name lookup, digest/platform/variant/capability/dependency checks, config versions from the existing STT validators and artifact-manifest cross-checks.
- Added content-addressed model cache verification and staged provisioning under `<store>/<manifest-sha256>/{manifest.yaml,artifact/}`. Cache hits are fully reverified; downloads use an explicit injected transport, pinned Hub revision, HTTPS redirects and a per-file manifest-size bound. Hashes, sizes, and exact file set are validated before atomic rename. Failed staging is removed; prior versions and invalid existing entries are never overwritten.
- Added `make release-check`, `make model-check`, and explicit network target `make model-fetch`. `release-check` and deterministic tests are included in `make verify`; `model-check` and `model-fetch` are not run at application startup.
- Updated the canonical roadmap, release README and M01D milestone records. Added ADR 0012.

## Preserved scope

No model download was run. No server, container, model store, deployment configuration or running service was changed. `releases/stt-cuda-baseline-001.yaml` remains unchanged. TTS remains health-only and Gateway routing remains unimplemented.
