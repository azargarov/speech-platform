# Speech Platform

Speech Platform is a self-hosted set of reusable speech services. STT v1 is the first product release: a CUDA faster-whisper worker behind one Gateway API. It supports Russian, English and Swedish transcription, automatic or request-selected spoken language, and request-selected output language. VoxCPM2 TTS supports multilingual plain text, a bounded SSML subset, extra-high-quality synthesis and optional gentle audio processing. Gateway also supports optional local/cloud text transformation and predictive model warmup.

Git releases and the root `compose.yaml` are the normal deployment source of truth. The persistent model store stays on the host and is mounted read-only. Ordinary install and recovery do not use `private/deployment/`, generation state or snapshots. See [ADR 0018](docs/adr/0018-git-compose-product-operations.md).

For the supported full-stack and service-scoped workflow, follow [installation prerequisites and commands](docs/operations/installation.md). `make preflight` reports PASS/WARN/FAIL/SKIP without changing services. Historical VoiceService release descriptors are not current runtime-image manifests.

## Requirements

- Linux x86_64 with Docker Engine and the Docker Compose plugin.
- NVIDIA GPU, compatible driver and NVIDIA Container Toolkit configured for
  Docker. Host `nvidia-smi` is only a host-side check; selected worker installs
  also run a disposable CUDA check inside the worker image.
- Python >=3.12, Go >=1.24.0 and Make for local verification; image/CI compilers are separately pinned.
- The verified `large-v3-turbo` and VoxCPM2 artifacts in a host model store readable by their workers. The default is `/srv/speech-platform/models`; model files are not downloaded at startup.
- A host port available for the Gateway (default 8080).

The model identity is manifest SHA-256 `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`, release `v0.1.2`, model `large-v3-turbo`. Keep existing files in place; this deployment mounts the digest directory read-only.

## Install

Use a supported STT v1 Git release. The `v0.1.2` model release identifies the model artifact; it is not itself a release containing this new Gateway and Compose product path.

```sh
git clone <repository-url> speech-platform
cd speech-platform
git checkout <approved-release-or-source-revision>
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
cp .env.example .env
chmod 600 .env
${EDITOR:-vi} .env
make preflight PYTHON=.venv/bin/python
make install PYTHON=.venv/bin/python
make status
```

Configure these values in `.env` when needed:

- `MODEL_STORE`: absolute path to the existing model store.
- `STT_GPU_DEVICE`: host GPU index; the worker sees the selected device as GPU 0.
- `SPEECH_BIND_IP` and `SPEECH_PORT`: API bind address and port. The default bind is loopback.
- `SPEECH_API_TOKEN`: required for every Gateway deployment, including loopback. Set a random secret of at least 32 characters and keep `.env` private. `.env.example` leaves it empty; Gateway startup fails until it is set.
- `SPEECH_API_URL`: optional HTTPS URL for the TLS reverse proxy used by `make test-stt`; configure it for non-loopback exposure. The Gateway itself serves HTTP, so keep its host port loopback-only unless a firewall permits access only from the TLS proxy.
- `MODEL_READ_GID`: supplementary group allowed to read model artifacts (default 988).

`make preflight` validates configuration and host prerequisites without changing Docker state. `make install` requires a clean committed checkout, retains currently used images by immutable image ID, builds all three images from that revision, verifies source/role labels and CUDA visibility, then starts the fixed `speech-platform` Compose project and waits for health/readiness. It never removes volumes, model data, images, networks or shared Ollama. `make status`, `make logs` and `make stop` are scoped to that project.

Preflight does not invoke sudo. The operator needs read/traverse access through the configured model-reader group to verify artifacts; ask the model-store administrator to arrange that access.

The install builds from the checked-out Git source. Docker base images, CUDA Python dependencies and model artifact identity are pinned. The STT v1 changes have not been published as a new image or Git release; use a supported tag after one is approved and created.

## STT API

`POST /v1/stt/transcriptions` accepts multipart audio with optional `source_language`, `output_language`, `model` and `timestamps` fields. Audio formats are WAV, FLAC, MP3, Ogg/Opus and MP4/M4A. Maximum request size is 25 MiB and the default inference deadline is 180 seconds.

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $SPEECH_API_TOKEN" \
  -F 'audio=@sample.wav;type=audio/wav' \
  -F 'source_language=auto' \
  -F 'output_language=auto' \
  http://127.0.0.1:8080/v1/stt/transcriptions
