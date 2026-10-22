# Speech Platform

Speech Platform is a self-hosted set of reusable speech services. STT v1 is the first product release: a CUDA faster-whisper worker behind one Gateway API. It supports Russian, English and Swedish transcription, automatic or request-selected spoken language, and request-selected output language. M03B adds a VoxCPM2 TTS candidate through the existing Gateway and worker; production acceptance remains pending. Voice dictation and text transformation are future work.

Git releases and the root `compose.yaml` are the normal deployment source of truth. The persistent model store stays on the host and is mounted read-only. Ordinary install and recovery do not use `private/deployment/`, generation state or snapshots. See [ADR 0018](docs/adr/0018-git-compose-product-operations.md).

## Requirements

- Linux x86_64 with Docker Engine and the Docker Compose plugin.
- NVIDIA GPU, driver and NVIDIA Container Toolkit configured for Docker.
- Python 3.13.9, Go 1.27.2 and Make for local verification and image builds.
- The verified `large-v3-turbo` model release in a host model store readable by the STT worker. The default is `/srv/speech-platform/models`; model files are not downloaded at startup.
- A host port available for the Gateway (default 8080).

The model identity is manifest SHA-256 `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`, release `v0.1.2`, model `large-v3-turbo`. Keep existing files in place; this deployment mounts the digest directory read-only.

## Install

Use a supported STT v1 Git release. The `v0.1.2` model release identifies the model artifact; it is not itself a release containing this new Gateway and Compose product path.

```sh
git clone <repository-url> speech-platform
cd speech-platform
git checkout <supported-stt-v1-release>
cp .env.example .env
chmod 600 .env
${EDITOR:-vi} .env
make plan
make install
make status
```

Configure these values in `.env` when needed:

- `MODEL_STORE`: absolute path to the existing model store.
- `STT_GPU_DEVICE`: host GPU index; the worker sees the selected device as GPU 0.
- `SPEECH_BIND_IP` and `SPEECH_PORT`: API bind address and port. The default bind is loopback.
- `SPEECH_API_TOKEN`: required when the host API bind is not loopback. Use a random secret of at least 32 characters. Keep `.env` private.
- `SPEECH_API_URL`: optional HTTPS URL for the TLS reverse proxy used by `make test-stt`; configure it for non-loopback exposure. The Gateway itself serves HTTP, so keep its host port loopback-only unless a firewall permits access only from the TLS proxy.
- `MODEL_READ_GID`: supplementary group allowed to read model artifacts (default 988).

`make plan` validates Docker/Compose, NVIDIA GPU selection, the pinned release and model artifact, API exposure settings and rendered Compose configuration. It does not start or change containers. `make install` requires a clean Git checkout, builds the pinned-source images, starts the canonical Compose project, waits for readiness and prints the API endpoint. Re-running it is safe. It acts only on the configured Compose project name (`speech-platform` by default).

If the model-store parent is root-owned, run `sudo -v` before `make plan`; the command uses cached sudo authorization for the read-only artifact check. It does not make Compose run as root. Add the operator to the Docker access group using the host’s normal administration process.

The install builds from the checked-out Git source. Docker base images, CUDA Python dependencies and model artifact identity are pinned. The STT v1 changes have not been published as a new image or Git release; use a supported tag after one is approved and created.

## STT API

`POST /v1/stt/transcriptions` accepts multipart audio with optional `source_language`, `output_language`, `model` and `timestamps` fields. Audio formats are WAV, FLAC, MP3, Ogg/Opus and MP4/M4A. Maximum request size is 25 MiB and the default inference deadline is 180 seconds.

```sh
curl --fail-with-body \
  -F 'audio=@sample.wav;type=audio/wav' \
  -F 'source_language=auto' \
  -F 'output_language=auto' \
  http://127.0.0.1:8080/v1/stt/transcriptions
```

For non-loopback exposure, include the configured bearer token:

```sh
curl --fail-with-body -H "Authorization: Bearer $SPEECH_API_TOKEN" \
  -F 'audio=@sample.wav;type=audio/wav' \
  -F 'source_language=ru' -F 'output_language=en' \
  https://<host>/v1/stt/transcriptions
```

`source_language` is `auto`, `ru`, `en` or `sv`; `output_language` has the same values. Both default to `auto`. A legacy `language` field remains as a source-language alias. If both source fields are supplied, they must agree. Detected unsupported languages return `unsupported_detected_language`; the service never silently substitutes a language.

