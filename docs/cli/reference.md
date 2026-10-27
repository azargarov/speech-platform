# Command-line reference

This reference covers supported operator, qualification and repository commands. Use the command-specific `--help` output as the final source for flags in the checked-out revision:

```sh
.venv/bin/python -m scripts.qualify --help
.venv/bin/python -m scripts.qualify transform --help
```

`scripts.qualify` exercises the authenticated public Gateway API. Make targets manage repository setup, validation, model artifacts, images and the SpeechPlatform Compose project. They are separate interfaces: qualification does not install services, and verification does not perform live inference.

## Getting started

From a clean checkout, create the environment, initialize protected operator configuration, then follow the installation guide:

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make init
make preflight PYTHON=.venv/bin/python
make install PYTHON=.venv/bin/python
make status PYTHON=.venv/bin/python
```

Review `.env` and provision the required pinned artifacts before preflight. The full-stack install is the default. Component selection and prerequisites are described in [installation and recovery](../operations/installation.md).

## Speech-to-text

Use `scripts.qualify stt` for one public Gateway transcription:

```sh
.venv/bin/python -m scripts.qualify stt \
  --audio private/audio/sample.wav \
  --source-language auto --output-language auto
```

`--audio` is required. Optional operation flags are `--source-language auto|ru|en|sv`, `--output-language auto|ru|en|sv`, `--provider local|groq`, and `--model ALIAS` (local provider only). Groq requires both `--provider groq` and explicit `--allow-cloud-audio`; Groq uses its configured server model, so `--model` is rejected with Groq. Timestamp and streaming switches exist for expected-error probes but are unsupported by the Gateway.

The request returns a transcription to the CLI. Use `--report` for structured metadata and `--evidence` only when retaining the transcript is required. For a fixture-by-fixture TTS-to-STT measurement, see [round-trip qualification](../operations/roundtrip-qualification.md).

## Text transformation and translation

Use `scripts.qualify transform` with inline text, a UTF-8 file, or standard input:

```sh
.venv/bin/python -m scripts.qualify transform \
  --text-file samples/text/ru-rude.txt \
  --mode diplomatic --format normal --target-language none \
  --model local-qwen

.venv/bin/python -m scripts.qualify transform \
  --text 'Hej, vi ses imorgon.' \
  --mode written --target-language en --model local-qwen
```

Input flags `--text` and `--text-file` are mutually exclusive; if neither is supplied, text is read from stdin. Supported modes are `raw`, `written`, `polite`, and `diplomatic`; formats are `normal`, `concise`, and `structured`; target languages are `none`, `en`, `sv`, and `ru`. Raw mode only permits Normal format. Translation uses the same transformation request.

`--model ALIAS` selects a configured Gateway alias. Omitting it lets Gateway apply its ordered model policy. An explicit alias never falls back; with no explicit alias, an eligible later configured model can be tried after an earlier provider failure. `--allow-cloud` makes configured cloud models eligible for this CLI request but cannot override Gateway policy or supply missing credentials. The CLI defaults to local-only. The public API has a different default for `local_only`; direct API clients should set `local_only: true` whenever they require local-only routing.

An experimental system prompt can be supplied for one request:

```sh
.venv/bin/python -m scripts.qualify transform \
  --text 'Synthetic text.' --mode written --model local-qwen \
  --prompt-file /path/to/operator-prompt.txt
```

The file must be nonempty UTF-8 and at most 64 KiB. It replaces the configured prompt for that request; it is not included in normal reports or logs. Treat it as trusted operator-controlled input.

Raw transformation with no target language is exact pass-through and does not call a model. Successful generated text is printed to stdout; terminal output may be sensitive. HTTP success establishes technical operation only, not semantic preservation or translation quality. M07 findings and limitations are in the [qualification procedure](../operations/qualification-cli.md) and [M07B2 evidence](../milestones/M07B2/verification.md).

## Text-to-speech

Use `scripts.qualify tts` to synthesize one WAV through the Gateway:

```sh
.venv/bin/python -m scripts.qualify tts \
  --text 'Synthetic speech.' --language en --mode quality \
  --input-format text --output private/audio/qualified.wav
```

Provide `--text` or `--text-file`. Supported optional flags include `--voice default`, `--language auto|en|ru|sv`, `--mode quality|fast|auto|high_quality|extra_high_quality`, `--input-format text|ssml`, and `--audio-processing none|gentle`. The public API does not select a TTS model/provider and only the configured default voice is exposed. Output uses exclusive creation and mode `0600`; missing parent directories are created with restrictive permissions. No file is overwritten.

## Health, readiness and diagnostics

The qualification CLI provides unauthenticated Gateway probes and a protected voice catalog request:

```sh
.venv/bin/python -m scripts.qualify health
.venv/bin/python -m scripts.qualify ready
.venv/bin/python -m scripts.qualify metrics
.venv/bin/python -m scripts.qualify voices
```

`health` checks Gateway process liveness; `ready` checks configured required worker dependencies; `metrics` summarizes the Gateway Prometheus endpoint; `voices` validates the public TTS voice catalog. Gateway `/healthz`, `/readyz`, and `/metrics` are unauthenticated; the voices route requires the configured bearer token.

For operational diagnostics, use scoped Make commands:

```sh
make status SERVICE=gateway PYTHON=.venv/bin/python
make logs SERVICE=gateway PYTHON=.venv/bin/python
```

`status` and `logs` may omit `SERVICE` to inspect all SpeechPlatform services. Log retrieval is bounded by the project tooling. Logs do not provide a substitute for structured qualification reports.

## Model lifecycle and warmup

Gateway warmup is explicit and authenticated. It changes model residency but does not accept user content:

```sh
.venv/bin/python -m scripts.qualify warmup \
  --operation stt --operation text_transform
