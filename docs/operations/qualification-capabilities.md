# Qualification CLI capability coverage

This matrix is tied to `api/openapi/public-v1.yaml` and the public Gateway
handler inspected on 2026-10-26. CLI enums are guarded by offline contract
drift tests. Gateway model aliases remain target configuration, not CLI enum
choices. Use `python -m scripts.qualify --help` and each command's `--help` for
the current syntax.

## Public OpenAPI surface

| API operation | Request fields and controls | CLI coverage | Verified limits / diagnostic cases |
| --- | --- | --- | --- |
| `POST /v1/stt/transcriptions` (`transcribe`) | `--audio`; `--source-language`; `--output-language`; `--model` local alias; `--timestamps`; `--stream`; `--provider local|groq`; `--allow-cloud-audio`; configured/none/missing auth; target and timeout | `scripts.qualify stt`; round-trip pins local; batch pins local | Provider and consent headers are explicit. Groq requires explicit audio consent. Groq uses server-configured model; explicit model is rejected. `timestamps=true` is sent for an expected-error probe but Gateway documents it unsupported. `stream=true` is sent as a probe and rejected; only false is supported. Deprecated `language` is represented by `--source-language`; audio media type is selected from the file extension. API error codes, HTTP status, safe response headers and stage are retained. |
| `POST /v1/tts/speech` (`synthesize`) | text or SSML; `--voice default`; `--language`; `--mode`; `--input-format`; `--audio-processing`; timeout; arbitrary exclusive WAV output | `scripts.qualify tts`; round-trip TTS stage | Public contract has no provider/model selection and only the `default` voice. WAV format and duration are checked. Gateway does not return a public model/provider identity. API errors and timeout are retained. |
| `GET /v1/tts/voices` (`listVoices`) | Authenticated GET | `scripts.qualify voices` | Validates catalog response fields and records public IDs/languages/capabilities. Worker unavailability remains a Gateway 503. |
| `POST /v1/text/transformations` (`transformText`) | text/file/stdin; `--mode raw|written|polite|diplomatic`; `--format normal|concise|structured`; `--target-language none|en|sv|ru`; optional configured `--model`; local-only CLI default or explicit `--allow-cloud`; request-local `system_prompt` via `--prompt-file`; timeout; configured/none/missing auth | `scripts.qualify transform`; `scripts.transform_samples`; round-trip does not call this operation | Raw requires Normal. Unset model is omitted; an explicit alias is passed through and never falls back. With no explicit model, configured ordered selection may try another eligible provider after failure. CLI cloud consent does not override Gateway policy. Prompt fingerprint and response provider/model/fallback metadata are retained. Invalid aliases, `cloud_not_allowed`, auth failures, validation and provider responses can be recorded with `--expect-error CODE`. No public text-model catalog exists. |
| `POST /v1/models/warmup` (`warmupModels`) | Repeat `--operation stt|tts|text_transform`; configured authentication; timeout | `scripts.qualify warmup` | Response schema, per-operation status and `complete` are recorded. This changes model residency; it is opt-in and is never run by ordinary verification. Partial warmup is a technical failure with per-operation result codes. |

OpenAPI applies bearer security to all listed routes. Production Gateway
configuration requires a token of at least 32 characters (`Config.Validate`),
and the deployed no-header read-only probe returned HTTP 401 `unauthorized`.
The handler helpers conditionally check auth when given a nonempty token, but
those helpers do not represent a deployable configuration: Gateway startup
rejects an empty token. The CLI defaults to a configured token and will not
silently omit it; `--auth-mode none` is an explicit operator-selected
no-header request. `/healthz`, `/readyz` and `/metrics` are unauthenticated
and are outside OpenAPI.

There is no public STT model-catalog route. The Gateway handler test expects
`GET /v1/stt/models` to return 404, so the stale OpenAPI operation and its
unused response schema were removed. Model aliases remain selectable through
request fields where the API supports model selection; no catalog command is
exposed by the CLI.

## Failure scenarios

