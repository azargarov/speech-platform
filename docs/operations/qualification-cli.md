# Gateway qualification CLI

The full route/field/provider/limitation matrix is in the
[qualification capability matrix](qualification-capabilities.md).

Run a single request from the repository root with `.env` configured with the Gateway URL and API token:

```sh
.venv/bin/python -m scripts.qualify stt --audio private/audio/sample.wav
printf '%s' 'Synthetic text for rewriting.' | .venv/bin/python -m scripts.qualify transform --mode written --format normal
.venv/bin/python -m scripts.qualify transform --text 'Hej.' --target-language en --mode written
.venv/bin/python -m scripts.qualify tts --text 'Synthetic speech.' --output private/audio/qualified.wav
```

The CLI also checks public catalogs, Gateway health/readiness/metrics, and
explicit model warmup:

```sh
.venv/bin/python -m scripts.qualify health
.venv/bin/python -m scripts.qualify ready --gateway-url https://speech.example.net
.venv/bin/python -m scripts.qualify voices --report private/qualification/voices.json
.venv/bin/python -m scripts.qualify metrics
.venv/bin/python -m scripts.qualify warmup --operation stt --operation text_transform
```

Warmup changes model residency and is opt-in; ordinary verification does not
invoke it. There is no public STT model catalog; the stale OpenAPI route was
removed because the Gateway intentionally returns 404 and its handler test
expects that behavior. Supply a configured model alias directly to `--model`
where the request contract supports selection. `metrics` summarizes metric
names/count because the operational route is outside the versioned OpenAPI
contract.

By default the CLI reads `.env`. `--gateway-url` selects an origin; non-loopback
targets require HTTPS. `--api-token-file private/gateway-token` can override
the configured token with a private file mode 0600 or stricter. Secrets are
never printed. `--auth-mode none` explicitly targets an intentionally
unauthenticated instance. A missing-header expected-401 probe is limited to
the read-only voice catalog so an open Gateway cannot accidentally receive an
inference request:

```sh
.venv/bin/python -m scripts.qualify voices --auth-mode missing --expect-error unauthorized
```

A deliberately invalid token can be tested with an operator-provided invalid
private token file in configured auth mode; the CLI never fabricates one.
OpenAPI declares bearer authentication for all versioned routes, while Gateway
configuration requires a token of at least 32 characters before the Gateway
can start. The route helpers skip their check only when constructed internally
with an empty token, which is not a valid production configuration. The CLI
does not silently omit credentials. See the
[coverage matrix](qualification-capabilities.md) for the configuration and
runtime evidence.
`--verbose` displays safe request progress and `--debug` additionally prints
allowlisted response headers, both on stderr. Debug mode also reads logs from
the repository-owned local Compose project for loopback Gateway targets. It
collects at most 100 lines and 32 KiB per Gateway/STT/TTS service from a
30-second to five-minute look-back window. Credential values and structured payload/message
fields are redacted. Logs are written to a unique mode-0600
`private/qualification-debug-*.json` file; the CLI prints only its path. If a
Gateway-generated `X-Request-ID` was returned and appears in logs, exact matching
lines are kept across Gateway, STT and TTS records;
otherwise the evidence is explicitly labeled as time-window-only. Each service
is reported as `matched`, `no_matching_lines`, or `failed`; aggregate collection
uses `matched`, `no_matching_lines`, `partial`, or `failed`, while a non-loopback
target is `unavailable`. The collector's bounded `--since` window can therefore
be empty even when an unfiltered manual log tail contains older entries.
Remote targets skip local Docker log collection. Ordinary requests do not
access Docker.

STT defaults to the local provider. Groq audio requires both `--provider groq` and explicit `--allow-cloud-audio`. Text transformation defaults to `local_only=true`; `--allow-cloud` explicitly permits configured cloud routing but cannot override Gateway policy. Translation is text transformation with `--target-language`. Raw mode requires normal formatting. Use `--text-file` or stdin to avoid placing sensitive input in shell history. `--timeout` is a client wait bound, not a server processing duration.

On a successful single `transform` request, the CLI prints the complete
`transformed_text` to stdout before its qualification summary. Treat terminal
output and any captured stdout as sensitive transformation output. `--report`
and `--evidence` retain their existing structured formats; ordinary Gateway
logs do not include generated text. Provider failure logs include the upstream
HTTP status and only bounded, sanitized error code/type tokens when supplied;
provider response bodies and raw error messages are not logged.

STT accepts the optional `--model` alias for local-provider selection. Groq STT
uses the configured server model and rejects explicit model values, so the CLI
rejects `--provider groq --model ...` before sending a request.

Use `--expect-error CODE` to qualify an expected public API rejection, for example
`--model groq-qwen --expect-error cloud_not_allowed`. The command exits zero
only when the Gateway returns that API code with an HTTP error status; the JSON
report retains the actual HTTP status and error classification and records
whether the expectation matched. If the request succeeds or a different error
is returned, the command fails. This option does not bypass request validation
or authentication.

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

CLI language, transformation mode/format, TTS mode/language, and audio
input-format/processing choices are checked against the corresponding public
OpenAPI enums by offline tests. Model aliases remain Gateway configuration, not
CLI choices.

### Cloud provider setup

The Gateway only receives cloud credentials from the private environment file
selected by `GATEWAY_SECRETS_FILE` (default `private/cloud.env`). Text models
use their configured `api_key_env`; Groq STT separately uses `GROQ_STT_API_KEY`
when `groq_stt.enabled` is true. The credential file must be under `private/`,
mode `0600`, and contain only the key names required by enabled cloud features.
`make preflight PYTHON=.venv/bin/python` validates credentials when present,
reports missing or invalid optional credentials as a warning, and never prints
values. Gateway startup also warns when enabled cloud credentials are
unavailable. Local routes and readiness remain usable.

