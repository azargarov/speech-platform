# Operations

Use the installation guide and the dedicated root Compose project. Do not use
host-wide prune, restart unrelated services, or remove persistent model data.
The current Gateway, STT and TTS services are inference-capable; historical
M01/M02 milestone records retain their original skeleton descriptions as
historical evidence, not as current runtime instructions.

Gateway `/healthz` reports process liveness. Gateway `/readyz` requires its
configured STT and TTS workers to report ready. Worker `/healthz` reports
process liveness, while `/readyz` reports ability to accept bounded on-demand
work. An unloaded STT or TTS model is an operational ready state. STT loads
Faster-Whisper on first request or internal warmup and unloads after its
configured idle period (60 seconds by default); TTS uses its existing lazy
loading and configurable 60-second idle unload. TTS readiness is false after a
known permanent artifact/runtime failure; repair the cause and retry through
warmup or synthesis. Readiness probes do not initialize models.

Gateway speech admission is bounded and independent: STT is one active local
request plus three FIFO waiters; TTS is one active request plus one waiter.
Queue time counts against the request deadline. Queued STT uploads are not
buffered. Full queues return 429, and request deadline exhaustion returns 504.
Current public STT is local-only; Groq STT is not implemented. Text
transformation retains its configured provider ordering, explicit model,
`local_only`, and `allow_cloud` rules. Cloud remains opt-in and a cold or
warming local model does not by itself trigger cloud fallback.

GPU preflight validates the selected device/runtime and observes free VRAM
headroom. The value can change immediately and reserves no memory. SpeechPlatform
does not have exclusive GPU ownership, does not guarantee arbitrary STT/TTS/
Ollama model coexistence, and never evicts a shared Ollama model. Observe
resource use and qualify the specific workload; preserve bounded worker
admission and cleanup behavior.

Normal shutdown sends SIGTERM through Compose. Gateway cancels its root context,
closes admission to new/queued speech work, then calls `http.Server.Shutdown`
with its configured deadline. Go's server shutdown does not forcibly cancel
active request contexts; active inference or response delivery may continue
until its request deadline or completion. If the shutdown deadline expires,
the process can be terminated by its supervisor while worker-side native
cleanup remains uncertain. Do not interpret a timeout as proof that CUDA
resources were released. Use the service-scoped install/status/logs/stop/remove
commands in the installation guide; removal preserves volumes, images and
external Ollama resources.

`/metrics` exposes readiness and text-transformation counters. Inspect sanitized
logs and health manually; request bodies, audio and transcripts must not be
logged. Runtime model downloads are disabled; provisioning is a separate
operator action.

## GHCR image publication

M01C publishes image artifacts only; it does not deploy or change running
services. Ordinary `make image` and pull-request verification do not publish.
For a local release, authenticate first with Docker using an account/token that
can write packages in `azargarov`, then explicitly run
`make publish VERSION=vX.Y.Z` (or add `SERVICE=gateway`, `stt`, or `tts`). The
target validates the version/service before building, resolves stable Compose-owned local image references through rendered configuration, and inspects them directly without requiring Compose containers. It validates every selected image before creating registry tags or pushing any selected image. Never put a token in a command argument or repository
file. GitHub Actions uses the scoped `GITHUB_TOKEN` only in the publish job.

`make image` defaults STT to CPU. Use `make image SERVICE=stt VARIANT=cuda`
for the CUDA production build, or `make image VARIANT=cuda` to build all
services with CUDA STT. The build never falls back to CPU after a CUDA error.
Publication defaults STT to CUDA; use `make publish SERVICE=stt VARIANT=cpu
VERSION=vX.Y.Z` only for an explicitly requested CPU publication. The variant
is part of the repository name, not inferred from a mutable tag.

Historical published repositories include
`ghcr.io/azargarov/voiceservice-gateway`, `voiceservice-stt-cpu`,
`voiceservice-stt-cuda`, and `voiceservice-tts-health-only`. The last name is a
historical health-only artifact and is not the current root-Compose VoxCPM2
worker. Each successful publish writes minimal metadata to
`dist/release-metadata/`; retain
that record with the actual `repository@digest` reference. Metadata includes
service, runtime variant and applicable dependency-lock SHA-256. The publisher
pulls that exact digest to verify `linux/amd64`, source revision, service,
variant and role labels. No model artifacts, private configuration,
credentials or local audio fixtures are release inputs. A version tag does not
authorize installation: deployment is a separate milestone and operator action.

## Optional local Ollama networking

The root Compose stack remains the canonical SpeechPlatform deployment. The
private `.env` may set `GATEWAY_CONFIG` to a deployment-specific file inside
the repository; the default is `configs/gateway.yaml`. The installer rejects
paths outside the repository and symlink traversal, validates the selected
Gateway configuration and mounts it read-only. When that selected config
enables an active local Ollama-backed model, `make plan`
reports the external Ollama network requirement and `make install`
prepares it before building or starting SpeechPlatform services. The installer
creates `speech-platform_ollama_private` as a Docker-managed internal user
bridge when it is missing, validates `driver=bridge` and `internal=true` when
it exists, and attaches the existing running Ollama container with the network
alias `ollama`. It preserves Ollama's other network attachments and published
ports. It never installs, starts, restarts or removes Ollama or its models.

