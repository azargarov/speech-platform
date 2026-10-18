# ADR 0011: Publish versioned service images to GHCR

- Status: accepted for M01C implementation; release and milestone validation pending
- Date: 2026-10-18

## Context

M01B established one Make/Compose path for verification and local image builds. M01C needs a controlled way to publish those images while keeping ordinary builds and pull request workflows read-only. The existing TTS process is only a health endpoint and must not be presented as inference.

## Decision

- Keep `make image` and the tracked Compose Dockerfiles as the only build interface. `make image` defaults to the established CPU STT build; `VARIANT=cuda` explicitly selects the existing CUDA Dockerfile through a build-only Compose override. `make publish` defaults STT to CUDA and uses distinct `ghcr.io/azargarov/voiceservice-stt-cuda` and `voiceservice-stt-cpu` repositories, with CPU publication requiring `VARIANT=cpu`. Gateway and health-only TTS keep their separate repositories.
- Require an explicit versioned Make invocation and configured GHCR Docker authentication. No build target publishes automatically.
- Pin base images by OCI digest and dependency locks by SHA-256. Attach full source revision, service, runtime variant, role and STT lock identity as OCI labels. After push, resolve the registry manifest digest, pull that exact digest, and verify `linux/amd64`, revision, service, variant, role and lock before writing minimal JSON metadata under ignored `dist/`.
- Run tag publication only in a job that depends on tag-source verification and image builds. Grant `packages: write` only to that job; the ordinary workflow remains `contents: read`.
- Treat the digest as the immutable artifact identity. Version tags are discovery labels and deployment remains out of scope.

## Consequences

This keeps local and release builds on one definition and records the registry identity needed for future operations. A successful CPU-side build does not establish CUDA runtime behavior. Publishing TTS confirms only its health-only implementation. Dependency and base inputs are version/digest pinned, but this does not claim bit-for-bit identical rebuilds. Package permissions, an actual GHCR publication and remote inspection remain pending the first explicitly approved release.

## Alternatives considered

- A separate release Dockerfile or workflow-specific build: rejected because it duplicates the build definition and can drift from local verification.
- Deployment from the release workflow: rejected; M01C publishes artifacts only and does not operate the server.
- Publishing TTS under a generic functional name: rejected because it would overstate implemented behavior.
