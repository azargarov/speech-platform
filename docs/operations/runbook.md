# Operations

Use the repository README commands and dedicated speech-platform Compose project. Do not use host-wide prune, network changes or restart unrelated services. All deployments remain operator actions; development verification never starts Compose services.

Override SPEECH_BIND_IP, SPEECH_PORT, SPEECH_LISTEN_PORT, GATEWAY_MEMORY, GATEWAY_CPUS, GATEWAY_PIDS, STT_MEMORY, STT_CPUS, STT_PIDS, TTS_MEMORY, TTS_CPUS and TTS_PIDS in the environment or a private Compose env file. `SPEECH_LISTEN_PORT` overrides the Gateway YAML port for both the process and Compose container target; `make compose-check` rejects a mismatch between the YAML default, rendered process environment and published target. `SPEECH_PORT` controls only the host port. Gateway request-size and header/time limits are enforced by the Go server. Worker socket timeouts apply to socket inactivity; `poll_interval_seconds` bounds how long the process waits for its next request before observing a stop signal. Worker request-size limits, model paths and active-inference drain deadlines are deferred until inference handlers are introduced in M02/M03. `make verify` checks the currently rendered Compose configuration and active environment overrides. Readiness failure is expected in M01.

No audio is written by skeletons. Inference providers must use bounded in-memory buffers where practical; future temporary files require private directories, restrictive permissions, deterministic cleanup on success/error/cancellation, and tmpfs mounts sized by configuration. No host audio mount is present. Runtime network downloads are prohibited; build/provisioning network access is separate.

Stop via Compose down to signal processes. Go drains with its configured timeout. Python closes its listener after the configured polling interval (0.5 seconds in sample configs); active worker-request draining is deferred to M02/M03. Authentication configuration and enforcement are M04. Do not treat the reserved OpenAPI bearer scheme as enforced authentication.

GET /metrics exposes a Prometheus readiness gauge. Inspect structured startup logs and health manually; do not log request bodies. GPU sizing and model cache mounts belong to inference milestones.

## GHCR image publication

M01C publishes image artifacts only; it does not deploy or change running
services. Ordinary `make image` and pull-request verification do not publish.
For a local release, authenticate first with Docker using an account/token that
can write packages in `azargarov`, then explicitly run
`make publish VERSION=vX.Y.Z` (or add `SERVICE=gateway`, `stt`, or `tts`). The
target validates the version/service before building and pushes only the
selected service images. Never put a token in a command argument or repository
file. GitHub Actions uses the scoped `GITHUB_TOKEN` only in the publish job.

`make image` defaults STT to CPU. Use `make image SERVICE=stt VARIANT=cuda`
for the CUDA production build, or `make image VARIANT=cuda` to build all
services with CUDA STT. The build never falls back to CPU after a CUDA error.
Publication defaults STT to CUDA; use `make publish SERVICE=stt VARIANT=cpu
VERSION=vX.Y.Z` only for an explicitly requested CPU publication. The variant
is part of the repository name, not inferred from a mutable tag.

Published repositories are `ghcr.io/azargarov/voiceservice-gateway`,
`voiceservice-stt-cpu`, `voiceservice-stt-cuda`, and
`voiceservice-tts-health-only`. The TTS image remains health-only. Each
successful publish writes minimal metadata to `dist/release-metadata/`; retain
that record with the actual `repository@digest` reference. Metadata includes
service, runtime variant and applicable dependency-lock SHA-256. The publisher
pulls that exact digest to verify `linux/amd64`, source revision, service,
variant and role labels. No model artifacts, private configuration,
credentials or local audio fixtures are release inputs. A version tag does not
authorize installation: deployment is a separate milestone and operator action.
