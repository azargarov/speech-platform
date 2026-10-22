# M05A implementation record

Status: **Local evaluation and Groq adapter implementation complete; both Groq runs are complete and operator review is pending. No production integration or service configuration change.**

## Design summary

The task is an isolated evaluation using the existing Ollama runtime. A small
standard-library runner consumes a synthetic JSONL corpus and versioned
prompt, calls the Ollama API sequentially, and stores detailed outputs in
ignored `private/m05a/`. Tracked artifacts describe procedure and summarized
evidence. No API contract, Gateway, STT, TTS or deployment configuration is
changed.

## Changes and deviations

- Added the 39-case synthetic corpus in `cases.jsonl`, direct-output prompt v1,
  benchmark method, comparison record, operator checklist and the five M05A
  milestone records. `PLANS.md` now marks M05A in progress; M05B remains
  unstarted and the broader M05 plan remains historical/future scope.
- Added `scripts/m05a_eval.py`, a standard-library-only sequential runner for
  the existing Ollama HTTP API. It records exact model digest, request
  configuration, original input, output, per-request timing/token counters,
  lexical invariant flags, `/api/ps` placement, one-second GPU and Ollama
  container samples, host RAM samples for short/medium/long cases, and unload
  outcome under ignored `private/m05a/`.
- Added ten focused tests for corpus/prompt validation, raw-format
  constraints, invariant boundaries, length classes, load classification,
  private path containment and memory summaries.
- Downloaded only `qwen3.5:9b-q4_K_M` and `gemma3:12b-it-q4_K_M` into the
  existing Ollama store. Ran one safety preflight and all 39 cases for each
  candidate; also captured short/medium/long resource samples. Both models
  were explicitly unloaded after each run and `/api/ps` was empty afterward.
  Candidate files remain installed but unloaded pending operator decision;
  cleanup commands are in `user-validation.md`.
- No Ollama/Dify container configuration, running Speech Platform service,
  model setting, API, M00 experiment or deployment file was changed. The
  existing Ollama container was not restarted.
- Deviation: an initial summary treated any nonzero `load_duration` as cold.
  Warm calls report about 0.01 seconds of load overhead, so the summary now
  classifies only values above one second as cold. Existing full-run summaries
  were recomputed from their preserved per-request records; no inference was
  rerun for this correction.

## Prompt refinement continuation — 2026-10-22

- Added versioned [prompt v2](prompts/v2.md) without changing v1, plus a
  separate seven-case [unseen corpus](unseen-cases.jsonl).
- Extended the runner to accept explicit prompt, prompt version and case file;
  the original defaults remain v1 and the 39-case corpus. Added focused tests
  for the v2 rules and unseen corpus structure.
- Preserved all baseline run directories. Captured v2 targeted, unseen and full
  outputs separately under `private/m05a/`; each run completed and unloaded
  the model. The full run completed 39/39. No model was downloaded.
- Manual review finds v2 fixes the `sv-03` negation inversion and `sv-09`
  invented remediation, while retaining significant critical failures,
  including language drift, uncertainty/status changes, and identifier
  mutation. See [prompt refinement](prompt-refinement.md).
- No deployment configuration, Gateway, STT/TTS worker, or model lifecycle
  configuration changed. STT/TTS were healthy before and after with zero
  observed restarts. Simultaneous LLM/TTS use remains untested.

## Groq cloud comparison continuation — 2026-10-22

- Added `scripts/m05a_groq_eval.py`, a standard-library Groq chat adapter
  alongside the unchanged Ollama path. It reuses corpus, prompt and lexical
  helper functions, holds prompt v2 and the 46-case order fixed, and supports
  preview, sequential execution and configuration-checked resume.
- The adapter records per-case output, exact/returned model identity, response
  ID, inference settings, completion reason, tokens, request wall time,
  provider processing-time header, rate-limit headers, retries and sanitized
  API outcome. Results live under private `private/m05a/` paths. API keys and
  full API error bodies are not recorded.
- Qwen uses `reasoning_effort=none`; GPT-OSS uses `reasoning_effort=low` with
  reasoning excluded. Requests use temperature 0, top_p 1, fixed seed and a
  1024 completion token limit. Default pacing is 2.1 seconds with a 60 second
  bounded timeout and at most two bounded retries.
- Added focused offline coverage for key rejection, request construction,
  reasoning settings, response parsing, quota/auth errors, retry delay,
  timeouts, malformed responses, persistence, secret omission, preview and
  resume. No new dependency was introduced.
- Groq API documentation was checked 2026-10-22; detailed sources and current
  published rate-limit examples are recorded in `groq-cloud-evaluation.md`.
- At the initial implementation stage, the execution shell did not expose
  `GROQ_API_KEY`; that historical blocker was resolved during the transport
  correction below. No cloud model quality claim is made.
- Corrected the v2 report's stale 15-case final summary to 17 distinct cases,
  explaining that `mix-03` and `perf-long` were omitted in the former tally.
  No original output or case-level evidence was altered.


## Groq transport correction and execution — 2026-10-22

- The user reported that the exact credential succeeded with curl while the
  prior `urllib` runner received Cloudflare HTTP 403 Error 1010. An equivalent
  one-case `requests` probe using the runner's payload returned HTTP 200. The
  adapter now uses the already-installed `requests` package for POST requests.
  It passes JSON, Authorization and Content-Type as before; the requests client
  supplies its own user agent. No new dependency or production configuration
  was added.
- Kept bounded timeout, sanitized transport errors, provider status and
  `Retry-After` classification, retry/backoff, private result persistence, and
  successful-case resume behavior. Updated transport tests; the focused adapter
  suite passed. A live `call_groq` probe completed with HTTP 200 before either
  benchmark started.
- Executed both fixed 46-case comparisons sequentially with prompt v2. Qwen
  completed 46/46 using 50 attempts and four recoverable 429 retries. GPT-OSS
  completed 46/46 using 46 attempts without retry. Fresh result directories and
  all prior evidence were preserved. See
  [Groq evaluation](groq-cloud-evaluation.md) for paths and transport limits.
- Tightened `private/groq_api` permissions from 0644 to 0600 before reading it.
  The key remained in Python memory and was excluded from command-line arguments,
  logs and result files.
