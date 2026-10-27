# SpeechPlatform — Backlog

This file records future ideas, possible improvements, and deferred decisions.

Items in this backlog are **not approved implementation tasks** and are not automatically part of the current milestone.

When an item is selected for implementation, move its requirements into the relevant milestone plan. Keep this file concise and update its status or link to the resulting decision.

## BL-001 — Interactive Text Regeneration

**Status:** Proposed  
**Priority:** Deferred  
**Area:** Text transformation / Client experience

### Motivation

Users may not know exactly how they want to express a thought. SpeechPlatform should help them explore alternative formulations rather than always produce one deterministic result.

Users remain responsible for reviewing and accepting generated text. Perfect semantic equivalence is not a prerequisite for offering useful suggestions.

### Proposed behavior

- Allow users to request another formulation of the same original text.
- Preserve the original text when regenerating; do not transform the previous generated result.
- Keep the selected transformation mode, format, and target language.
- Support moderate sampling variation for interactive use.
- Allow clients to present, compare, and select generated alternatives.

### Inference behavior

**Qualification:** Prefer deterministic settings such as temperature 0 and a fixed seed, supporting reproducible testing and prompt comparisons.

**Interactive:** Explore moderate nonzero temperature and variable seeds to generate useful wording alternatives.

These are proposed operating behaviors, not yet finalized API requirements.

### Open questions

- Should sampling parameters be configured server-side, exposed through the API, or both?
- Should clients request alternatives individually or in batches?
- How should alternatives be presented in Linux and future mobile clients?
- What sampling parameters produce useful variation without excessive meaning drift?
- Should regenerated alternatives retain diagnostic metadata identifying the model and prompt?

### Acceptance considerations

Evaluate variety, naturalness, latency, semantic preservation, and usability before choosing an implementation.

Do not introduce a new service or subsystem solely for regeneration.