The response retains `text` and `language` for compatibility and adds explicit fields:

```json
{
  "detected_language": "ru",
  "source_language": "ru",
  "output_language": "ru",
  "transcription": "Доброе утро.",
  "text": "Доброе утро.",
  "translated": false,
  "language_probability": 0.98
}
```

`transcription` is always the original-language transcript. `text` is the requested output. When source and output match, `text` equals `transcription` and `translated` is false. With `output_language=auto`, output remains in the detected source language. Translation is model-configured. The deployed `large-v3-turbo` configuration disables translation because it does not reliably support the English translation task; Russian-to-English and Swedish-to-English requests return `unsupported_translation`. Same-language and automatic transcription remain available. Other STT models may enable translation only when their configuration declares and their deployment supports that capability. `language_probability` appears only when automatic detection supplies it; forced source selection does not invent confidence.

| Spoken language | `auto` | `ru` | `en` | `sv` |
| --- | --- | --- | --- | --- |
| Russian | Russian transcript | Russian transcript | `unsupported_translation` on large-v3-turbo | `unsupported_translation` |
| English | English transcript | Explicitly unsupported | English transcript | Explicitly unsupported |
| Swedish | Swedish transcript | Explicitly unsupported | `unsupported_translation` on large-v3-turbo | Swedish transcript |

Automatic detection of a language outside Russian, English and Swedish returns `unsupported_detected_language` (422).

Use `make test-stt AUDIO=private/audio/sample.wav SOURCE_LANGUAGE=auto OUTPUT_LANGUAGE=auto` to submit a local file through Gateway. The command prints detected/output metadata and transcription to the invoking terminal; audio is not copied into logs by the service.

## Operate and recover

```sh
make status
make logs
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

`healthz` confirms Gateway process liveness. `readyz` confirms the configured STT and TTS workers are available; the TTS model may be unloaded because it loads on demand. `make logs` follows the configured project logs. Docker Compose restarts crashed services. If configuration or model files are unavailable, inspect the logs and restore the expected configuration or artifact permissions.

## TTS candidate API

The M03B candidate accepts text and returns a complete WAV PCM16 file. The
default mode is `quality` (10 steps); `auto` currently selects the same mode.
`fast` (8 steps) remains unavailable until its quality is accepted. `language`
defaults to `auto`, which passes multilingual text without language metadata;
`en`, `ru` and `sv` are client hints and do not produce a detected-language
code. The request body is limited to 64 KiB and 10,000 text characters.

```sh
curl --fail-with-body -H 'Content-Type: application/json' \
  --data '{"text":"Hello, мир!","language":"auto","mode":"quality"}' \
  http://127.0.0.1:8080/v1/tts/speech --output speech.wav
```

See [TTS operations](docs/operations/tts.md) for model staging, warm-up,
loaded state and resource controls. Model fetching is explicit; runtime
downloads are disabled.

Redeploy a known-good release with:

```sh
git checkout <known-good-release>
make plan
make install
```

This rebuilds and applies the selected checkout’s compatible configuration. It does not require snapshot restoration, generation adoption, NAS or an external backup. Updating follows the same path after checking out the new supported release.

## Development and verification

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
```

`make verify` runs lint, strict configuration and Compose checks, release and governance validation, tests, builds and dependency-lock checks. A real GPU test needs local audio and a safe isolated GPU window. Keep audio fixtures under ignored `private/`; never commit private audio or transcripts.

## Roadmap

- **STT v1:** Russian, English and Swedish transcription with automatic and forced source selection. Translation is advertised only for models whose configuration enables a verified translation capability; the deployed large-v3-turbo model has translation disabled.
- **TTS:** M03A selected VoxCPM2 for initial M03B integration after operator listening; M03B implementation and live acceptance are in progress. This selection is not production acceptance.
- **Voice dictation and text transformation:** future separate optional service after STT v1. It will preserve raw transcription and offer per-request `raw`, `clean`, `business`, `friendly`, `casual` and `formal_to_casual` modes through a configurable local LLM. It will not put an LLM in the STT worker and should continue to allow ordinary STT when the transformation service is unavailable. Desktop shortcuts and insertion must account for Linux Wayland restrictions; mobile mode selection can follow.
- **Transcript Refinement:** optional future text-processing capability; it will remain separate from raw STT.

See [PLANS.md](PLANS.md), [public API contract](api/openapi/public-v1.yaml), and [architecture decisions](docs/adr/).
