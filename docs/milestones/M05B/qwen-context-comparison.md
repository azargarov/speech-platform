# M05B Qwen context comparison — Stage 2 execution protocol

Status: **The resumed sequential 4K/8K comparison completed on 2026-10-22;
all 18 responses and passive telemetry were recorded. Both contexts completed
the nine-case corpus, naturally expired and recovered GPU memory. Seven cases
at each context failed lexical quality invariants; operator review is pending.
See [stage-2a-qualification.md](stage-2a-qualification.md). Stage 2B and
deployment remain unauthorized.** No shared Ollama settings, production
Gateway, STT/TTS deployment or prior M05A evidence was changed.

## Offline budget result

The example local Qwen configuration now uses `context_limit_tokens: 8192`.
The system prompt, 512-unit fixed framing allowance, 512-token configured
template overhead, 1,024-token output reservation and common conservative
serialized-byte preflight remain unchanged. For the existing 1,069-byte
system prompt and 112-byte empty serialized user wrapper, the resulting maximum
ASCII source budget is:

`8192 - 512 - 512 - 1024 - 1069 - 112 = 4963 serialized bytes`.

Escaping counts toward the serialized user-message length; Unicode uses UTF-8
bytes. No truncation is performed. Offline tests cover multilingual equality,
JSON escaping equality/overflow, and a synthetic longer dictated text that is
rejected at 4K and accepted at 8K before provider dispatch. This validates the
configured arithmetic only; it does not establish model tokenizer/template
fit.

## Controlled live comparison — Stage 2A only

Use a Stage 2A harness that sends bounded requests with
`keep_alive: "60s"` and never sends an unload request. Do not use the existing
`scripts/m05a_eval.py` live path because it explicitly unloads after a run.
Keep the same exact installed model digest, prompt v2, private synthetic
corpus, host, runtime, seed and batch/thread settings. Stage 2A is
bounded to one 4K run followed by one 8K run; do not repeat or reverse order.
Each context uses the same nine short/medium/long English, Swedish and Russian
samples. Keep each run in a new private directory; never overwrite or edit
existing `private/m05a` evidence. Keep all outputs and transcripts private.

The case file remains `private/m05a/stage2a-cases.jsonl`; preserve its existing
offline validation. The exact request envelope and abort rules are in
`stage-2a-qualification.md`; this protocol is not separate authorization.

Capture successful completion and Ollama prompt token counts for actual
context acceptance; a preflight fit alone is insufficient. The nine prepared
cases are the complete Stage 2A request budget; do not add separate long-input
requests or retry failed cases.

Before each setting, capture GPU and all model residency, then sample GPU,
`/api/ps`, service health and Ollama request logs once per second. Capture the
same measures immediately afterward and through a 120-second natural-idle
observation window. Record inference success, post-inference residency,
natural idle expiration and confirmed GPU memory recovery as separate results.
Mark measurements contaminated if another client request/model load is
observed. Abort if requests or GPU use cannot be attributed safely. Do not run
simultaneous STT/TTS/LLM workloads or infer coexistence from sequential health
checks. Cold-start and forced-unload behavior are not measured by this
non-destructive protocol.

## Qualification decision criteria

Stage 2A must record baseline/peak/post-run memory and residency, latency,
long-request acceptance/completion, natural idle expiration and confirmed
memory recovery, and the qualified
tokenizer/template bound. 8K is a candidate for Stage 2 qualification, not
approved for production based on this offline work. A context larger than 8K
should be investigated only if representative dictated inputs still fail the
conservative budget or actual acceptance/completion at 8K, and only after the
GPU memory/latency trade-off is reviewed. The current arithmetic leaves up to
4,963 serialized source bytes at 8K; larger-context GPU residency and quality
are not established.

## Evidence status

- **OBSERVED:** offline code arithmetic and regression tests, once executed,
  establish the local serialized-byte budget and pre-dispatch behavior.
- **INTERPRETATION:** 8K provides materially more accepted input budget while
  retaining all configured overhead and output reservation.
- **OBSERVED:** the partial 4K attempt recorded one successful API completion,
  452 prompt tokens, a 0.568-second backend generation phase, 8,508 MiB sampled
  peak GPU use, natural expiry and memory recovery. The output itself was not
  saved, so no quality claim is established.
- **NOT ESTABLISHED:** a comparable nine-case 4K/8K result, 8K corpus memory
  and latency, full output quality, tokenizer/template bounds, STT/TTS
  coexistence, or whether a context larger than 8K is worthwhile.
