# Install SpeechPlatform

The supported runtime is root `compose.yaml`. `make preflight` runs independent,
read-only `scripts/preflight.py`. `make install`, `status`, `logs`, and `stop` use
Make and Docker Compose. Focused helpers sanitize Compose invocation, retain
existing image IDs, verify built-image labels and run CUDA visibility probes.
Make and Docker Compose are the supported deployment path.
The historical VoiceService installer has been retired. The descriptor
`releases/voiceservice-v0.1.2.yaml` remains as historical model and image
provenance; it does not describe the current VoxCPM2 deployment.

## Prerequisites

- Linux amd64; Ubuntu 24.04 is the qualified distribution. Docker Engine and
  Compose plugin >=2.24; operator access to the local Unix Docker daemon.
  Installation explicitly uses the `default` Docker context and requires its
  endpoint to be local Unix. Deployment overrides belong in `.env`, not a prior
  shell. The Compose project is fixed to `speech-platform`.
- NVIDIA GPU/compatible driver and NVIDIA Container Toolkit for STT/TTS. Host
  `nvidia-smi` is necessary but insufficient: installation runs a disposable,
  network-disabled CUDA driver/device probe in each selected worker image before
  service creation. A free-VRAM check is an observation, not a reservation or a
  guarantee that models can coexist. SpeechPlatform does not claim exclusive
  GPU ownership; Ollama remains shared and is never evicted by the installer.
  A legacy Python installer option named `require_idle_gpu` is not an active
  guarantee; it fails explicitly because process ownership is not inspected.
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
# Review model paths, reader GIDs, GPU indices, bind IP and port.
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
no Groq or cloud-text credentials. Cloud credentials remain optional even when
a provider is enabled: preflight warns about missing or invalid optional
credentials, Gateway starts, and a request explicitly selecting that provider
returns `provider_unavailable`. For custom
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

Installation always builds and updates the complete three-service stack.
Inspection, logs and stop may select one service:

```sh
make preflight SERVICE=stt PYTHON=.venv/bin/python
make status SERVICE=tts PYTHON=.venv/bin/python
make logs SERVICE=tts PYTHON=.venv/bin/python
make stop SERVICE=tts PYTHON=.venv/bin/python
```

Before service replacement, install checks the clean Git source, read-only
preflight, fixed Compose ownership, and retains current container image IDs under
revision-specific local rollback tags. It builds all services through Compose,
checks source/role/platform labels, runs network-disabled CUDA visibility probes
for STT and TTS, then calls `compose up --no-build --pull never`. Compose waits
for health; bounded readiness requests then check all three services. Installation
never rotates `.env`, downloads models or makes cloud inference requests.
`GATEWAY_EXPECTED_IMAGE_ID` and `GATEWAY_EXPECTED_SOURCE_REVISION` are obsolete;
preflight rejects them with a migration message. Remove those reviewed lines from
`.env` manually before install. The installer never edits private configuration.

## Model lifecycle and request admission

STT starts without loading Faster-Whisper. First transcription or internal
warmup loads the model; after 60 seconds without active or admitted work it is
unloaded, and a later request reloads it. TTS also loads on demand and retains
its configurable 60-second idle unload. Both workers keep process liveness
(`/healthz`) separate from readiness (`/readyz`); an operational unloaded model
is ready. TTS readiness becomes unavailable for a known permanent artifact or
runtime failure, and recovery is retried after repairing the cause and issuing
new work. Readiness probes do not load models.

STT and TTS are currently mandatory deployment components: both worker URLs
are required by Gateway configuration, both Compose services are part of the
default install, and Gateway `/readyz` requires both workers. To support a
disabled STT or TTS capability, the minimum change is to add an explicit
validated enable flag and optional worker URL in Gateway configuration, make
the corresponding Compose service/profile and worker-specific preflight checks
conditional, and have Gateway readiness require only enabled workers. Request
routes would need to return a stable unavailable/disabled error when their
worker is disabled. This work does not change their lifecycle.

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
The example's `text_transform.prompt_file` is relative to the Gateway config
file and points to `../configs/prompts/text-transformation-system.txt`. Compose
mounts `configs/prompts/` read-only at `/configs/prompts/` in the Gateway.
Custom prompt files must remain in that mounted directory and the config path
must resolve to the corresponding mounted file.

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
`allow_cloud`. Missing Groq credentials leave that capability unavailable and
do not affect local STT/TTS. Cloud audio still requires per-request
`X-Allow-Cloud-Audio: true`.

### Updating the text transformation prompt

The active prompt is `configs/prompts/text-transformation-system.txt`, mounted
read-only into the Gateway. Its bytes, excluding one terminal LF (and a CR
immediately before it), are the active prompt text and the input to its SHA-256
fingerprint. The Gateway validates UTF-8, non-empty content, a 64 KiB size
limit, and fit against every enabled model before activation.

After a Gateway version with prompt reload support has been deployed, update
the version-controlled prompt file using a temporary file in the same directory
and an atomic rename. Then signal only the Gateway container:

```sh
docker --context default kill --signal HUP <gateway-container-id>
```

