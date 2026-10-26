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
Public STT is local-only by default. Optional Groq STT requires operator
configuration and per-request `X-Allow-Cloud-Audio: true`; text transformation
cloud authorization does not grant audio authorization. See the [Groq STT
operations note](groq-stt.md). Text transformation retains its configured provider ordering, explicit model,
`local_only`, and `allow_cloud` rules. Cloud remains opt-in and a cold or
warming local model does not by itself trigger cloud fallback.

Preflight validates host NVIDIA prerequisites and observes free VRAM headroom;
installation also runs a bounded, network-disabled CUDA visibility probe inside
the built STT and TTS images before container replacement. VRAM can change
immediately and is not reserved. SpeechPlatform
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
resources were released. Use `make install`, `make status`, `make logs`, or
`make stop` in the installation guide. Stop affects only SpeechPlatform services
and preserves images, volumes, model stores, networks, private files and Ollama.

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

## Optional local Ollama

Ollama remains separately managed. When the selected Gateway configuration
enables a local Ollama model, preflight checks the configured endpoint, existing
shared container/network and model metadata. Compose connects Gateway to the
already existing external network only for that configuration. Installation
does not create or alter the network and does not attach, stop, restart, upgrade
or remove the Ollama container. The owner provisions the prerequisites. Metadata
checks use `/api/version` and `/api/tags`; they do not load a model or run inference.

The Compose wrapper fixes project identity to `speech-platform`, selects Docker's
`default` context, and removes ambient deployment overrides before invoking
Compose. `make install` builds Gateway/STT/TTS from a clean committed revision,
validates image labels and container CUDA access before `up`, and retains current
container image IDs under local rollback tags. `make stop` only stops selected
SpeechPlatform services. No supported target runs `down`, removes volumes or
prunes Docker resources.

Obsolete `GATEWAY_EXPECTED_IMAGE_ID` and
`GATEWAY_EXPECTED_SOURCE_REVISION` settings must be manually removed from `.env`
after review; preflight rejects them with a migration message. Never paste
private configuration into reports. For exact-image rollback and return to the
current release, follow [the rollback procedure in the installation guide](installation.md#exact-image-rollback).
It validates retained local image IDs and a private configuration snapshot,
uses Compose with `--no-build --pull never`, and scopes changes to Gateway, STT
and TTS. The older procedure of checking out a prior source revision and
rebuilding it is not an exact-image rollback.

See the [qualification capability matrix](qualification-capabilities.md) for
the public Gateway operations supported by the CLI, contract/runtime gaps and
diagnostic evidence boundaries.
