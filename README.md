# SpeechPlatform

SpeechPlatform is an API service for speech processing and text transformation. It provides authenticated HTTP endpoints that separate client applications can use. Linux desktop, Android and iOS clients are separate projects; they are not implemented in this repository.

## Capabilities

- **Speech to text (STT):** local Faster-Whisper transcription. Optional Groq transcription is separately configured and disabled in the canonical Gateway configuration.
- **Text to speech (TTS):** local VoxCPM2 synthesis with plain text and a bounded SSML subset, returning WAV audio.
- **Text transformation and translation:** Gateway routing to local Ollama Qwen or configured Groq text models. Translation requests use the same endpoint and support target-language options for English, Swedish and Russian.

Speech translation and text translation are distinct. The currently configured local STT model, `large-v3-turbo`, does not support cross-language translation. Use `/v1/text/transformations` with `target_language` to translate existing text.

Text transformation supports `Raw`, `Written`, `Polite` and `Diplomatic` modes, with `Normal`, `Concise` and `Structured` formats. Raw with no target language returns the input unchanged; Raw supports Normal format only. Style and translation options combine in one API request; no separate Written operation is required. The API accepts these options, but generated language quality is not guaranteed: M07 qualification found material omissions, language switches and unsupported additions across models. Review generated text before use; see the [M07B2 findings](docs/milestones/M07B2/verification.md).

The canonical [`configs/gateway.yaml`](configs/gateway.yaml) enables `local-qwen`, `groq-qwen` and `groq-gpt-oss` in ordered selection. When no model is specified, only models allowed by the request and Gateway policy are candidates; ordered selection may try a later candidate after an earlier provider failure. An explicitly selected model never falls back. The qualification CLI is local-only by default; `--allow-cloud` explicitly permits cloud routing for that request, but Gateway policy and credentials still apply. Direct API clients must note that `local_only` currently defaults to `false`; set it to `true` on requests that must be local-only. Canonical text-cloud policy is enabled and Groq credentials are optional. Groq STT separately requires operator enablement and per-request audio consent. No Groq TTS provider is implemented.

The text endpoint accepts an optional request-local `system_prompt`. The qualification CLI's `--prompt-file` sends a UTF-8 prompt for one request only; it does not change the configured Gateway prompt. Treat prompt files as trusted operator-controlled input.

## Architecture

Clients authenticate to the Gateway, which validates public API requests and routes them to independent STT and TTS workers or configured text providers. Worker networking is private. The Gateway has outbound HTTPS access for configured cloud providers. Ollama is shared and managed outside SpeechPlatform; SpeechPlatform checks its configured endpoint/model but does not manage Ollama's lifecycle.

SpeechPlatform is an API-based service platform, not a client application. See the [architecture overview](docs/architecture/overview.md) for service boundaries and the [OpenAPI contract](api/openapi/public-v1.yaml) for public routes and request schemas.

## Quick start

Requirements include Linux amd64, Docker Engine and Compose, Git, Make, Python 3.12+, Go 1.24+, and any selected worker model artifacts described in the [installation guide](docs/operations/installation.md). Selecting STT or TTS for deployment requires a compatible NVIDIA driver and NVIDIA Container Toolkit. A fresh Gateway-only configuration must disable STT/TTS capabilities; an update that leaves either enabled still requires its existing compatible, healthy worker. Gateway-only deployment skips worker image builds and GPU probes, but local text inference still requires the separately managed Ollama endpoint and model.

The default install selects the full Gateway, STT and TTS stack. Configure the private deployment environment first, then run:

```sh
git clone https://github.com/azargarov/speech-platform.git
cd speech-platform
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make init
# Review .env and provision required model artifacts; see the installation guide.
make preflight PYTHON=.venv/bin/python
make install PYTHON=.venv/bin/python
make status PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
```

Component-scoped installation is supported, for example `make install COMPONENTS=gateway PYTHON=.venv/bin/python`. Preflight checks selected services and verifies enabled workers that are left running. See the [installation guide](docs/operations/installation.md) for prerequisites, model provisioning, configuration, rollback and recovery.

