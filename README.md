# SpeechPlatform

SpeechPlatform is a local-first platform for speech processing through an authenticated Gateway API. It provides speech-to-text (STT), text-to-speech (TTS), configurable text transformation and text-based translation. Optional cloud providers are disabled unless explicitly configured and authorized.

## Features

- **STT:** local Faster-Whisper transcription in Russian, English and Swedish, with automatic or selected language handling.
- **TTS:** local VoxCPM2 plain-text speech synthesis and a bounded SSML subset; WAV output.
- **Text transformation and translation:** optional, separately configured Gateway capability. Translation uses the text transformation endpoint. Generated text requires user review.
- **Optional cloud integration:** Groq STT requires configuration and per-request audio consent. Cloud text providers require explicit Gateway configuration and authorization.

Speech translation and text translation are distinct. STT can translate speech only when the selected model supports it; the deployed `large-v3-turbo` configuration does not support cross-language translation. To translate existing text, use `/v1/text/transformations` with `target_language`.

## Architecture

Clients call the Gateway, which authenticates public requests and routes them to separate STT and TTS workers. Text transformation is disabled in the default Gateway configuration. It can be enabled with a private configuration and an existing local Ollama service, or with explicitly configured cloud providers. SpeechPlatform does not manage the lifecycle of shared Ollama.

The standard deployment path is Make + Docker Compose. Model files are provisioned separately, mounted read-only by workers, and are not downloaded at runtime. The Gateway serves HTTP; use its loopback binding for local access. For remote access, put a TLS reverse proxy in front of it and restrict direct access to the Gateway port.

## Requirements

- Linux amd64, Docker Engine and Docker Compose plugin.
- NVIDIA GPU, compatible driver and NVIDIA Container Toolkit for the STT/TTS workers.
- Python 3.12 or newer, Go 1.24 or newer, Git and Make for setup and verification.
- The model artifacts and host model store described in the [installation guide](docs/operations/installation.md).

## Quick Start

This installs the three services from the checked-out source. Before installation, ensure the configured STT and TTS model artifacts are present and readable; see [model provisioning](docs/operations/installation.md#configure-check-and-install).

```sh
git clone https://github.com/azargarov/speech-platform.git
cd speech-platform
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make init
${EDITOR:-vi} .env
make preflight PYTHON=.venv/bin/python
make install PYTHON=.venv/bin/python
make status PYTHON=.venv/bin/python
```

`make init` creates a private `.env` with a random Gateway token and initializes private directories; it does not overwrite existing configuration. Review model paths, GPU indices, bind address and port in `.env` before preflight. Model downloads are explicit (`make model-fetch` and `make tts-model-fetch`). Detailed prerequisites, provisioning, configuration and safeguards are in the [installation guide](docs/operations/installation.md).

## API Examples

Every public speech and text endpoint requires the configured bearer token. Health and readiness endpoints are unauthenticated. Load the private `.env` into the current Bash environment without echoing it, then call the Gateway:

```sh
set -a
. ./.env
set +a

curl --fail-with-body \
  -H "Authorization: Bearer ${SPEECH_API_TOKEN}" \
  -F 'audio=@sample.wav;type=audio/wav' \
  -F 'source_language=auto' \
  -F 'output_language=auto' \
  http://127.0.0.1:8080/v1/stt/transcriptions
```

Text transformation and text translation use the same endpoint. This example requests local-only English translation; text transformation must first be enabled in Gateway configuration.

```sh
curl --fail-with-body \
  -H "Authorization: Bearer ${SPEECH_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"text":"Hej, vi ses imorgon.","mode":"written","format":"normal","target_language":"en","local_only":true}' \
  http://127.0.0.1:8080/v1/text/transformations
```

TTS returns WAV audio:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer ${SPEECH_API_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"text":"Hello from SpeechPlatform.","language":"en","mode":"quality","input_format":"text","audio_processing":"none"}' \
  http://127.0.0.1:8080/v1/tts/speech \
  --output private/audio/speech.wav
```

See the [OpenAPI contract](api/openapi/public-v1.yaml) for request fields, responses and supported options. Never put real tokens in source control, shell scripts or reports. Use HTTPS for traffic beyond loopback; the Gateway itself does not terminate TLS.

## Configuration and Privacy

The Gateway requires `SPEECH_API_TOKEN` for every deployment, including loopback. `make init` generates it; keep `.env` private with restrictive permissions. Keep optional provider credentials in the private secrets file described in the [installation guide](docs/operations/installation.md), not in Git.

STT stays local by default. Sending audio to Groq requires both operator configuration and explicit per-request `X-Allow-Cloud-Audio: true` consent. Text cloud access is controlled separately by Gateway configuration and request options; enabling it is never implicit. Review the [Groq STT guidance](docs/operations/groq-stt.md) before enabling cloud audio.

SpeechPlatform does not log request audio or transcripts by default. Client examples that return transcripts or transformed text display them to the caller, so handle terminal output accordingly. Generated transformations are not guaranteed to preserve meaning and require user review. Model, dataset and generated-output licensing may differ from the platform code; review the applicable terms before deployment or redistribution.

## Documentation

- [Installation and model provisioning](docs/operations/installation.md)
- [Operations runbook](docs/operations/runbook.md)
- [Exact-image rollback and restoration](docs/operations/installation.md#exact-image-rollback)
- [Public API contract](api/openapi/public-v1.yaml)
- [Architecture principles](docs/architecture/principles.md)
- [Development methodology](docs/development/methodology.md)
- [Gateway qualification CLI](docs/operations/qualification-cli.md)
- [Milestone plan and evidence](PLANS.md)
- [Initial full-release qualification status](docs/operations/initial-release-qualification.md)

## Project Status

The D01–D04 deployment work is complete: Make + Compose is the supported installation path, and D03 exact-image rollback was rehearsed and documented. D04 retired the legacy deployment infrastructure. Details and limitations are recorded in [PLANS.md](PLANS.md), the [D03 result](docs/milestones/D03/result.md) and [D04 result](docs/milestones/D04/result.md).

M07A is the planned public-Gateway CLI qualification milestone; implementation is awaiting user validation. It does not qualify live service behavior. The current full-product release qualification remains in progress. Repository tags `v0.1.0`–`v0.1.2` are historical; `v0.1.2` identifies legacy VoiceService/model provenance and is not a release of the current full SpeechPlatform stack. No current full-product release is declared.

Implemented functionality does not imply every workload is qualified: concurrent STT/TTS/Ollama GPU use is not guaranteed, cloud inference remains opt-in, and production licensing review for the TTS model and related assets remains open. See milestone records for scope-specific evidence.

## License

No repository-level `LICENSE` file is present. Do not infer a license for the platform code from the licenses of its dependencies or model artifacts.
