# ADR 0021: Configurable text providers and deterministic fallback

- Status: **Accepted for M05B Stage 1 offline implementation; live qualification pending**
- Date: 2026-10-22
- Scope: optional direct text transformation/translation through Gateway
- On acceptance, refines the future local-only text assumptions in ADR 0018
  decisions 7 and 10 and the architecture overview's provider-ownership wording
  for remote text inference only. Existing STT/TTS ownership is unchanged.

## Context

The operator retains local Qwen3.5 9B and two Groq models for generated text
that users review. Models/endpoints will change. The existing Go Gateway has
strict YAML loading and HTTP conventions, while STT/TTS own separate native
inference. M05A was formally closed in commit
`a5d22ab2ce7e52b2dc15380b5391832d0523ab8e`. The accepted three-model
retention and quality limitations remain in its committed records.

## Proposed decision

Add a small in-process `internal/texttransform` module behind one additive
Gateway operation. It owns options, prompt, model selection and bounded
fallback. A single text-generation interface has Ollama `/api/generate` and
OpenAI-compatible Chat Completions adapters using standard Go HTTP. Ollama
owns local model lifecycle. No new service or native inference enters Gateway.

Extend existing Gateway YAML with providers, a model sequence and selection
policy. Full endpoints and environment-variable names are configuration.
Model order alone defines priority; stable local/cloud partitions implement
the two locality policies. Locality is explicit trusted provider metadata,
independent of protocol. No model-name selection branches are permitted.
Optional provider parameters are typed, model-specific and omitted when unset;
reasoning_effort remains configurable without a duplicate capability list or
hardcoded model tables. Share transport settings; retain provider timeouts.

Cloud access defaults off. A request may impose local-only use, never widen
permission. Explicit model selection uses that model only. Raw without
translation is exact passthrough. All other options compose into one invocation
per attempt, always from original text. Only failures classified as eligible in
the authoritative plan table can trigger bounded sequential fallback; no semantic
verification or quality retries. Report original/generated text, requested
options, actual logical model/provider and fallback/generated metadata. Public
model identity always uses the configured logical ID; canonical upstream names are internal metadata, not equality gates.

The complete schema, failure table, limits, API and stage gates are in the
[M05B plan](../milestones/M05B/plan.md). Keep that record authoritative for
details instead of duplicating tables here. Implement contracts before handlers.

## Alternatives considered

- Separate text worker: useful if native inference or independent scaling later
  warrants it, but adds deployment and an internal API for HTTP forwarding now.
- Generic provider SDK/framework: unnecessary dependency and policy surface;
  two explicit serializers are sufficient for the selected protocols.
- Reuse Python evaluation scripts in production: couples service lifecycle to
  corpus/run-file/model-map concerns and adds a process/runtime dependency.
- Numeric priorities or dynamic scoring: conflicts with meaningful YAML order
  and adds tuning without a demonstrated requirement.
- Single-call-only with manual retry: simpler, but does not meet authorized
  automatic fallback requirements. Explicit selection still offers that control.

## Consequences and limits

The Gateway gains text orchestration and outbound HTTP responsibilities, while
speech workers remain independent. Provider IDs exposed in metadata are logical
aliases, not endpoint/engine disclosures. Default-off configuration preserves
old deployments. A Gateway-only egress path and container-to-host reachability
must be reviewed and qualified before deployment; shared services stay intact.

Structural configuration errors still fail startup. Missing optional credentials
mark only their provider unavailable; runtime failures also remain isolated from
speech readiness. Enabled raw passthrough needs no provider. Provider-wide or
unknown-scope 429 suppresses that provider for the request; same-model retries
are zero. Preflight bounds the complete prompt, template overhead and output
reservation against each model context; no silent input truncation.

Text work is linked to a dedicated service lifetime for admission, shutdown and
cancellation without changing speech drain semantics. Remote inference termination
is separately qualified. The recorded 6,400 MiB free during local Qwen is below
the 8,000 MiB TTS load requirement; concurrent qualification and actual Ollama
unload evidence gate local production use. Failed/inconclusive qualification
leaves it disabled unless an appropriate restricted operating policy is approved.
No GPU scheduler is introduced. One milestone has offline implementation and
live qualification acceptance stages. Stage 1 is authorized; live qualification
remains unauthorized.

Operators can disable the optional block or restore known-good configuration.
Automatic fallback can duplicate billable work after uncertain transport outcomes. Prompt separation reduces injection
authority but cannot guarantee fidelity; accepted local language/semantic
limitations remain visible and output requires user review.

## Protocol references checked during planning

Checked 2026-10-22; these are protocol guidance, not live compatibility evidence.
Ollama documents a separate system prompt, nonstreaming generation and finite
keep-alive in its [Generate API](https://docs.ollama.com/api/generate).
Groq documents its configurable OpenAI base URL and unsupported optional fields
in [OpenAI compatibility](https://console.groq.com/docs/openai).
Its [reasoning documentation](https://console.groq.com/docs/reasoning) describes
Qwen's `none`, GPT-OSS's `low`, and separate reasoning-output controls. Support
varies by model; repeat compatibility checks when changing configured models.
