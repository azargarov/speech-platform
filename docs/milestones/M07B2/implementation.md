# M07B2 implementation record

## Design

One module, `scripts/transform_samples.py`, drives the existing public Gateway
client helpers in `scripts.qualify` and multipart builder in
`scripts.api_smoke`. It discovers and preflights selected WAVs and output paths,
then performs STT once followed by nine sequential transformations per case.
It writes only validated response text. New files are exclusively created with
mode `0600`; `--regenerate` writes a sibling temporary file and atomically
replaces only the expected output. Generated result directories are ignored by
Git. No new dependency or API client abstraction is introduced.

## Implemented scope

The batch tool adds no dependencies. The prompt follow-up changes Gateway
generation instructions only; it changes no route, API or worker behavior. The
tool does not assess semantic preservation; generated text, criticism,
numbers, technical terms and intent require human review. See
[verification](verification.md) for executed commands and outcomes. No live
inference was performed as part of implementation.

## Request correction

The first operator-reported live attempt received HTTP 400 `invalid_options`
after a successful STT request. Source inspection found that the batch client
serialized the optional `model` field as JSON `null`. Gateway validation
rejects `null` for option fields, while an omitted `model` allows configured
selection. The batch payload now omits `model` when no explicit alias is
selected. Mode, normal format, target language and `local_only=true` remain
explicit. No Gateway or public contract change was made. The public schema
currently marks `model` nullable, while deployed validation rejects explicit
null; omission avoids relying on that inconsistency.

## Production prompt correction and reload

The active prompt is externalized to the version-controlled
`configs/prompts/text-transformation-system.txt`. It distinguishes Written,
Polite and Diplomatic, says tone changes cannot change substance, preserves
material attribution and recurrence, and applies translation and style
together. Raw and format behavior remain unchanged. No model, sampling,
routing or cloud policy changed. The source prompt is loaded and validated at
startup, can be atomically reloaded on SIGHUP, and exposes the active prompt
SHA-256 in a response header. Each request holds one immutable prompt snapshot.
Prompt content is bounded and checked against enabled model context before
activation. This remains one prompt source and one reload path; there is no
prompt registry or additional processing stage. Static tests do not establish
linguistic quality, which remains for controlled live comparison and human
review.

## Qualification CLI model selection

The M07A qualification CLI now omits the optional request `model` property
when `--model` is not supplied. An explicit alias is passed through unchanged;
the existing `--allow-cloud` flag only sets `local_only=false` and does not
override Gateway policy. The Gateway remains responsible for alias validity,
availability and provider authorization. The batch qualification CLI already
omits an unset `model` field and records the model returned by the Gateway.

Read-only inspection of the effective Gateway model configuration on
2026-10-25 found enabled aliases `local-qwen` (local), `groq-qwen` (cloud),
and `groq-gpt-oss` (cloud), with ordered routing and cloud disabled. Consequently
the local alias is eligible by default; explicit cloud aliases remain blocked
by current policy, even when the CLI permits cloud routing. These values are
configuration observations, not guarantees about future deployments.

The public OpenAPI request schema currently permits `model: null`, but Gateway
request validation rejects null option fields. The client avoids this
inconsistency by omitting an unset field. The smallest contract correction is
to make request `model` optional and non-nullable; no OpenAPI or Gateway change
was made as part of this CLI correction.

## M07 qualification CLI follow-up

The single-request CLI now accepts `--expect-error CODE`. A matching Gateway
API error with an HTTP error status is recorded with its actual status/code and
counts as a successful expected-error qualification; a success response or a
different API code fails that expectation. This uses the existing request and
report path and does not bypass authentication or Gateway validation.

An offline contract-drift test compares the CLI's STT provider/language,
transformation mode/format/language, and TTS language/mode/audio-processing
choices with the public OpenAPI enums. Configured model aliases remain owned by
Gateway configuration. Existing local-only batch and round-trip behavior is
unchanged; no provider adapter, API client framework, service, or dependency
was added.

The CLI also exposes the contract's optional local STT model alias and TTS
`text`/`ssml` input format. The existing multipart helper accepts an optional
model field while preserving its original wire format when omitted. Groq STT
rejects `--model` locally because the contract uses its configured server
model. No TTS model/provider selector was added because the public TTS contract
does not provide one.

## Comprehensive diagnostic CLI coverage

The single-request `scripts.qualify` CLI maps every OpenAPI operation ID:
STT, TTS, text transformation, TTS voice catalog and model warmup. It exposes
every API-supported request choice, allows arbitrary Gateway origins with
HTTPS enforcement off loopback, uses configured or
operator-supplied private tokens, and captures content-free structured
diagnostics. Warmup is explicit because it changes model residency. Health,
readiness and metrics checks cover Gateway operational routes outside
OpenAPI. The batch and TTS-to-STT tools reuse the same safe response-header,
troubleshooting and failure-stage helpers and accept the same target selector;
their purpose-specific local-only routing remains unchanged.

The route/field/provider/error matrix and verified limits are maintained in
[`qualification-capabilities.md`](../../operations/qualification-capabilities.md).
Contract drift tests fail if a public OpenAPI operation or CLI enum/field
coverage changes without updating the command map/tests. Inspection found a
real discrepancy: OpenAPI declares `GET /v1/stt/models`, while the Gateway
handler lacks the route and its test expects 404. The contract correction
removes the unsupported route/schema and the CLI's catalog command; configured
model aliases remain request parameters where supported. Production auth is
mandatory: Gateway config validation rejects an empty or short token, and a
live no-header read-only probe returned 401 `unauthorized`. The handler's
conditional check for an empty token only affects unvalidated internal test
construction, not the supported Gateway startup path. Public API logs and a
Gateway-generated request ID are not available; reports make that absence
explicit and do not invent server correlation. Groq remains blocked by active
Gateway configuration and is not bypassed.

## M07 integration: end-to-end request correlation

The Gateway now creates a UUIDv4 for each request, replaces any supplied
`X-Request-ID`, returns it, and carries it through its context and structured
request logs. Authentication remains inside the route handler and is evaluated
independently of the correlation ID. Local STT/TTS worker calls receive that
Gateway-owned ID; workers accept only canonical UUIDv4 values. STT also forwards
the ID through supervisor IPC for inference failure events. Text-provider
attempt logs use the same ID. Worker lifecycle logs contain request metadata
and bounded API error codes only, not speech or text payloads.

The qualification CLIs retain client-local IDs as separate metadata and use
only server-returned IDs for exact log matching. Diagnostics stay opt-in,
loopback-only, service-scoped and bounded; missing exact matches remain
explicitly distinct from time-window-only evidence. Public OpenAPI documents
the additive response header. The earlier model-list route discrepancy is
resolved by removing the unsupported operation/schema from OpenAPI and its CLI
surface. This section supersedes the earlier implementation note that server
request IDs were unavailable; that note describes the pre-integration state.
