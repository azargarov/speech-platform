# M05B Qwen context comparison — Stage 2 execution protocol

Status: **prepared offline; live inference is not authorized by this record.**
Do not execute until a separate Stage 2 authorization identifies the host and
window. No shared Ollama settings, production Gateway, STT/TTS deployment or
prior M05A evidence is changed by this protocol.

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

## Controlled live comparison to run only after authorization

Use the existing `scripts/m05a_eval.py` sequential runner with the same exact
installed model digest, prompt, corpus, host, runtime, seed, batch/thread
settings and one-request-at-a-time behavior. Run 4K first, then 8K, and repeat
in reverse order only if the authorization permits the additional runs. Keep
each run in a new private directory; never overwrite or edit existing
`private/m05a` evidence. Keep all outputs and transcripts private.

Example commands (not executed; execute only after Stage 2 authorization):

```sh
python scripts/m05a_eval.py --validate
python scripts/m05a_eval.py --model qwen3.5:9b-q4_K_M --num-ctx 4096 \
  --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2 \
  --run-dir private/m05a/qwen-context-4k-<run-id>
python scripts/m05a_eval.py --model qwen3.5:9b-q4_K_M --num-ctx 8192 \
  --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2 \
  --run-dir private/m05a/qwen-context-8k-<run-id>
```

Use the same representative long dictated request for each setting. Include
the offline synthetic request described in
`TestEightKContextAcceptsLongDictationRejectedAtFourK` in a private one-case
case file conforming to the M05A case schema, and run it as a separate
`--case-id` run at both settings. The normal corpus remains the quality and
latency comparison. Capture successful completion and Ollama prompt token
counts for actual context acceptance; a preflight fit alone is insufficient.

Before and after each setting, record GPU baseline and check STT readiness and
TTS health. Use the existing one-second `nvidia-smi`, Ollama container and host
memory sampling. Record per-request load duration, total latency, time to first
fragment, prompt evaluation, output evaluation, peak GPU memory, model
placement/VRAM from `/api/ps`, and `/api/ps` after the runner's explicit unload.
Also record Ollama version, model digest, driver, initial GPU residency and
unload/recovery observations. Do not run concurrent STT/TTS/LLM workloads or
infer coexistence from sequential health checks. Stop on unexpected service
degradation, unrelated model residency, failed unload, or memory pressure; do
not kill shared Ollama or issue an unscoped unload.

## Qualification decision criteria

Stage 2 must review the measured 4K/8K memory delta, cold-load and warm latency,
long-request acceptance/completion, unload/recovery, and the qualified
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
- **NOT ESTABLISHED:** GPU memory, cold/warm latency, load/unload behavior,
  actual tokenizer/template context acceptance, long-request output quality,
  STT/TTS coexistence, and whether a context larger than 8K is worthwhile.
