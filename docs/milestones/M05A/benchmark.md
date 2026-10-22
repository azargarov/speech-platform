# M05A benchmark methodology

## Conditions

- Host: the active `llm` host where this repository and existing Compose
  deployment are running; record timestamp, CPU/GPU/driver, runtime version,
  free RAM/disk, service identities and initial GPU residency in
  `verification.md`.
- Workload: 39 synthetic cases, same order and v1 prompt for each candidate;
  one request in flight, 4096 context, fixed seed and generation options.
- Length classes use input characters: short under 100, medium 100–299, and
  long 300 or more. Report latency by class as well as overall.
- Request `think: false` for direct output when supported; do not compare
  reasoning modes in this initial evaluation.
- One cold first request after an explicit unload; remaining requests are
  warm while the 10-minute keep-alive applies; explicit unload after each
  candidate. No indefinite residency.
- The runner timestamps request start and first streamed response fragment.
  Ollama reports load, prompt-evaluation, generation and total durations plus
  prompt/output token counts. First-fragment timing is a measured proxy for
  time to first token, not token-level instrumentation.
- The summary classifies a request as a cold model load when Ollama's reported
  `load_duration` exceeds one second; the raw per-request counter remains
  available for review.
- Sample host `nvidia-smi` at one-second intervals during each run. Record
  maximum total GPU use and compare to baseline; Ollama's `/api/ps` provides
  model placement and reported VRAM where available. The full preflight and
  39-case runs sampled GPU and Ollama container usage once per second. Separate
  supplementary runs sampled host `MemAvailable` from `/proc/meminfo` once per
  second for short, medium and long cases; this host-RAM sampling was not
  performed during the full corpus runs. The summary classifies a request as a
  cold model load when Ollama's reported `load_duration` exceeds one second;
  raw counters remain available for review.
- Check STT `/readyz` and TTS `/healthz` before and after each candidate.
  The experiment is sequential. Simultaneous LLM/TTS use is not inferred from
  these checks.

## Quality review

Exact lexical checks inspect case-specific invariant tokens after Unicode
case-folding and whitespace normalization. A miss is a review flag. Presence
does not prove the fact is used correctly, and equivalent translations can
legitimately change ordinary wording. Human review must score preservation,
completeness, grammar, naturalness, politeness, translation accuracy,
formatting compliance, hallucination and omissions. Rate preservation and
completeness before style. Any material factual change is a critical failure;
aggregate scores cannot hide it.

## Reporting

Keep complete request, response and per-request runtime metadata under
`private/m05a/<run-id>/`. Tracked records report model digest, run time,
request settings, error counts, quality-review status, critical findings and
median/range latency and tokens/s. Report separately cold first-load and warm
requests. Never present a single run as sustained-load capacity.


## Prompt refinement continuation

The v2 experiment keeps the baseline model, one-request-at-a-time behavior,
`temperature=0`, `think=false`, `num_ctx=4096`, seed `20261022` and the other
runner options unchanged. It first runs selected confirmed v1 failures, then
a separately authored seven-case unseen corpus, then (after targeted fixes were
observed) the original 39 cases. Prompt v1 and v2 full runs use separate
private run directories. The runner records the prompt version and case-file
path with each run. Compare semantic outcomes by case; lexical flag totals are
not semantic accuracy rates. See [prompt refinement](prompt-refinement.md) for
results and limitations.