```

Repeat `--operation` with `stt`, `tts`, or `text_transform`; one or more are required. A ready result confirms the warmup completed, not that a model will remain resident. Warmup can consume GPU and must not be treated as a read-only health check.

The Make-only TTS lifecycle helpers operate inside the existing TTS container:

```sh
make tts-warmup
make tts-state
```

`tts-warmup` loads the TTS model. `tts-state` reports the worker's internal loaded/unloaded state. These commands require a running TTS service; use the operational procedures for resource and recovery guidance.

## Configuration validation and model artifacts

Use `make config` to validate the canonical Gateway, STT and TTS configurations. `make preflight` is a read-only deployment prerequisite check; it can inspect Docker ownership/health, configured worker dependencies, networks, model metadata and host resources, and performs no deployment.

```sh
make config PYTHON=.venv/bin/python
make preflight COMPONENTS=gateway PYTHON=.venv/bin/python
make release-check PYTHON=.venv/bin/python
make model-check PYTHON=.venv/bin/python
make tts-model-check PYTHON=.venv/bin/python
```

`make model-fetch` and `make tts-model-fetch` explicitly download pinned artifacts into their configured stores; they require network access and may require store-owner privileges. Check paths, ownership and licensing before fetching. Lock validation is available with `make stt-lock-check` and `make tts-lock-check`. `make release-check` validates the configured release descriptor; it does not install it.

The Go Gateway executable is primarily a service entry point. Its supported offline configuration check is:

```sh
SPEECH_API_TOKEN=offline-config-validation-token-0123456789 \
  go run ./cmd/gateway --config configs/gateway.yaml --check-config
