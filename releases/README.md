# Speech Platform Runtime Baselines

`stt-cuda-baseline-001.yaml` records the exact private CUDA STT runtime observed
working on `llm`. Use its source revision, target-local image identity, model
manifest, private configuration checksums, and runtime limits together when
reproducing the smoke test. The target Docker image is local-only; no registry
digest is recorded, and the image archive/build evidence identities are listed
separately.

The private Compose and application configurations remain under ignored
`private/deployment/stt-runtime-smoke/`. The WAV fixtures remain under ignored
`private/audio/` and are not included in Git. Host paths, GPU UUID, ports,
resource limits, engine versions and container ID are environment-specific.
The baseline does not establish a persistent production deployment, capacity,
or peak resource usage. No release-management workflow is implied.

M01C introduces separate GHCR images named `voiceservice-gateway`,
`voiceservice-stt-cpu`, `voiceservice-stt-cuda`, and
`voiceservice-tts-health-only` under
`ghcr.io/azargarov/`. The TTS image contains the health-only service and does
not provide inference. Version tags are discovery labels; use the captured OCI
manifest digest as image identity. Per-image metadata is written to ignored
`dist/release-metadata/` by an explicit `make publish VERSION=vX.Y.Z` call or
the tag release workflow. Publication requires GHCR authentication and is not
part of `make image`. `make image` defaults STT to CPU; `make image
SERVICE=stt VARIANT=cuda` explicitly builds the CUDA variant. Publication
defaults STT to CUDA, while CPU publication requires `VARIANT=cpu`. This does
not alter or replace the CUDA baseline above.

## Platform release descriptor

`voiceservice-v0.1.2.yaml` is the initial versioned platform release contract.
It binds the three M01C immutable GHCR digests to the source revision,
`linux/amd64`, runtime variants, current capabilities, configuration schema
compatibility and service dependencies. Compose remains the service/build
registry; the descriptor only selects immutable release artifacts.

The descriptor references `artifacts/stt-large-v3-turbo.yaml` by canonical
manifest SHA-256. This manifest is copied byte-for-byte from the previously
verified private artifact manifest; it records file names, sizes and SHA-256
checksums, but contains no model bytes. The model stays outside Git images and
Docker contexts.

```sh
make release-check
make model-check MODEL_STORE=private/model-store
make model-fetch MODEL_STORE=private/model-store
```

`release-check` is offline and runs as part of `make verify`. `model-check`
only verifies the local cache. `model-fetch` is the explicit network operation;
it downloads the pinned Hub revision to a staging directory, verifies the
existing artifact contract, then atomically activates it under the manifest
SHA-256. The default store is private and ignored by Git. Existing verified
versions are reused and retained. No command downloads a model at application
startup or changes a running service. Host group permissions and deployment
remain for M01E.
