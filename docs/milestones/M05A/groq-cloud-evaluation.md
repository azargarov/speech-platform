# M05A Groq cloud comparison

Status: **Both provider runs and semantic review complete; operator validation pending. M05A remains IN PROGRESS; M05B is not started.**

## Evaluation plan and boundaries

Compare `qwen/qwen3.8-27b` and `openai/gpt-oss-120b` against the existing
local Qwen3.5 9B Q4_K_M evidence. Use the unchanged prompt v2 and exactly 46
synthetic cases: the original 39-case `cases.jsonl` followed by the separate
seven-case `unseen-cases.jsonl`. Prompt v1/v2 and all prior local results stay
unchanged. Each model may receive one full run; an interrupted run can resume
successful cases only after checking its saved configuration.

Responsibilities remain narrow: `scripts/m05a_eval.py` retains Ollama behavior
and shared corpus/prompt helpers. `scripts/m05a_groq_eval.py` owns only the
Groq chat-completions request, provider error/retry policy, private run records
and preview mode. It adds no dependency, generic provider framework, service,
Gateway route or deployment configuration. All data sent to Groq is synthetic.
Cloud inference has no effect on local GPU memory or local inference services.

The runner uses `GROQ_API_KEY` only in the Authorization header. It does not
write credentials, authorization metadata or provider error bodies to artifacts
or logs. Missing credentials reject a live run. Preview mode performs corpus,
prompt and plan validation without requiring credentials or making a request.
Raw outputs and telemetry belong under ignored `private/m05a/groq-<model>-v2-20261022/`
directories, with restrictive directory/file permissions. No `.env`, Compose,
Gateway, STT or TTS configuration is changed.

## Model selection and inference settings

| Exact model | Groq reasoning setting | Reasoning output | Common generation settings |
|---|---|---|---|
| `qwen/qwen3.8-27b` | `reasoning_effort=none` | excluded | temperature 0, top_p 1, seed 20261022, max_completion_tokens 1024 |
| `openai/gpt-oss-120b` | `reasoning_effort=low` | `include_reasoning=false` | temperature 0, top_p 1, seed 20261022, max_completion_tokens 1024 |

Groq documents Qwen 3.8 `none` as disabling reasoning, and GPT-OSS 120B
supports `low`, `medium`, or `high`; GPT-OSS's default is `medium`. The chosen
low setting limits extra reasoning-token use while enabling the model-specific
reasoning mode. No chain-of-thought is requested or stored. Common decoding
settings are held fixed for comparison; deterministic behavior is best effort,
not guaranteed by the provider. The exact setting and `include_reasoning=false`
are recorded in run and per-request metadata. If Groq rejects either reasoning
parameter with HTTP 400, the run records that rejection and stops; it does not
retry with another reasoning setting.

