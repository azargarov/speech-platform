# Gateway qualification CLI

Run a single request from the repository root with `.env` configured with the Gateway URL and API token:

```sh
.venv/bin/python -m scripts.qualify stt --audio private/audio/sample.wav
printf '%s' 'Synthetic text for rewriting.' | .venv/bin/python -m scripts.qualify transform --mode written --format normal
.venv/bin/python -m scripts.qualify transform --text 'Hej.' --target-language en --mode written
.venv/bin/python -m scripts.qualify tts --text 'Synthetic speech.' --output private/audio/qualified.wav
```

STT defaults to the local provider. Groq audio requires both `--provider groq` and explicit `--allow-cloud-audio`. Text transformation defaults to `local_only=true`; `--allow-cloud` explicitly permits configured cloud routing but cannot override Gateway policy. Translation is text transformation with `--target-language`. Raw mode requires normal formatting. Use `--text-file` or stdin to avoid placing sensitive input in shell history. `--timeout` is a client wait bound, not a server processing duration.

### Text model selection

When `--model` is omitted, the CLI omits the `model` property from the request
and lets Gateway apply its configured selection policy. An explicit alias is
sent unchanged, for example:

```sh
.venv/bin/python -m scripts.qualify transform --text 'Synthetic text.' --model local-qwen
.venv/bin/python -m scripts.qualify transform --text 'Synthetic text.' --model groq-qwen --allow-cloud
```

Read-only inspection of the effective Gateway configuration on 2026-10-25
found ordered selection with `allow_cloud=false` and these enabled aliases:

| Alias | Configured provider locality | Current cloud policy |
| --- | --- | --- |
| `local-qwen` | Local | Eligible under current policy |
| `groq-qwen` | Cloud | Denied while `allow_cloud=false` |
| `groq-gpt-oss` | Cloud | Denied while `allow_cloud=false` |

The tracked [`gateway-text.example.yaml`](../../configs/gateway-text.example.yaml)
contains the same aliases. `--allow-cloud` sets `local_only=false`; the Gateway
still enforces its own cloud policy, model availability and alias validity.
Without the flag, an explicit cloud alias is sent with `local_only=true` and
the Gateway rejects it. Unknown or disabled aliases are likewise left for the
Gateway to reject. Batch qualification has no `--model` option: it omits the
field and reports the actual model returned by the Gateway.

The OpenAPI request schema currently marks `model` nullable, but Gateway
validation rejects JSON `null` for option fields. The CLI avoids this mismatch
by omitting an unset field. The smallest contract correction is to keep the
request property optional but make it a non-nullable string; response model
fields may remain nullable where the response contract requires it.

Each invocation prints a short content-free result. Failures include a safe explanation; when no request was sent, the summary shows `HTTP N/A` and `elapsed=N/A`. `--report private/reports/run.json` writes an optional JSON report using exclusive creation and mode 0600. The stable top-level fields are `schema_version`, `operation`, `request`, `http`, `elapsed_seconds`, `error`, `response`, `outcome`, `technical_checks`, and `artifact`. `request.input` contains sizes only; response text is not included. `--evidence private/reports/evidence.json` explicitly stores request/response text for STT and text operations; protect and delete it when no longer needed.

TTS WAV is inspected in memory and discarded unless `--output` is given. WAV output may use any relative or absolute filesystem path, including `~/...`; the parent directory must already exist and be writable. The CLI does not create directories or overwrite files. It uses exclusive creation with mode `0600` and removes a partial file if writing fails when cleanup is possible. A permission failure discovered at file creation happens after the Gateway request, so synthesis may complete without a saved WAV. Choose a destination appropriate for generated audio and its sensitivity. `--report` and `--evidence` remain restricted to an existing path under `private/`.

All requested output destinations are canonicalized and checked for collisions before an API request. Output creation or writing failures return exit code 3. If a WAV or evidence artifact was successfully written before a later evidence/report write fails, the CLI does not remove that completed artifact; inspect and remove it manually if needed. A partial file from a failed write is removed when possible; if cleanup itself fails, the error states that a partial file may remain.

The CLI checks protocol success and deterministic response properties. It does not score semantic preservation or linguistic quality. Live qualification requires separate authorization and must not be inferred from offline tests.

For text transformation, JSON report metadata records the optional
`X-Speech-Prompt-SHA256` response header when returned. This identifies the
active prompt snapshot used by the Gateway without adding prompt contents to
the report.

For sequential local TTS-to-STT fixture measurements, see the [round-trip qualification guide](roundtrip-qualification.md).