```

The configured bearer token is required for loopback and external requests:

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

### Optional Groq STT

STT remains local-only by default. Groq Whisper is disabled unless
`groq_stt.enabled` is set in the Gateway configuration and the configured
`api_key_env` is supplied through the private Gateway secrets file. This audio
permission is independent of text transformation's `allow_cloud` setting.
Each request must also carry `X-Allow-Cloud-Audio: true` before Groq can be
eligible. `X-STT-Provider: local` pins local processing; `X-STT-Provider: groq`
pins Groq and requires that consent. With no provider header, an explicitly
consenting request prefers local capacity and may use Groq when local capacity
is occupied. A provider error is returned; the same request is not retried on
another provider. Existing clients that omit these headers remain local-only.

The initial Gateway configuration allows one local and at most two Groq
operations, with a total of two active STT operations across both providers to
bound retained audio buffers. The existing three-request STT waiting queue is
unchanged. This is request-count admission, not a GPU memory reservation.
Groq uses the configured Whisper model and supports only same-language or
automatic transcription through this API; cross-language audio translation is
rejected. Provider provenance is returned in `X-Speech-Provider`.

When authorized requests use Groq, uploaded audio is transmitted to Groq's
transcription endpoint. Groq states that inference customer data is not
retained by default, but inputs/outputs may be temporarily retained for
reliability or abuse investigation for up to 30 days; account data controls
including Zero Data Retention determine applicable handling. Review Groq's
[speech-to-text API](https://console.groq.com/docs/speech-to-text) and
[data-retention policy](https://console.groq.com/docs/your-data) before enabling
cloud audio for sensitive recordings. SpeechPlatform does not log or persist
the uploaded audio.

Use `make test-stt AUDIO=private/audio/sample.wav SOURCE_LANGUAGE=auto OUTPUT_LANGUAGE=auto` to submit a local file through Gateway. The command prints detected/output metadata and transcription to the invoking terminal; audio is not copied into logs by the service.

## Operate and recover

```sh
make status
make logs
curl -fsS http://127.0.0.1:8080/healthz
curl -fsS http://127.0.0.1:8080/readyz
```

`/healthz` confirms Gateway process liveness. Gateway `/readyz` requires both
configured speech workers to report ready. Worker `/healthz` is process
liveness; worker `/readyz` is ability to accept bounded on-demand work. An
unloaded STT or TTS model remains ready and is loaded on the next inference or
warmup. TTS reports not-ready for a known permanent artifact/runtime failure;
after correcting the artifact or configuration, a subsequent warmup or
synthesis can retry loading and clear the condition. Transient resource
shortages do not permanently latch TTS readiness. Readiness checks never load a
model. `make logs` shows recent project logs. Compose restarts crashed services;
configuration and artifact failures need operator repair.

The Gateway has independent bounded FIFO speech admission: STT allows one
active request and three waiting requests; TTS allows one active request and
one waiting request. Queue waiting counts against the request deadline. Waiting
STT uploads are not buffered until admitted. A full queue returns the existing
429 response; deadline exhaustion returns 504. Public STT currently dispatches
to local Faster-Whisper by default. Optional Groq STT requires operator
configuration plus per-request cloud-audio consent as described above. Queue
capacity does not reserve GPU memory.

## TTS API

The public TTS endpoint accepts text and returns a complete WAV PCM16 file. The
default mode is `quality` (10 steps); `auto` currently selects the same mode.
`fast` uses 8 steps, `high_quality` 16, and `extra_high_quality` 32; optional `audio_processing: gentle` applies bounded FFmpeg mastering. `language`
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
make preflight PYTHON=.venv/bin/python
make install PYTHON=.venv/bin/python
```

This rebuilds and applies the selected checkout’s compatible configuration. It does not require snapshot restoration, generation adoption, NAS or an external backup. Updating follows the same path after checking out the new supported release.

## Development and verification

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
```

`make verify` runs lint, strict configuration and Compose checks, release and governance validation, tests, builds and dependency-lock checks. A real GPU test needs local audio and a safe isolated GPU window. Keep audio fixtures under ignored `private/`; never commit private audio or transcripts.

## Status

M06 model lifecycle and predictive warmup are operator-accepted. STT, VoxCPM2
plain-text/SSML TTS and optional local/cloud text transformation are implemented.
Cloud inference remains explicitly opt-in. Initial release installation and CI
qualification is in progress; see [evidence](docs/operations/initial-release-qualification.md).
Historical VoiceService tags v0.1.0–v0.1.2 remain preserved; v0.2.0 is proposed for
the first full SpeechPlatform product release, subject to operator approval.

Text transformation is separately configured and disabled by default. When
enabled, configured local Ollama models remain subject to the existing
`ordered`, `local_first` or `cloud_first` selection policy, explicit model
selection, `local_only` and global `allow_cloud` authorization. Cloud use is
opt-in. A local model being cold or warming does not by itself cause cloud
fallback. Public warmup prepares STT, TTS or the configured local text model;
it sends no user content and never invokes a cloud model.

See [PLANS.md](PLANS.md) and the [public API contract](api/openapi/public-v1.yaml).