Sources checked 2026-10-22: [Groq API reference](https://console.groq.com/docs/api-reference),
[reasoning configuration](https://console.groq.com/docs/reasoning),
[rate limits](https://console.groq.com/docs/rate-limits),
[API errors](https://console.groq.com/docs/errors).

## Rate limits and execution controls

The runner makes requests sequentially, defaults to a 2.1-second delay, bounds
timeouts to 1–180 seconds (default 60), and permits at most two retries. HTTP
429 honors `Retry-After` with a 120-second cap; transient 5xx/network errors
use bounded exponential backoff. Authentication, invalid model, other 4xx,
and recognized quota exhaustion stop the run. Error bodies are classified but
not persisted because they can echo request data. Successful requests are not
repeated. Summaries contain request/retry totals, token usage, per-request
network-inclusive wall time, model response ID, finish reason, processing-time
header where returned, and rate-limit headers.

Groq's currently published Developer plan table lists 30 RPM, 1K RPD and 8K
TPM for each exact model. Limits are organization-level and the account's
actual plan/remaining quota can differ; 46 successful requests per model fit
the published RPD example but are not guaranteed to fit the user's account.
Preview reports 46 expected successful calls per model, and a maximum of 138
attempts at the two-retry cap. A full run is one model at a time. Cost is
**NOT ESTABLISHED** until actual account plan, usage and billing are reviewed.

### Preview commands

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_groq_eval.py --preview --model qwen/qwen3.8-27b
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_groq_eval.py --preview --model openai/gpt-oss-120b
```

### Full-run commands

Run only after `GROQ_API_KEY` is available in the process environment. Do not
put the key in command-line arguments or output. Run sequentially, preserve the
first result directory, and stop if a daily quota or other nonrecoverable
condition is reported.

```sh
umask 077
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_groq_eval.py --model qwen/qwen3.8-27b --run-dir private/m05a/groq-qwen3.8-27b-v2-20261022
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_groq_eval.py --model openai/gpt-oss-120b --run-dir private/m05a/groq-gpt-oss-120b-v2-20261022
```

After an interruption, inspect `run.json` and `results.jsonl`, confirm the
exact model, prompt version and case IDs, then resume only that same directory
and configuration using `--resume`. A failed request is retried on resume;
successful cases are skipped. Do not launch a second complete run to repair
semantic output.

## Review method

Review all 46 same-input pairs manually under the established M05A criteria.
Classify each critical case by failure type and distinguish API transport
errors from model-quality failures. Specifically inspect `sv-03`, all Swedish
and Russian no-target cases, `en-11`, `ru-03`, `mix-02`, `mix-03`,
`perf-medium`, `perf-long`, and the unseen Russian complaint for invented
provider response. Lexical invariant flags are screening aids only; they are
not semantic failure rates or proof of correctness. No automatic language
identifier is added; target-language compliance is a manual review item,
including mixed-language inputs.

Compare Qwen3.5 local Ollama wall-clock request timings only with cloud
network-inclusive request wall-clock timings. Groq processing-time headers are
reported separately and are not treated as user-visible latency. Existing
local runs used prompt v1/v2 and Ollama-specific settings documented in
`verification.md`; provider, model, reasoning, hardware and timing boundaries
differ. The sample is too small for statistical significance.

## Execution summary and quality results

| Candidate | Successful cases | API errors / retries | Critical semantic cases | Language failures | Identifier mutations |
|---|---:|---:|---:|---:|---:|
| Qwen3.5 9B Q4_K_M, local Ollama v2 | 39/39 | 0 / 0 | 17/39 | See local review | `mix-02`, `mix-03` |
| Qwen3.8 27B, Groq v2 | 46/46 | 4 / 4 | 4 original; 0 unseen | No confirmed failure | No confirmed mutation; judgment cases remain |
| GPT-OSS 120B, Groq v2 | 46/46 | 0 / 0 | 5 original; 1 unseen | No confirmed failure | Unicode/spacing fidelity requires operator judgment |

Cloud execution completed on 2026-10-22 after a transport change. See the
observed run evidence below and [case-by-case semantic review](groq-semantic-review.md).
Operator acceptance remains pending; these findings are not an automatic
model selection or winner declaration.

The local count correction is documented in `prompt-refinement.md`: the
detailed v2 case list contains 17 distinct cases; an older final sentence said
15 and omitted `mix-03` and `perf-long`. The underlying local output files are
preserved and unchanged.


## Observed provider execution — 2026-10-22

The original `urllib` transport sent `Content-Type: application/json` and
`Authorization: Bearer …`; its default user agent was `Python-urllib/...`. The
JSON request contained the fixed model, prompt v2 messages, case data, and
settings in the table above. The operator-reported successful curl call used
the same credential and endpoint, but its exact invocation and captured
headers/body are not available here, so a byte-for-byte curl comparison is not
established. A live `requests` probe using the runner's payload returned HTTP
200, and the updated runner then completed a one-case probe with HTTP 200. The
Python client user agent changed to `python-requests/...`; the runner's JSON
payload and explicit Content-Type and Authorization headers stayed unchanged.
This supports HTTP-client behavior as the likely cause of the earlier
Cloudflare 1010, but does not prove Cloudflare's internal rule.

| Candidate | Run directory | Cases | Attempts | Retries | Failed |
|---|---|---:|---:|---:|---:|
| `qwen/qwen3.8-27b`, reasoning none | `private/m05a/groq-qwen3.8-27b-v2-requests-20261022/` | 46/46 | 50 | 4 | 0 |
| `openai/gpt-oss-120b`, reasoning low | `private/m05a/groq-gpt-oss-120b-v2-requests-20261022/` | 46/46 | 46 | 0 | 0 |

**OBSERVED:** Both summaries and per-case results are under ignored `private/`
paths with mode `0600`; their run directories use restrictive permissions.
The credential file `private/groq_api` was tightened from mode `0644` to
`0600` before reading it. The key was read only into Python memory and was not
placed in command arguments, logs or result artifacts. The earlier failed
`urllib` run directory and all pre-existing benchmark evidence were preserved.

**INTERPRETATION:** `requests` resolved the observed transport failure in this
environment. The four Qwen 429 responses recovered under existing retry policy;
this does not establish account-specific quota or billing. Semantic outcomes
and limits are recorded in [groq-semantic-review.md](groq-semantic-review.md).

### Completed-run telemetry — private summaries and result rows

| Candidate | Successful | Requests / retries | First successful request | Subsequent median | Per-case wall time min / median / max | Input / output / total tokens |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.8 27B | 46/46 | 50 / 4 | 0.525 s | 0.277 s | 0.198 / 0.279 / 1.940 s | 21,102 / 2,011 / 23,113 |
| GPT-OSS 120B | 46/46 | 46 / 0 | 0.355 s | 0.559 s | 0.282 / 0.557 / 2.270 s | 23,405 / 5,603 / 29,008 |

**OBSERVED:** Qwen retries occurred on `u-ru-complaint`, `u-ru-uncertain`,
`u-en-criticism` and `u-translate-identifiers`, one retry each; all were
HTTP 429 rate-limit responses and later succeeded. GPT-OSS had no retries.
Saved headers reported request limit 1,000 and token limit 8,000 for both
runs; Qwen remaining request quota moved from 996 on its first result to 951
on its last, and GPT-OSS from 999 to 954. These are per-response snapshots,
not current account quota or the published plan table. Inter-request delay was
2.1 seconds; total run elapsed time includes pacing and retry waits in addition
to per-request wall times.

**INTERPRETATION:** GPT-OSS used about 25.5% more total tokens and its median
network-inclusive request wall time was about twice Qwen's in this sample.
Qwen's four recoverable rate limits increased attempts by four. These
measurements do not establish a general latency or cost ranking. Provider
processing time is NOT ESTABLISHED because no processing-time values were
saved in result rows. Cost remains NOT ESTABLISHED without account billing data.

## Operational concerns and operator checklist

- [ ] Keep the key available through the private secret file; never paste it
  into chat, Git, shell arguments or logs.
- [x] Review all 46 source/output/options per completed model and classify
  confirmed critical failures, minor issues and judgment cases in
  [the semantic review](groq-semantic-review.md). Operator decision remains
  pending.
- [ ] Confirm actual plan limits, remaining quota, rate-limit headers and
  billing/cost observations in the Groq account; no pricing inference is made
  from request counts alone.
- [x] Compare source-language preservation, negation, uncertainty, speaker
  perspective, criticism, translation, identifiers, commitments and formatting
  against local Qwen3.5 evidence. See [semantic review](groq-semantic-review.md).
- [ ] Resolve judgment cases, especially payment semantics, translated
  deadline wording, mixed-language `klart`, and strict identifier fidelity.
- [ ] Decide whether either cloud model merits operator acceptance for a
  separately proposed next step. No acceptance is implied by fluency, API
  success or this technical evaluation.
- [ ] Keep M05A open pending operator validation and explicit closeout. Do not
  start M05B or commit from this evaluation.

Credential rotation/revocation is controlled by the operator in Groq. The
runner never retains the key; private synthetic results can be removed after
review when no longer needed. No local service health check is required after
cloud inference because the cloud runner does not contact or reconfigure local
services.