Text-cloud routing also requires `text_transform.selection.allow_cloud: true`.
This is a Gateway startup setting; prompt SIGHUP reload does not change it.
Even with that setting enabled, ordinary qualification remains local-only.
Select a cloud alias explicitly and pass `--allow-cloud` for text, or select
`--provider groq --allow-cloud-audio` for STT. Both controls are per request.
To diagnose one capability, run its existing single-request command with an
operator-approved synthetic or otherwise authorized input. For example, with
an existing operator-authorized audio file,
`python -m scripts.qualify stt --audio private/authorized-sample.wav --provider groq --allow-cloud-audio --expect-error provider_unavailable`
checks that Groq STT is unavailable without accepting a different provider;
omit `--expect-error` only for an authorized inference qualification. For text,
select a cloud model with `--allow-cloud`; `cloud_not_allowed` identifies
Gateway policy denial, while `provider_unavailable` identifies a selected
provider lacking usable credentials. A successful response records provider
provenance. A remote Gateway does not disclose whether an unavailable provider
is disabled or enabled without credentials; inspect its local config and safe
startup warning to distinguish those states.
The default model selection policy should remain local-first/local-only unless
an operator intentionally changes it. Groq TTS is not provided. The current
batch STT/text tool and TTS → STT round-trip tool remain local-only. The
single-request TTS command accepts `--input-format text|ssml`; SSML must satisfy
the Gateway's supported subset and configured limits.

After enabling a Gateway startup policy, use the repository deployment path.
There is no supported Gateway-only deployment target: `make install` builds
and updates Gateway, STT and TTS together. Review its impact and recovery
prerequisites before running it on a shared host.

### Provider comparison

For the accepted synthetic `en-rude` transcript, run individual requests
sequentially so every report is tied to one explicit model, mode and target
language. Use distinct private report/evidence paths for every invocation:

```sh
install -d -m 0700 private/m07b2
.venv/bin/python -m scripts.qualify transform \
  --text-file samples/transformed/en-rude/raw.txt \
  --model groq-qwen --allow-cloud --mode written --format normal \
  --target-language none --report private/m07b2/groq-qwen-written-en.json \
  --evidence private/m07b2/groq-qwen-written-en-evidence.json
```

Repeat for `groq-gpt-oss`, modes `written`, `polite`, `diplomatic`, and target
languages `none`, `ru`, `sv`. Use `local-qwen` without `--allow-cloud` as the
local baseline. Reports record the returned provider/model and prompt SHA-256;
evidence contains generated text and must remain private. HTTP success is
technical evidence only and does not establish semantic preservation.

The OpenAPI request schema currently marks `model` nullable, but Gateway
validation rejects JSON `null` for option fields. The CLI avoids this mismatch
by omitting an unset field. The smallest contract correction is to keep the
request property optional but make it a non-nullable string; response model
fields may remain nullable where the response contract requires it.

Each invocation prints a short content-free result. Failures include a safe explanation; when no request was sent, the summary shows `HTTP N/A` and `elapsed=N/A`. `--report private/reports/run.json` writes an optional JSON report using exclusive creation and mode 0600. Top-level fields include `schema_version`, `operation`, `request`, `http`, `elapsed_seconds`, `error`, `diagnostics`, `response`, `outcome`, `technical_checks`, and `artifact`. Diagnostics distinguish a local client operation ID from a real server request ID, which is recorded only when a whitelisted header is returned. Gateway logs are marked unavailable through the public API. `request.input` contains sizes only; response text is not included. `--evidence private/reports/evidence.json` explicitly stores request/response text for STT and text operations; protect and delete it when no longer needed.

When `--expect-error` is provided, the report adds an `expected_api_error`
object with the expected code and match result. Reports otherwise retain their
existing shape. TTS responses currently do not expose a public model/provider
identity by contract; the CLI records WAV metadata/content type and records a
provider or model header only if an actual response includes one.

TTS WAV is inspected in memory and discarded unless `--output` is given. WAV output may use any relative or absolute filesystem path, including `~/...`; the parent directory must already exist and be writable. The CLI does not create directories or overwrite files. It uses exclusive creation with mode `0600` and removes a partial file if writing fails when cleanup is possible. A permission failure discovered at file creation happens after the Gateway request, so synthesis may complete without a saved WAV. Choose a destination appropriate for generated audio and its sensitivity. `--report` and `--evidence` remain restricted to an existing path under `private/`.

All requested output destinations are canonicalized and checked for collisions before an API request. Output creation or writing failures return exit code 3. If a WAV or evidence artifact was successfully written before a later evidence/report write fails, the CLI does not remove that completed artifact; inspect and remove it manually if needed. A partial file from a failed write is removed when possible; if cleanup itself fails, the error states that a partial file may remain.

The CLI checks protocol success and deterministic response properties. It does not score semantic preservation or linguistic quality. Live qualification requires separate authorization and must not be inferred from offline tests.

Each report includes `capability_state`: `available` after a valid successful
operation; `disabled` after `capability_disabled`, the legacy disabled-text
code, or a policy rejection; `configured_but_unavailable` after
`provider_unavailable`/`worker_unavailable`; `failing_during_execution` after
another Gateway response or invalid response; and `not_established` when local
validation or authentication prevented a meaningful operation result. The
actual HTTP status, API error, diagnostic stage and request ID remain recorded.

For text transformation, JSON report metadata records the optional
`X-Speech-Prompt-SHA256` response header when returned. This identifies the
active prompt snapshot used by the Gateway without adding prompt contents to
the report.

For sequential local TTS-to-STT fixture measurements, see the [round-trip qualification guide](roundtrip-qualification.md).
