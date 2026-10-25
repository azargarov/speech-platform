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

## Acceptance checks

- Deterministic fixture discovery and language mapping for `en`, `ru`, `sv`.
- Exactly one STT call and nine sequential text calls per successful fixture.
- Outputs contain only validated API text; collision-safe output and explicit
  atomic regeneration.
- Operation-level status, provider/model and elapsed time in JSON summary;
  content-free progress on stderr.
- Focused tests, `make verify PYTHON=.venv/bin/python`, and `git diff --check`.

## Status

Implementation authorized and in progress. Live qualification, user validation
and closeout are pending separate authorization.

## Deferred follow-up

After M07B2 closeout, propose a separate API contract-consistency audit covering
OpenAPI/Gateway/CLI alignment, duplicated protocol definitions, hardcoded
provider/language/mode lists, API path/header centralization, timeout/limit
consistency, and deterministic contract-drift checks. This audit is out of
M07B2 scope and is not authorized by this plan.
