# Install SpeechPlatform

The supported runtime is root `compose.yaml`. `make preflight` runs the independent,
read-only `scripts/preflight.py`; `make install` still uses
`scripts/product_deployment.py` for build and deployment orchestration.
The historical VoiceService installer has been retired. The descriptor
`releases/voiceservice-v0.1.2.yaml` remains as historical model and image
provenance; it does not describe the current VoxCPM2 deployment.

## Prerequisites

- Linux amd64; Ubuntu 24.04 is the qualified distribution. Docker Engine and
  Compose plugin >=2.24; operator access to the local Unix Docker daemon.
  Remote DOCKER_HOST/DOCKER_CONTEXT endpoints are rejected; no context is switched
  automatically. Deployment overrides must be in `.env`, not a previous shell.
- NVIDIA GPU/compatible driver and NVIDIA Container Toolkit for STT/TTS. Host
  `nvidia-smi` is necessary but insufficient: installation runs a disposable,
  network-disabled CUDA driver/device probe in each selected worker image before
  service creation. A free-VRAM check is an observation, not a reservation or a
  guarantee that models can coexist. SpeechPlatform does not claim exclusive
  GPU ownership; Ollama remains shared and is never evicted by the installer.
  The obsolete Python `require_idle_gpu` helper option is retained only as a
  compatibility check: false/omitted is accepted, while true fails explicitly
  because the installer does not inspect process ownership.
- Python >=3.12 virtualenv dependencies from `requirements-dev.txt`, Go compatible
  with `go.mod` (>=1.24.0), Git,
  network access for uncached image builds (registries, PyPI, GitHub). The Gateway
  image and CI pin Go 1.27.2; host Go is used for config validation. Ordinary
  CI builds do not load models. FFmpeg on the host is useful for audio inspection;
  the TTS image includes its own FFmpeg.
- At least `INSTALL_MIN_FREE_GIB` free on the build and Docker storage filesystems
  (20 GiB default; Docker storage is checked when host-visible),
  plus capacity for pinned STT/TTS artifacts. Allow more disk for uncached CUDA
  wheels/layers. Model provisioning is explicit and never performed by preflight.
- Model-store ownership and configured reader GIDs must let the operator verify
  artifacts and container UID 65532 read them. Ask the store administrator to add
  the operator to the model-reader group, then start a new login session. Runtime
  mounts remain read-only; existing complete stores need not be writable.

## Configure, check and install

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make init
# Review model paths, reader GIDs, GPU indices, project name, bind IP and port.
# Do not print or paste SPEECH_API_TOKEN into logs or reports.
${EDITOR:-vi} .env
make preflight PYTHON=.venv/bin/python
make install PYTHON=.venv/bin/python
make status PYTHON=.venv/bin/python
```

`make init` creates `.env` only when absent, assigns a fresh 32-byte
cryptographically secure API token, and creates `private/`, `private/audio/`
and `private/deployment/` with mode `0700`. It does not replace existing
configuration. The generated `.env` is mode `0600`. Local-only operation needs
no Groq or cloud-text credentials; those remain optional and are configured
only when the corresponding provider is intentionally enabled. For custom
Gateway configuration or provider credentials, use files under `private/` and
review the optional settings in `.env.example`.

Provision missing artifacts separately with `make model-fetch` and
`make tts-model-fetch`, after reviewing paths, ownership and model terms. These
commands may need the store owner's privileges; preflight never invokes sudo,
pulls images, downloads models, creates containers/networks, probes CUDA inside a
container, or loads GPU models. It checks pinned manifest identity, file set and
sizes without hashing multi-gigabyte files; worker startup verifies artifact
SHA-256 before loading. `make tts-model-check` remains an explicit full TTS
integrity check. Configuration checks may populate ordinary Go/Python build caches.

The report groups Host, GPU, Models, Networking, External Providers and Deployment
results. PASS is satisfied, WARN permits installation with the stated limitation,
FAIL blocks it, SKIP is disabled/not applicable. Every WARN/FAIL gives a corrective
next step. Summary counts end with READY TO INSTALL or NOT READY TO INSTALL;
blocking failures return nonzero. Dirty source is WARN during inspection and FAIL
during install. Installation requires reviewed changes committed first.

Single-service operations use the same configuration and preserve other services:

```sh
make preflight SERVICE=stt PYTHON=.venv/bin/python
make install SERVICE=stt PYTHON=.venv/bin/python
make install SERVICE=tts PYTHON=.venv/bin/python
make install SERVICE=gateway PYTHON=.venv/bin/python
make gpu-check SERVICE=tts PYTHON=.venv/bin/python  # explicit disposable GPU probe
```

Gateway-only install requires healthy STT/TTS workers because its readiness checks
both. Default install builds/starts all three. It builds only selected services,
validates local image identity, uses `--no-build --pull never` for activation,
then waits for selected health/readiness. Rerunning converges through Compose.
For the special prebuilt Gateway path, preserve `SERVICE=gateway NO_BUILD=1` plus
explicit expected image ID and source revision; see `.env.example`.

## Model lifecycle and request admission

STT starts without loading Faster-Whisper. First transcription or internal
warmup loads the model; after 60 seconds without active or admitted work it is
unloaded, and a later request reloads it. TTS also loads on demand and retains
its configurable 60-second idle unload. Both workers keep process liveness
(`/healthz`) separate from readiness (`/readyz`); an operational unloaded model
is ready. TTS readiness becomes unavailable for a known permanent artifact or
runtime failure, and recovery is retried after repairing the cause and issuing
new work. Readiness probes do not load models.

Gateway speech queues are independent and FIFO: STT has one active local
Faster-Whisper request plus three waiting requests; TTS has one active plus one
waiting request. Waiting counts against each request's deadline, and queued STT
audio is not buffered. A full queue returns 429; an expired request returns 504.
Groq STT is optional and disabled by default. Public STT remains local-only
unless the operator enables it and each request supplies cloud-audio consent.
These request limits do not reserve GPU memory or guarantee STT/TTS/Ollama coexistence; use
sequential warmups and observe available resources on constrained GPUs.

## Optional local text transformation and Ollama

Default Gateway config disables LLM use and requires no Ollama/cloud service.
Copy `configs/gateway-text.example.yaml` into ignored `private/`, adapt its
listener to `0.0.0.0` and worker URLs to `http://stt:8081` / `http://tts:8082`, then
set `GATEWAY_CONFIG=private/<name>.yaml` in `.env`. Paths are canonicalized; root
Compose also uses a bind-mount object so relative names cannot become named volumes.

