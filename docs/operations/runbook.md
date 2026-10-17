# Operations

Use the repository README commands and dedicated speech-platform Compose project. Do not use host-wide prune, network changes or restart unrelated services. All deployments remain operator actions; development verification never starts Compose services.

Override SPEECH_BIND_IP, SPEECH_PORT, GATEWAY_MEMORY, GATEWAY_CPUS, STT_MEMORY, STT_CPUS, TTS_MEMORY and TTS_CPUS in the environment or a private Compose env file. Change process ports/paths/timeouts in configs/*.yaml; keep gateway URL, container port mapping and worker listen ports consistent. Resource defaults exist only in deployment configuration. `make verify` validates rendered Compose overrides too. Readiness failure is expected in M01.

No audio is written by skeletons. Inference providers must use bounded in-memory buffers where practical; future temporary files require private directories, restrictive permissions, deterministic cleanup on success/error/cancellation, and tmpfs mounts sized by configuration. No host audio mount is present. Runtime network downloads are prohibited; build/provisioning network access is separate.

Stop via Compose down to signal processes. Go drains with configured timeout; Python closes its listener within its poll interval and worker request threads are daemonized. Active inference drain/cancellation remains unimplemented. Authentication secrets and token rotation are M04. Do not treat the reserved OpenAPI bearer scheme or auth_mode as enforced auth.

GET /metrics exposes a Prometheus readiness gauge. Inspect structured startup logs and health manually; do not log request bodies. GPU sizing and model cache mounts belong to inference milestones.