| Failure class | How it is exercised or represented | Evidence retained |
| --- | --- | --- |
| Local argument/input validation | Invalid enum/combination, unreadable or oversized input, invalid URL, output collision | No HTTP status; stage `preflight`; safe message and exit code |
| Gateway request validation / size / media | Send documented unsupported STT options (`--timestamps`, `--stream`), malformed SSML via `--input-format ssml`, or an input at the configured limit; `--expect-error CODE` checks the actual returned code | HTTP status, API code, response stage and safe headers |
| Missing authentication | `voices --auth-mode missing --expect-error unauthorized`; limited to a read-only route so an open target cannot trigger inference | Actual 401/code, no Authorization header |
| Invalid authentication | Supply an operator-created invalid token in a private token file and target a protected read-only route | Actual response; token never printed |
| Cloud policy / consent | Explicit Groq alias with `--allow-cloud`, or Groq STT with `--allow-cloud-audio`; Gateway remains authoritative | Actual 403/API code; no CLI policy bypass |
| Unknown/unavailable model alias | Pass an arbitrary explicit `--model` and optionally `--expect-error` with the observed API code | Gateway status/code; alias is not locally assumed valid |
| Provider/worker failure | Select a configured provider/model; service readiness may also be checked with `ready`; no automatic retry or provider substitution | HTTP/provider metadata, status/code, stage and guidance |
| Timeout / connection / malformed response / client size bound | `--timeout`, unreachable target, and bounded response validation | Distinct classification, elapsed time, stage, safe response headers when available |
| Warmup resource failure | Explicit `warmup`; each operation status and code are validated | Overall completion plus individual operation results |

The CLI does not fabricate an arbitrary raw body or arbitrary HTTP method/path.
It cannot validate Gateway rejection of every malformed wire shape; those
cases belong in Gateway contract tests. The public API does not expose server
logs or a request-ID generation/echo contract, so external logs cannot be
attached automatically by the CLI.

## Gateway operational routes outside OpenAPI

| Route | CLI coverage | Notes |
| --- | --- | --- |
| `GET /healthz` | `scripts.qualify health` | Unauthenticated liveness check. |
| `GET /readyz` | `scripts.qualify ready` | Unauthenticated readiness check; 503 code and status are preserved. |
| `GET /metrics` | `scripts.qualify metrics` | Unauthenticated Prometheus endpoint. CLI reports metric names/count, not metric values. It is not a versioned public API operation. |

## Optional provider diagnostics

The CLI probes capabilities by selecting the provider on its existing inference
route. STT Groq probes require both `--provider groq` and
`--allow-cloud-audio`; text probes require an explicit cloud alias,
`--allow-cloud`, and Gateway policy permission. Use an operator-authorized
input. `cloud_not_allowed` identifies a policy denial, `capability_disabled`
identifies a disabled speech route, and `provider_unavailable` identifies a
provider unavailable before dispatch. For compatibility, explicitly selected
disabled Groq STT retains `provider_unavailable` and adds
`X-Speech-Capability-State: disabled`; missing credentials report the same
error code with state `unavailable`. Success records provider provenance. The
CLI's `capability_state` records available, disabled, configured
but unavailable, failing during execution, or not established. Cloud probes can
perform inference if the capability is available; only use them when that
possibility is authorized.

The root catch-all and unsupported HTTP methods are not separate capability
commands. They can be exercised by targeting a non-route with a deliberately
invalid URL only if a future explicit diagnostic probe is added; the CLI does
not accept arbitrary paths or raw request bodies. Public logs are not exposed
by the Gateway API. The report's client-side operation ID is local to the
report and is not sent to the Gateway. The CLI reports the actual Gateway
`X-Request-ID` only when returned; it never invents one.

## Shared diagnostics and safety

