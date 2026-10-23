# M05 — Voice dictation and text transformation

Status: **Umbrella roadmap: M05A evaluation complete and closed; M05B Stage 1 and Stage 2A/2B are operator-accepted. The 4K/8K comparison completed all 18 requests with natural expiry and GPU recovery. Seven outputs per context failed lexical invariants and remain failed; local Qwen is retained only for user-reviewed transformations, with no quality guarantee. Stage 2C deployment remains separately gated. Clients remain future work. This work is outside STT v1 acceptance.**

## Current planning slice — 2026-10-22

The [M05B proposal](../M05B/plan.md) is the current design for initial direct
text transformation/translation: `raw`, `written`, `polite`, `diplomatic`;
`normal`, `concise`, `structured`; targets `none`, `en`, `sv`, `ru`. It proposes
an optional module in Gateway with configurable local/cloud providers, stable
model order and explicitly permitted fallback. Translation can compose with
rewriting in one invocation, while STT remains an independent operation.

These requirements supersede the provisional mode list and local-only text
assumption below for M05B. Those earlier ideas are historical future options,
not an existing public API. The operator retains all three evaluated Qwen/GPT-OSS
options subject to user review of generated text. M05A is closed for its
bounded evaluation scope, with known limitations recorded in its result.
M05B has an offline implementation gate, a bounded Stage 2A local qualification, and a separately authorized Stage 2B live-service qualification;
its revised plan addresses Astra findings A–I, including speech availability
with missing optional keys and a shared-GPU gate on local production use.
See [ADR 0021](../../adr/0021-configurable-text-transformation.md).
This planning update authorized no M05B implementation or deployment. Stage 1
implementation is operator-accepted. Stage 2A is accepted with the limitations
recorded in its qualification; Stage 2B technical qualification is accepted PASS.
Stage 2C deployment and M05B closeout remain unauthorized.

## Purpose

Support voice-driven writing in Russian, English and Swedish by keeping speech recognition, optional translation and optional text transformation as independent operations. Preserve the original raw transcription in every transformed result.

## Earlier provisional scope and later client work

- Per-request modes: `raw`, `clean`, `business`, `friendly`, `casual` and `formal_to_casual`.
- A separate optional transformation service or module behind Gateway. It uses a configurable local LLM backend; the STT inference worker must not include or call an LLM.
- STT remains usable when text transformation is unavailable.
- Transformation preserves facts, negation, technical terms, identifiers, names, numbers, dates and intended commitments. It must not silently invent missing information.
- Keep the mode list configurable and extensible. Reverse transformations and user-defined modes are future extensions, not promised behavior in the first slice.
- API selection is request-level; backend policy does not define desktop shortcuts.
- A future desktop client may provide persistent mode selection, temporary override, push-to-talk and insertion into the active application. Its design must account for Linux Wayland shortcut registration and input-injection restrictions. Mobile clients may later provide equivalent mode selection.

## Boundaries and readiness

This milestone starts only after STT v1 has been accepted. Before implementation, define a provider-independent transformation contract, local model/resource policy, factual-preservation evaluation set, privacy behavior and an explicit unavailable-service response. Translation remains its own operation and advertises only qualified language pairs. Keep raw transcription available whether translation or transformation succeeds.

No text transformation, LLM dependency, desktop shortcut handling, input injection or mobile client belongs to STT v1.