The Gateway logs `text transformation prompt reloaded` with the active
fingerprint after success. A rejected reload logs `text transformation prompt
reload rejected` and leaves the prior snapshot active. Each transformation
response also includes `X-Speech-Prompt-SHA256`; qualification JSON reports
record that value. The request captures one prompt snapshot, so a reload during
an operation affects later requests only. Updating the prompt file does not
change provider/model selection or sampling settings and does not restart the
Gateway. Changes to the prompt-file path itself still require configuration
change and deployment.

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
make test-tts PYTHON=.venv/bin/python OUTPUT=private/audio/tts-smoke.wav
```

The independent API smoke client reads the configured token without displaying
it. STT prints response metadata and transcript to the invoking terminal. TTS
uses a short synthetic phrase and creates a new mode-0600 WAV under `private/`;
it refuses to overwrite an existing output.

Use the [public contract](../../api/openapi/public-v1.yaml) for SSML and text
transformation. Wait for STT/TTS idle unloading before local LLM experiments on
small GPUs; no deployment lock reserves VRAM. Translation unsupported by the pinned
large-v3-turbo model returns an explicit error, not a fabricated translation.

For an upgrade, check out the approved clean revision, review `.env` compatibility,
then run preflight/install. Before building, the installer retains current container
image IDs as local `speech-platform-rollback-<service>:<image-id>` tags.

### Exact-image rollback

Use exact local image objects and a private configuration snapshot. Do not select
a rollback by source revision alone.

1. Record the target Gateway, STT and TTS image IDs from the trusted pre-upgrade
   record. Confirm each image exists and inspect its service-role and source
   labels. Do not use a tag until `docker image inspect` has confirmed its full
   image ID.
2. Snapshot the active `.env`, the configured Gateway YAML and any configured
   private secrets file under a new `private/deployment-backups/<rollback-id>/`
   directory. Keep the directory mode `0700`; keep `.env` and secret files
   `0600`. Point the snapshot `.env` at the copied Gateway YAML and secrets file.
   Leave active `.env`, credentials and source files unchanged. The old
   pre-D02 `.env` backup contains obsolete image-pin entries and fails current
   preflight; use a validated snapshot of the active configuration instead.
3. Give the three exact image IDs a common local rollback tag, then inspect each
   tag and confirm it resolves to its recorded full image ID and correct role.
   For example, replace the placeholders with recorded IDs and one unique tag:

   ```sh
   ROLLBACK_TAG=rollback-<unique-id>
   docker tag "$GATEWAY_IMAGE_ID" "speech-platform-gateway:$ROLLBACK_TAG"
   docker tag "$STT_IMAGE_ID" "speech-platform-stt-cuda:$ROLLBACK_TAG"
   docker tag "$TTS_IMAGE_ID" "speech-platform-tts:$ROLLBACK_TAG"
   docker image inspect "speech-platform-gateway:$ROLLBACK_TAG" \
     "speech-platform-stt-cuda:$ROLLBACK_TAG" \
     "speech-platform-tts:$ROLLBACK_TAG"
   ```

4. Render the complete project with `SOURCE_REVISION=$ROLLBACK_TAG`,
   `GATEWAY_IMAGE=speech-platform-gateway:$ROLLBACK_TAG`, the snapshot `.env`,
   `compose.yaml` and the existing Ollama overlay when configured. Confirm the
   project is `speech-platform`, the only services are Gateway/STT/TTS, each
   image reference is the verified rollback alias, worker/model/config mounts
   are read-only, and Ollama remains an external network. Run each selected
   image's `--check-config` command in a temporary `--network none` container
   before replacing services.
5. Reinspect all three aliases to full image IDs immediately before running:

   ```sh
   SOURCE_REVISION="$ROLLBACK_TAG" \
   GATEWAY_IMAGE="speech-platform-gateway:$ROLLBACK_TAG" \
   docker --context default compose \
     --project-name speech-platform \
     --env-file private/deployment-backups/<rollback-id>/.env \
     -f compose.yaml \
     -f deployments/compose/compose.ollama.yaml \
     up -d --no-build --pull never --wait --wait-timeout 240 \
     gateway stt tts
   ```

   Omit the Ollama overlay only when the selected Gateway config does not use
   local Ollama. This command changes only the three named SpeechPlatform
   services. It does not build, pull, run `down`, remove volumes or alter the
   external Ollama network.
6. Verify health/readiness, container image IDs and labels, authenticated
   Gateway API behavior, and bounded local STT and TTS smoke tests. Check that
   Ollama and unrelated container IDs/start times are unchanged.

To restore the intended release, check out its clean committed revision and run
`make preflight`, `make install`, and `make status` with the active validated
`.env`. Installation rebuilds the three images from that revision, retains the
currently running exact image IDs, and replaces only SpeechPlatform services.
Repeat health, image/source, API and local STT/TTS checks. If rollback or
restoration is incomplete, inspect `make status` and service-scoped `make logs`,
preserve the recorded exact IDs/config snapshot, and restore from a validated
clean revision. Do not use `down`, prune Docker resources, or alter shared
Ollama. If neither a compatible config snapshot nor exact images validate, stop
before replacement.

Model stores and private source configuration are never removed by these steps;
workers mount model stores read-only.

```sh
make stop SERVICE=tts PYTHON=.venv/bin/python
```

`make stop` stops only the selected SpeechPlatform service, or all three when no
service is selected. It preserves containers, images, volumes, networks, models,
private files and shared Ollama. Do not use the legacy `remove` target for normal
operation. Private reports and audio must stay ignored.
