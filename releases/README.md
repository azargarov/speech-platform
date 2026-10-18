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