The optional settings in the private `.env` are:

```dotenv
OLLAMA_CONTAINER_NAME=ollama
OLLAMA_NETWORK_NAME=speech-platform_ollama_private
```

Set `OLLAMA_CONTAINER_NAME` to the existing Docker container name when it is
not `ollama`. The Gateway provider endpoint must use
`http://ollama:11434/api/generate`; the configured Docker alias remains
`ollama`. The network name may be customized in `.env`. The installer fails
before deploying SpeechPlatform if the Ollama container is absent or stopped,
the network has conflicting driver/internal settings, or the existing network
attachment lacks the required alias. It does not silently repair a conflicting
network or detach/reconnect an attached Ollama container.

If local Ollama is disabled or no enabled local Ollama model is configured,
the optional network is not prepared or included in Compose. Legacy STT/TTS-only
installations remain unchanged. Fresh installation requires an operator-managed
running Ollama container and installed model; this workflow does not install
Ollama, fetch models, or enable cloud inference. `allow_cloud` remains an
explicit Gateway configuration choice and is false in the M05B candidate.

After deployment, the installer runs the Gateway binary as a temporary
Compose task using `--check-ollama`. That command checks Docker DNS resolution,
TCP port 11434 and read-only `GET /api/version`; it does not invoke an
inference endpoint. A connectivity failure stops the install command and leaves
all existing shared Ollama resources intact. The canonical worker health checks
still determine whether Gateway, STT and TTS are ready.

For a Gateway-only update over healthy existing STT/TTS workers, use
`make install SERVICE=gateway`. It prepares/reuses the Ollama path as needed,
builds only Gateway and runs Compose with `--no-deps`; existing STT/TTS
containers are not intentionally recreated. A fresh full installation uses
`make install` without `SERVICE`.

Gateway rollback and Ollama-network cleanup are separate operations. Rolling
back Gateway with the known-good Compose/config does not disconnect or restart
Ollama. Removing the SpeechPlatform project through Compose does not remove the
external network. Do not remove the network as part of normal rollback. If an
operator explicitly decides to retire the network, first deploy Gateway
without the Ollama overlay, then inspect membership and the Ollama attachments:

```sh
docker network inspect "${OLLAMA_NETWORK_NAME:-speech-platform_ollama_private}" \
  --format '{{json .Containers}}'
docker inspect "${OLLAMA_CONTAINER_NAME:-ollama}" \
  --format '{{json .NetworkSettings.Networks}}'
```

Stop if the network contains any unexpected member. Only after confirming the
Gateway has detached and the operator has reviewed remaining users may the
operator explicitly disconnect Ollama and remove the now-empty network:

```sh
docker network disconnect "${OLLAMA_NETWORK_NAME:-speech-platform_ollama_private}" \
  "${OLLAMA_CONTAINER_NAME:-ollama}"
docker network rm "${OLLAMA_NETWORK_NAME:-speech-platform_ollama_private}"
```

The deployment tooling never runs these cleanup commands. It does not run
whole-host prune or delete externally managed networks.

### Reusing an approved local Gateway image

The canonical installer defaults to its normal build path. For a specifically
approved prebuilt Gateway, the private `.env` may pin both the full expected
local image ID and its full source revision, then an operator may request the
narrow no-build path:

```dotenv
GATEWAY_EXPECTED_IMAGE_ID=sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159
GATEWAY_EXPECTED_SOURCE_REVISION=c3f0079227af573f7715640afa5b229a22c46ab6
```

After separately approved implementation/commit and deployment authorization,
run `sudo -v`, then `make plan SERVICE=gateway NO_BUILD=1` and
`make install SERVICE=gateway NO_BUILD=1`. This mode is Gateway-only. It checks
that the source revision is an ancestor of the clean checkout, verifies the
Gateway build inputs have not changed since that revision, and inspects the
local tag for the exact image ID, revision/service/role/runtime labels and
`linux/amd64` platform. It rechecks immediately before recreation and uses
Compose `--no-build --pull never --no-deps`; it cannot pull or rebuild. Missing
or mismatched identity aborts the operation. Existing installer preflight,
Ollama network preparation, readiness and read-only connectivity checks remain
active. It does not alter model-store permissions or bypass the `sudo -v`
requirement. The six M06 files and local documentation must be preserved using
the private same-checkout backup procedure documented in the M05B Stage 2C
readiness record so the clean-worktree gate remains effective. Rollback remains
a separately authorized Gateway-only action and does not detach/restart
Ollama or remove its external network.
