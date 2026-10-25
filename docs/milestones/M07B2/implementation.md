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