An enabled local model requires the externally owned running Ollama container,
its existing internal bridge network and alias `ollama`, endpoint
`http://ollama:11434/api/generate`, and the exact configured model already present.
The Ollama owner prepares these prerequisites explicitly. SpeechPlatform only
inspects/reuses them: it never creates, restarts, upgrades or attaches shared Ollama.
Preflight inspects the existing Ollama container/network and queries
`/api/version` and `/api/tags` without loading a model; missing model or
unreachable required local provider is FAIL. It does not test Gateway container
DNS before installation; service health checks establish runtime connectivity.

Cloud stays opt-in through `selection.allow_cloud: true`. No credentials are
required while false, and cold/unavailable local models do not change routing.
For enabled cloud models, use an HTTPS endpoint and an `api_key_env` identifier;
put the matching KEY=value entries in `private/cloud.env` (0600), or set
`GATEWAY_SECRETS_FILE` to another private file. Do not quote values, use whitespace,
or add unrelated keys. That optional file is passed only to Gateway. Preflight
validates it without contacting paid provider inference endpoints. Public errors
and reports never include credential values. Groq STT credentials are checked
independently when `groq_stt.enabled` is true; they do not depend on text
`allow_cloud`. Cloud audio still requires per-request `X-Allow-Cloud-Audio: true`.

## Smoke test, upgrade and remove

`make test` is the deterministic offline test suite. Live smoke tests are explicit:

```sh
# Every public speech/text API call requires the configured bearer token.
curl --fail-with-body -H 'Authorization: Bearer <SPEECH_API_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"operations":["stt","tts"]}' http://127.0.0.1:8080/v1/models/warmup
curl --fail-with-body -H 'Authorization: Bearer <SPEECH_API_TOKEN>' \
  -H 'Content-Type: application/json' \
  -d '{"text":"This is a synthetic speech test.","language":"en","mode":"extra_high_quality","audio_processing":"gentle"}' \
  http://127.0.0.1:8080/v1/tts/speech -o private/synthetic.wav
make test-stt PYTHON=.venv/bin/python AUDIO=private/synthetic.wav SOURCE_LANGUAGE=en
```

Use the [public contract](../../api/openapi/public-v1.yaml) for SSML and text
transformation. Wait for STT/TTS idle unloading before local LLM experiments on
small GPUs; no deployment lock reserves VRAM. Translation unsupported by the pinned
large-v3-turbo model returns an explicit error, not a fabricated translation.

For an upgrade, check out the approved tag, review `.env` compatibility, then run
preflight/install again. For recovery, select the previous known-good source/image
and matching configuration. No volumes or model stores need deletion.

```sh
make stop SERVICE=tts PYTHON=.venv/bin/python
make remove SERVICE=tts PYTHON=.venv/bin/python
make remove PYTHON=.venv/bin/python  # project containers/internal networks only
```

Removal never uses `-v`, `--rmi` or global cleanup and preserves shared/external
Ollama, models and persistent volumes. Verify the project name belongs to this
checkout before changing resources. Private reports and audio must stay ignored.