All single, batch and round-trip report stages record the operation/target,
elapsed time, HTTP status, actual API error code, failure stage, allowlisted
response headers, client request ID, server correlation ID when returned, and
safe troubleshooting guidance. Gateway logs are unavailable through the public
API. Explicit `--debug` additionally reads the repository-owned local Compose
logs for loopback targets (100 lines and 32 KiB per service, at most five
minutes), redacts credentials and structured payload/message fields, and saves
them in a mode-0600 file under `private/`. If a server ID is returned and
appears in logs, matching lines are selected; otherwise the evidence is labeled
time-window-only. Per-service results distinguish matching lines, a successful
empty time window (`no_matching_lines`), and retrieval failure; remote targets
are marked unavailable. An unfiltered manual tail can show older entries that
fall outside the collector's `--since` window. `--verbose` and `--debug` emit
content-free progress to stderr;
credentials and request/response text are not printed. `--gateway-url` selects
the target origin (non-loopback HTTP is rejected); `.env` remains the default.
`--api-token-file` accepts a private file under `private/` with mode 0600 or
stricter. `--auth-mode none` explicitly tests a configured unauthenticated
instance; `--auth-mode missing --expect-error unauthorized` is the negative
missing-header probe. A deliberately invalid token can be supplied through a
private token file, but the CLI never fabricates one.

Single-operation JSON reports can be written to any explicit filesystem path
with `--report`; `--evidence` can likewise explicitly retain request/response
text at any path. `private/` remains the recommended location for sensitive
qualification data. Relative paths are resolved from the current working
directory, missing parent directories are created with restrictive permissions,
and files are created exclusively with mode 0600; existing files are never
overwritten. The CLI does not add outputs to `.gitignore` or manage Git. Output
outside `private/` may be included in commits if it is tracked or added, so
review its contents and repository status before committing. Batch transformed
text outputs remain generated evaluation artifacts. Round-trip detailed reports
remain under `private/`.

## Canonical providers and qualification evidence

The tracked [`configs/gateway.yaml`](../../configs/gateway.yaml) is the
canonical Gateway configuration for the root Compose installation. It enables
text transformation with ordered selection and `allow_cloud: true`. Its text
aliases are `local-qwen` (`qwen3.5:9b-q4_K_M`, Ollama), `groq-qwen`
(`qwen/qwen3.8-27b`, Groq; `max_completion_tokens: 512`), and `groq-gpt-oss`
(`openai/gpt-oss-120b`, Groq; `max_completion_tokens: 1024`). Groq credentials
are optional for Gateway startup and are supplied through the protected file
selected by `GATEWAY_SECRETS_FILE` (default `private/cloud.env`). Missing
credentials make the selected cloud provider unavailable; they do not authorize
fallback for an explicitly selected model. For an unspecified model, ordered
selection can use a later eligible model after a provider failure, but only if
the request permits cloud and Gateway policy allows it.

Groq STT remains disabled in canonical configuration and requires both operator
enablement and per-request `X-Allow-Cloud-Audio: true`. It uses
`GROQ_STT_API_KEY`, independently of text-cloud policy. TTS has no API-level
provider/model selector; current deployment uses the configured local worker.
The public API does not expose text-model/provider health or a model catalog.

Live results below describe dated, bounded qualification runs, not the current
runtime state. The 2026-10-26 M07B2 run sent 186 text requests to the then-running
installation; its exact revision, model outcomes and quality review are in the
[M07B2 verification record](../milestones/M07B2/verification.md). It observed
one Groq Qwen upstream rate-limit failure and material semantic, language
retention and formatting defects across the samples. It did not establish a
general model winner, broad linguistic quality, or safe unattended use. HTTP
success is technical evidence only. Historical live cloud-policy probes and
older active-config observations in milestone records are snapshots of those
installations and must not be read as the current tracked configuration.

## Remaining verified limits

- STT timestamps and streaming are explicitly unsupported by the current API.
- TTS cannot select a model/provider, and it exposes only the default voice.
- No STT or text model-catalog route is exposed; aliases must come from trusted
  deployment configuration.
- The API has no text-model catalog, provider health, or public log/correlation
  endpoint. Text aliases must be supplied from trusted deployment config.
- `TextTransformRequest.model` is marked nullable in OpenAPI, but Gateway rejects
  an explicit JSON `null`; omit the property to use configured selection. The
  qualification CLI and batch tool already do this.
- Request parameters and response schemas are guarded by deterministic
  OpenAPI drift tests. Gateway-specific routes without public operations are
  recorded separately in this matrix.
- Negative HTTP testing can select expected API codes and request known
  invalid/disabled options. The tool does not provide arbitrary raw payloads,
  destructive load tests, or automatic retries.
- Live linguistic quality remains human-reviewed; HTTP success and WER/CER do
  not establish semantic correctness.