```

The service flags are `--config PATH` (required), `--check-config`, and
`--check-ollama`. The latter is a read-only DNS, TCP and `/api/version` probe
for configured Ollama; it does not run inference. `make config` uses a dummy
token for offline validation. The `healthcheck` Go binary and
`scripts/compose.py` / `scripts/deploy_images.py` are Compose/installer helpers,
not general operator CLIs; prefer the Make interface.

## Installation and component-scoped deployment

Installation always includes Gateway. `COMPONENTS` accepts a comma-separated selection from `gateway`, `stt`, and `tts`; the default is all three. Selection controls which services are updated, independently of Gateway capability flags.

```sh
make preflight COMPONENTS=gateway PYTHON=.venv/bin/python
make install COMPONENTS=gateway PYTHON=.venv/bin/python
make install COMPONENTS=gateway,stt PYTHON=.venv/bin/python
make install COMPONENTS=gateway,tts PYTHON=.venv/bin/python
make install COMPONENTS=gateway,stt,tts PYTHON=.venv/bin/python
```

Preflight requires enabled, unselected workers to already be owned, compatible, running and healthy. Installation builds and recreates selected services and is a mutating Docker operation. It requires a clean committed worktree and passing scoped preflight. Do not use it as a smoke test. See [installation, exact-image rollback and recovery](../operations/installation.md).

Other operational Make commands:

| Command | Purpose and caution |
| --- | --- |
| `make init` | Create `.env` and private directories only when absent. |
| `make status [SERVICE=...]` | Inspect the project and image/container identity. |
| `make logs [SERVICE=...]` | Read bounded project logs; handle operational output as sensitive. |
| `make stop [SERVICE=...]` | Stop selected SpeechPlatform service(s); does not remove images, volumes or networks. |

## Qualification reports and evidence

The `scripts.qualify` commands share these options where applicable:

| Option | Purpose |
| --- | --- |
| `--gateway-url URL` | Select Gateway origin. Non-loopback targets require HTTPS. |
| `--api-token-file PATH` | Use a private token file under `private/` with mode `0600` or stricter. |
| `--auth-mode configured\|none\|missing` | Use configured bearer auth, send no auth header, or send a missing header for a read-only expected-401 probe. |
| `--timeout SECONDS` | Bound the CLI's wait; this is not the server's processing deadline. |
| `--report PATH` | Write structured JSON using exclusive creation and mode `0600`. |
| `--evidence PATH` | Explicitly retain request/response content where supported; protect it. |
| `--expect-error CODE` | Pass only when the Gateway returns the expected API error with an error status. |
| `--verbose` / `--debug` | Print safe progress; debug may collect bounded local Compose logs for loopback targets. |

`private/` is recommended for sensitive reports and evidence. Explicit report/evidence paths may be relative or absolute outside `private/`; parent directories are created, existing files are never overwritten, and the CLI does not update `.gitignore`. Outputs outside `private/` may be committed if added to Git. Ordinary reports omit transformation text; `--evidence` can retain text/transcripts. TTS `--output` writes audio. The debug log artifact is always written under `private/`. See [qualification procedures and report interpretation](../operations/qualification-cli.md).

Specialized tools:

| Entry point | Behavior and data handling |
| --- | --- |
| `python -m scripts.transform_samples` | No required options; runs all fixtures by default. `--case ID` selects one; `--regenerate` replaces only expected outputs after successful writes. Optional `--timeout`, `--gateway-url`, `--api-token-file`, `--verbose`, and `--debug` control request/diagnostic behavior. Always uses local STT and local-only text routing. Writes generated text under Git-ignored `samples/transformed/`. See [batch qualification](../operations/batch-text-qualification.md). |
| `python -m scripts.roundtrip` | No required CLI flags; runs all text fixtures by default. Optional `--language en|ru|sv`, `--case ID`, `--output-dir DIR`, `--report PATH`, `--regenerate`, `--tts-mode`, `--timeout`, `--gateway-url`, `--api-token-file`, `--verbose`, and `--debug`. The selected output directory must exist. Always uses local TTS/STT. Reports include reference text and returned transcription; protect reports/audio. See [round-trip qualification](../operations/roundtrip-qualification.md). |
| `./test-transformation.sh [--allow-cloud]` | No required options. Runs the nine-fixture Written/Polite/Diplomatic matrix: 27 local requests, or 81 total including 54 cloud requests with explicit `--allow-cloud`. Writes reports and text evidence under `samples/out/` and prints fixture/generated text. Use only with approved inputs and cloud authorization. |

The legacy API smoke commands have narrower options: `python -m scripts.api_smoke stt --audio PATH [--source-language auto|ru|en|sv] [--output-language auto|ru|en|sv]`; `python -m scripts.api_smoke tts --output PATH [--text TEXT]`. They are exposed through `make test-stt AUDIO=...` and `make test-tts OUTPUT=...` and issue live local Gateway requests without the richer qualification reports.

`make test-roundtrip` also performs live inference over all fixtures. These live smoke targets are not part of `make verify`.

## Developer, image and release commands

| Target | Purpose |
| --- | --- |
| `make bootstrap PYTHON=...` | Install development, CPU STT and Go dependencies. |
| `make fmt` / `make lint` | Format source (mutates files) / run Go vet and Ruff checks. |
| `make test` | Run Go race tests and Python script/STT/TTS test suites; no live Gateway requests. |
| `make build` / `make verify` | Build Go and parse Python / run the full offline validation target. |
| `make compose-check` / `make config` | Render and validate Compose / validate Gateway and worker configs. |
| `make governance-check` | Validate skill governance structure and references. |
| `make image [SERVICE=gateway\|stt\|tts] [VARIANT=cpu\|cuda]` | Build local service images; does not publish. Default image target builds Gateway, STT and TTS using CPU STT. |
| `make publish VERSION=vX.Y.Z [SERVICE=...] [VARIANT=cpu\|cuda]` | Validate and publish selected images to the configured registry. This pushes artifacts and is separate from installation. Choose the STT variant intentionally. |

The specialized `stt-cpu-integration` and `stt-cuda-http-integration` targets require explicit experiment inputs, pinned identities and resource settings. The CPU target requires `STT_APPLICATION_CONFIG`, `STT_DEPLOYMENT_CONFIG`, and `STT_SMOKE_AUDIO`; it runs a real local CPU inference test. The CUDA target has a larger required environment described in the [CUDA HTTP integration procedure](../operations/stt-cuda-http-integration.md). Neither is routine verification; do not infer live qualification from static checks.

The Make wrappers `test-stt`, `test-tts`, and `test-roundtrip` perform live local Gateway operations rather than offline tests:

```sh
make test-stt AUDIO=private/audio/sample.wav PYTHON=.venv/bin/python
make test-tts OUTPUT=private/audio/tts-smoke.wav PYTHON=.venv/bin/python
make test-roundtrip PYTHON=.venv/bin/python
```

`test-roundtrip` runs every discovered fixture; use `scripts.roundtrip --case ...` when a single case is needed. Run these only against a healthy local Gateway with approved inputs and an appropriate GPU window.

## Troubleshooting

- Check CLI flags in `.venv/bin/python -m scripts.qualify <operation> --help`.
- Distinguish Gateway liveness (`health`) from dependency readiness (`ready`). A disabled capability and an unavailable configured provider are different outcomes.
- Use `--expect-error CODE` only for an expected rejection; inspect the recorded actual status and code.
- Use `make preflight COMPONENTS=...` before installation. Do not bypass failed ownership, model-integrity, health or image checks.
- Use scoped `make status`, `make logs`, and the [runbook](../operations/runbook.md) for operational failures. Do not run broad Docker `down`, prune, or restart commands as troubleshooting.
- HTTP 200, a completed round trip, WER/CER or formatting checks do not establish semantic or linguistic quality. Review generated text and audio separately.
