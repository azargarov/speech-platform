# M05B Stage 1 context-budget review

Status: **focused offline correction recorded; included in Stage 1 operator PASS (2026-10-22).**
No deployment, live inference, configuration of the production Gateway, Stage 2,
milestone closeout or commit was performed.

## Calculation

Preflight counts UTF-8 bytes of the exact system prompt and serialized user
message. The user message contains the serialized options plus a JSON-escaped
text string and fixed labels/newlines. It adds a fixed 512-unit framing
allowance, configured `prompt_overhead_tokens`, and the full output reservation
(`num_predict` for Ollama; `max_completion_tokens`/`max_tokens` for Chat
Completions). For the example local model:

| Term | Units |
| --- | ---: |
| Context limit | 4,096 |
| Fixed framing allowance | -512 |
| Configured template overhead | -512 |
| Output reservation | -1,024 |
| System prompt | -1,069 bytes |
| Empty serialized user wrapper and default options | -112 bytes |
| Remaining ASCII text budget | **867 serialized bytes** |

The former prompt was 1,477 bytes, so the same calculation left 459 bytes.
Escaped characters consume additional serialized bytes; the request is checked
as a whole before any provider call and is rejected/skipped rather than cut.
The 512 framing allowance is added to a byte count despite being named in
tokens: this intentionally pessimistic mixed-unit calculation is only a valid
context bound if tokenizer/template qualification supports the one-byte/one-token
assumption. This review does not establish that qualification.

## Prompt and counter assessment

The shorter prompt retains all four modes, all three formats, target-language
semantics, ambiguity/register preservation, protected content categories,
non-invention, and output-only/no-metadata rules. A deterministic offline test
pins its resulting example budget; existing boundary coverage checks equality,
one unit over, multilingual text preservation and zero provider calls on
overflow.

An accurate model counter is not a small, reliable Stage 1 change. The current
official Ollama Generate API documents `prompt_eval_count` only in the response,
after inference, and the documented API endpoint list does not expose a
preflight tokenizer. A preflight would need the exact installed tokenizer,
model revision, and the same template/framing the server applies. A separately
vendored tokenizer or guessed API endpoint would add model/version coupling and
still need equivalence validation. This review does not establish which Ollama
version is installed. See the [Generate API](https://docs.ollama.com/api/generate)
and [current Ollama API endpoint list](https://github.com/ollama/ollama/blob/main/docs/api.md).

Reducing the 1,024-token output reservation increases input budget one-for-one,
but directly caps transformed output. Dictation may expand during translation
or restructuring. The adapters accept only normal stop completions; a provider
that reports a length stop is rejected. Lowering the reservation therefore
risks more incomplete responses/failures and is not recommended as the first
correction.

## Decision and remaining assumptions

The smallest correction is prompt compaction, preserving the existing 4K local
context, 512 overhead, 1,024 output reserve, refusal-before-dispatch behavior,
and model selection/fallback. No STT/TTS path, production configuration,
provider adapter, or GPU policy changed. The resulting 867 bytes is a useful
increase for short dictation, but remains modest; the API still allows 10,000
input bytes and larger requests can be rejected for local inference.

Before live enablement, qualify the exact installed Ollama/model revision,
tokenizer behavior on Unicode and special-token-like text, the rendered prompt
template/system-message framing, actual context handling, and completion stop
semantics. GPU coexistence remains independently unqualified; this review does
not authorize a larger context or live request.

## Evidence

- **OBSERVED:** offline command `go test ./internal/texttransform -run 'Test(ExampleLocalSerializedInputBudget|ContextBoundaryAndMultilingualInputAreNotTruncated|ContextBoundaryCountsJSONEscaping|ContextRejectionMakesNoCall|ValidateConfigRejectsFixedPromptThatCannotFit)$'` passed in the current workspace.
- **OBSERVED:** prompt/budget byte lengths were calculated from the checked-in Go prompt and serializer; 1,069 + 112 bytes leave 867 under the example values.
- **INTERPRETATION:** prompt compaction improves practical input capacity without weakening configured output reserve or changing context memory use.
- **NOT ESTABLISHED:** installed Ollama version, exact tokenizer/template bound, live semantic quality, output completion behavior for target models, and GPU coexistence.

## Operator-approved 8K investigation amendment — 2026-10-22

The preceding calculation and 4K recommendation are retained as the original
review record. Under the operator's new authorization for offline
configuration/tests, the example local Qwen context is now 8,192. The fixed
prompt and conservative checks, 512-unit framing, 512-token configured
template overhead, and 1,024-token output reservation remain unchanged. The
same arithmetic now leaves 4,963 serialized ASCII source bytes:

`8192 - 512 - 512 - 1024 - 1069 - 112 = 4963`.

Offline regression coverage tests the resulting budget, existing multilingual
and JSON escaping boundaries, and a synthetic longer dictated request that is
rejected at 4K and accepted at 8K before provider dispatch. The M05A sequential
runner now supports explicit 4K/8K selection with 4K remaining the default; the
controlled comparison procedure is in
[qwen-context-comparison.md](qwen-context-comparison.md).

This supersedes the earlier 4K example recommendation for the offline example
only. **INTERPRETATION:** 8K is suitable to enter Stage 2 qualification because
it expands the conservative budget without reducing output reservation or
weakening preflight. **NOT ESTABLISHED:** no live acceptance, GPU memory,
latency, load/unload, longer-request output quality, or coexistence evidence
was collected. A context above 8K is not yet justified; reconsider it if
representative inputs exceed the 8K budget or fail actual live acceptance.
Stage 2 remains unauthorized and no live benchmark was run.
