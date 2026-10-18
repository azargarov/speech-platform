# M01C implementation record

Status: implementation committed; v0.1.2 published and independently verified by the user from XMG. M01C closeout evidence is recorded in [verification](verification.md) and [result](result.md).

## Changes

- Added `make publish VERSION=...` and optional service selection with Make-time unknown-service rejection.
- Added a publisher that calls the existing `make image`, tags the Compose image, pushes to GHCR, resolves the registry digest with Buildx, pulls the digest and verifies the image platform and OCI source/role labels before emitting JSON metadata to ignored `dist/release-metadata/`.
- Added OCI source-revision and service-role labels to existing Dockerfiles and passed role/revision build arguments through the existing Compose build definitions.
- Added explicit CPU/CUDA STT selection to `make image`; default build behavior remains CPU. The CUDA build-only Compose override uses the existing `worker-stt-cuda.Dockerfile`, pinned Python base digest, CUDA lock hash and `linux/amd64`. The existing runtime CUDA overlay remains build-free.
- Added explicit service and runtime-variant labels plus CPU/CUDA dependency-lock labels for STT images. CUDA publication is the default; CPU publication requires `VARIANT=cpu` and uses the distinct `voiceservice-stt-cpu` repository, while CUDA uses `voiceservice-stt-cuda`.
- Extended publisher validation and metadata with service/runtime variant and dependency-lock SHA-256; it verifies local and registry service, variant, role, revision, platform and applicable lock labels. A CUDA build error stops publication without CPU fallback.
- Updated the tag workflow to build the CPU default and an explicit CUDA variant before the dependent publish job; publication explicitly requests CUDA.
- Pinned the existing Gateway and CPU worker base images by their observed OCI index digests to stabilize release build inputs.
- Added a version-tag workflow. Verification and image builds are a prerequisite job; only the publish job has `packages: write` and logs in using the scoped `GITHUB_TOKEN`. Existing PR verification remains read-only.
- Named the TTS package `voiceservice-tts-health-only` and labeled it `tts-health-only`.
- Added tests for release version parsing, bounded service selection and GHCR auth configuration.
- Updated the roadmap, operational documentation and releases README. Added proposed [ADR 0011](../../../docs/adr/0011-ghcr-publication.md).

The earlier release gate failed because the publisher selected CPU STT and the implementation was uncommitted. The variant correction addressed that defect. Later, the approved annotated tag `v0.1.2` published Gateway, CUDA STT, and health-only TTS from commit `bbbeb697c1ae840e084e962fac39db0c19ab7728`; the release workflow succeeded. The user's authenticated XMG manifest inspection confirmed the registry digests match release metadata. The operational baseline remains a compatibility reference only; it does not validate this new image.


## Publisher image-resolution correction

The `v0.1.1` release run 39162673061 built the images, then failed before tagging/pushing because `docker compose images -q` requires created Compose containers. Replaced that lookup with the stable `image:` references rendered from the tracked Compose definitions, followed by `docker image inspect`. Gateway, CPU STT, CUDA STT and health-only TTS now have explicit local image names; CPU and CUDA STT remain distinct. The publisher now validates all selected local image labels, lock identity and platform before any registry tagging or pushing. This does not create containers or publish images.

This resolution fix was included in the successful v0.1.2 publication. The v0.1.0 deprecated artifact-action failure and the v0.1.1 image-resolution failure are retained in the [verification history](verification.md); neither release tag was moved or recreated.
