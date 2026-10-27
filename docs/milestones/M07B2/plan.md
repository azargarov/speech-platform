# M07B2 — Batch STT and Text Transformation Qualification

## Goal

Provide a sequential CLI that sends each existing `samples/audio/*.wav` fixture
through public Gateway STT once, then submits the exact returned transcription
to Written, Polite and Diplomatic transformations in all three supported
target-language settings. Save the ten text outputs per case under the ignored
`samples/transformed/` tree for manual review.

## Scope

- Reuse M07A Gateway authentication, HTTP transport and response validators.
- Omit an unspecified model alias so Gateway applies its configured default;
  pass any explicit alias through unchanged and preserve Gateway decisions.
- Require local STT, disable cloud-audio consent and set `local_only=true` for
  every transformation.
- Add focused offline tests and operating instructions.
- Do not alter models, API contracts or inference services. A separately
  authorized follow-up narrowly revises the existing production prompt to
  clarify semantic preservation and mode distinctions; it does not create a
  second prompt framework. This stage does not score linguistic quality or
  authorize live inference.
- The authorized M07 qualification follow-up adds expected API-error checks
  and offline OpenAPI enum drift tests to the existing single-request CLI.
  It does not change Gateway contracts, provider routing or batch local-only
  safeguards.

## Acceptance checks

- Deterministic fixture discovery and language mapping for `en`, `ru`, `sv`.
- Exactly one STT call and nine sequential text calls per successful fixture.
- Outputs contain only validated API text; collision-safe output and explicit
  atomic regeneration.
- Operation-level status, provider/model and elapsed time in JSON summary;
  content-free progress on stderr.
- Focused tests, `make verify PYTHON=.venv/bin/python`, and `git diff --check`.

## Status

Implementation is complete. The authorized live provider qualification was
executed on 2026-10-26 and is recorded in [verification.md](verification.md).
Operator validation and milestone closeout remain pending; this evaluation
does not close M07B2.

## Authorized comprehensive live quality qualification — 2026-10-26

The operator authorized a bounded live comparison of `local-qwen`,
`groq-qwen`, and `groq-gpt-oss` using the running installation. The evaluation
covers the existing nine `samples/text` fixtures, the mandatory English
Diplomatic regression, English/Swedish/Russian mode and format cases, all six
translation directions, and focused long, ambiguous, and technical inputs.
It uses `scripts.qualify` only. Groq text inference is explicitly authorized;
cloud STT is excluded. No configuration, prompt, inference parameter,
infrastructure, or service lifecycle changes are in scope. Exact inputs,
outputs, individual CLI reports, evidence, and reviews are retained under
`private/m07-quality-20261026/`.

Live output quality is evaluated separately from HTTP/CLI success. A
successful request is not a semantic pass. Operator review and closeout remain
separate gates.

## Deferred follow-up

After M07B2 closeout, propose a separate API contract-consistency audit covering
OpenAPI/Gateway/CLI alignment, duplicated protocol definitions, hardcoded
provider/language/mode lists, API path/header centralization, timeout/limit
consistency, and deterministic contract-drift checks. This audit is out of
M07B2 scope and is not authorized by this plan.
