# M05 — Voice dictation and text transformation

Status: **FUTURE; NOT STARTED. This work is outside STT v1 acceptance.**

## Purpose

Support voice-driven writing in Russian, English and Swedish by keeping speech recognition, optional translation and optional text transformation as independent operations. Preserve the original raw transcription in every transformed result.

## Future scope

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