## Qualification examples

Use the existing CLI to send a local transformation request:

```sh
.venv/bin/python -m scripts.qualify transform \
  --text-file samples/text/ru-rude.txt \
  --mode diplomatic --format normal --target-language none \
  --model local-qwen
```

The CLI also exposes local speech qualification:

```sh
.venv/bin/python -m scripts.qualify stt --audio /path/to/private-audio.wav
.venv/bin/python -m scripts.qualify tts --text 'Synthetic speech.' --output private/audio/qualified.wav
```

To test a one-request prompt override, add `--prompt-file`:

```sh
.venv/bin/python -m scripts.qualify transform \
  --text 'Synthetic text.' --mode written --model local-qwen \
  --prompt-file /path/to/operator-prompt.txt
```

To explicitly permit a configured cloud model for a request, add `--model groq-qwen --allow-cloud` (or select `groq-gpt-oss`). This requires Gateway cloud policy to permit routing and usable Groq credentials. The canonical `groq-qwen` model uses `max_completion_tokens: 512`; `groq-gpt-oss` uses 1024. These settings are in [`configs/gateway.yaml`](configs/gateway.yaml).

Supply a one-request prompt override with `--prompt-file /path/to/operator-prompt.txt`; the supplied file is sent as request data and is not saved in ordinary reports. See the [`scripts.qualify` guide](docs/operations/qualification-cli.md) for all options. The CLI's HTTP result and diagnostics measure technical behavior; they do not score semantic or linguistic quality. Reports and evidence can contain sensitive data; `private/` is the recommended output location, and explicit output elsewhere may be committed if added to Git.

Direct API clients authenticate each operation with the bearer token and should set `local_only: true` when cloud routing is not intended. For example, after loading the private `.env` values into the shell:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer ${SPEECH_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"text":"Hej, vi ses imorgon.","mode":"written","format":"normal","target_language":"en","model":"local-qwen","local_only":true}' \
  http://127.0.0.1:8080/v1/text/transformations
```

## Configuration and privacy

- `configs/gateway.yaml` is the canonical, tracked Gateway runtime configuration. STT and TTS retain their own tracked configuration files under `configs/`.
- `.env` contains operator-specific deployment values and `SPEECH_API_TOKEN`; `make init` creates a private file and does not overwrite existing settings.
- Provider credentials belong in `private/cloud.env` or another protected file selected by `GATEWAY_SECRETS_FILE`. Do not put credentials in tracked YAML, reports or command arguments.
- The Gateway requires bearer authentication for API routes. Text-cloud eligibility depends on `local_only` and Gateway cloud policy; see the API-default note above. Groq audio has separate per-request consent.
- Audio, transcripts, prompts and generated text are not written to ordinary service logs. Qualification evidence that retains request/response content must be protected and deleted when no longer needed.

For API details see [OpenAPI](api/openapi/public-v1.yaml); for command examples see the [CLI reference](docs/cli/reference.md); for deployment and operations see the [operations documentation](docs/operations/installation.md) and [qualification capability matrix](docs/operations/qualification-capabilities.md). Current project and milestone state is in [PLANS.md](PLANS.md); future ideas are tracked separately in [`BACKLOG.md`](BACKLOG.md).

## Project status and limitations

The implementation includes authenticated Gateway APIs, configurable local and cloud text-provider routing, optional cloud STT, component-scoped Docker Compose installation, request-local prompt override, and qualification tooling. Feature implementation does not establish general quality or production readiness. The M07B2 sample found significant model-specific and mode-specific semantic and translation failures and recommended no general model winner. Broad language quality, unattended use, arbitrary concurrent GPU workloads, and production licensing suitability are not established. M07B2 remains pending user validation and closeout; [PLANS.md](PLANS.md) is the source of current milestone status, and [`BACKLOG.md`](BACKLOG.md) contains unapproved future ideas.

No repository-level `LICENSE` file is present. Do not infer a platform-code license from dependency or model licenses.
