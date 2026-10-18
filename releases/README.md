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
