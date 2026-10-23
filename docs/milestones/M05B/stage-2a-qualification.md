# M05B Stage 2A — Local Qwen qualification

Status: **The resumed bounded sequential 4K/8K comparison completed on
2026-10-22 after the operator accepted the harness root-cause analysis and
offline regression evidence. All 18 responses and telemetry were saved in
private evidence. Both contexts completed all nine requests, naturally
expired, and recovered GPU memory. Seven outputs at each context failed one or
more lexical quality invariants; these are model-quality findings, not harness
failures. The operator accepts retaining local Qwen as a user-reviewed
transformation candidate despite these limitations. This is not a lexical
quality pass or a guarantee of meaning preservation or multilingual quality.**

## Scope and test envelope

Stage 2A is limited to one sequential comparison of the installed
`qwen3.5:9b-q4_K_M` model at `num_ctx=4096` and `num_ctx=8192`, using the
prepared nine-case corpus and M05A generation settings. The existing
`scripts/m05a_eval.py` runner is suitable for offline validation but not live
execution because it sends an explicit unload request. It does not authorize
deployment, Gateway configuration changes, cloud inference, STT/TTS requests,
simultaneous stress testing, model downloads, shared Ollama configuration
changes, or M05B closeout.

The run envelope is fixed before inference:

- One 4K run followed by one 8K run; no retries, repeats or reverse-order run.
- Nine identical private synthetic cases per context: short, medium and long
dictation in English, Swedish and Russian. The same prompt v2 and generation
settings are used in both runs (`temperature=0`, `top_p=1`, seed `20261022`,
`num_batch=128`, `num_thread=8`, `num_predict=512`, `think=false`).
- Maximum 18 generation requests total, sequentially, with the runner's
300-second per-request timeout. A failed case stops that context run.
- Run artifacts, inputs and outputs stay in new mode-0700 directories under
`private/m05a/`; do not read or overwrite prior run artifacts for this test.
- Do not use the existing M05A runner for live calls without changing its
  cleanup behavior: it sends `keep_alive=0`. Stage 2A sends no unload request
  and does not use an empty generation request. Each bounded generation
  request must specify `keep_alive: "60s"`; this asks Ollama to expire its
  residency naturally after one minute of idleness. This is finite, but is not
  evidence that another client is idle or that expiration occurred.
- Immediately before each context run, record timestamp, exact model identity,
  full `/api/ps` residency, GPU memory/utilization/processes, and Gateway/STT/TTS
  health/restart counts. Do not require an empty server and never remove or
  alter a model already resident for another client. If the tested model is
  already resident, its warm/cold state cannot be called cold.
- Run 4K first, then 8K only after the 4K run and its post-run observation
  window are complete. Never overlap them. Use nine requests per context,
  one at a time, with the existing synthetic corpus and generation settings;
  total cap remains 18 requests and each request has a 300-second timeout.
- Sample GPU memory/utilization and `/api/ps` at least once per second during
  each run. Record baseline, peak and post-run GPU memory and model residency.
  Capture Ollama request logs so unexpected generation requests can mark the
  run contaminated. If other use cannot be distinguished from this run, do not
  claim isolation; abort when GPU activity or memory cannot be attributed
  safely. An observed extra client request contaminates the measurement.
- After the final request, observe without issuing an unload: record immediate
  post-run residency and GPU state, then poll at 10-second intervals for up to
  120 seconds to observe natural idle expiration. Record expiration only if
  `/api/ps` shows the model absent. Record GPU recovery only if GPU memory
  returns to within 128 MiB of the pre-run baseline for three consecutive
  samples. These are separate observations: inference success does not prove
  residency, natural expiration, or memory recovery.
- Cold-start latency and unload behavior are unmeasurable in this shared,
  non-destructive protocol. Do not use `keep_alive: 0` unless exclusive use of
  the tested model has been established; Stage 2A does not establish it.

## Pre-run baseline — 2026-10-22

**OBSERVED:** repository HEAD is Stage 1 commit
`0066c9a39fb09725137781cde114f912402033b4`; the worktree was clean at
inspection. Ollama container `ollama/ollama` is running, version `0.33.1`.
`GET /api/ps` returned `{"models":[]}`. The requested model is installed and
`/api/tags` reports digest
`56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`, size
6,550,825,550 bytes. No model download is needed.

**OBSERVED:** at 2026-10-22 16:49:42 UTC, `nvidia-smi` reported a Quadro RTX
5000, driver `580.178.04`, total 15,360 MiB, used 2,216 MiB, free 12,694 MiB,
GPU utilization 0%, temperature 35 C. A host Python process used 2,212 MiB.
Its cgroup mapped to the running `speech-platform-stt-1` container; that
container was healthy. Gateway and TTS were also healthy. At 16:50:57 UTC all
three product containers had restart count zero and health `healthy`; Gateway
`/healthz` returned `alive` and `/readyz` returned `ready`. The separate
M01E, Dify and other containers were observed running and are out of scope.

**INTERPRETATION:** the GPU has sufficient initial free memory for a bounded
single Qwen request at either context. The resident STT process means this is
not an isolated-GPU measurement. Do not infer simultaneous inference capacity
or shared-GPU coexistence from this qualification.

**SAFETY GATE — NOT SATISFIED:** the prior quiescence requirement is replaced
by telemetry-based contamination detection, but the current Ollama logs expose
only a network address, not a client identity or model-request owner. `/api/ps`
reports resident models and placement but not which client is using them. GPU
process accounting attributes 2,212 MiB to the STT process and does not split
Ollama usage by client. Therefore a concurrent request from a client sharing
the same address cannot currently be distinguished reliably. Do not run until
request attribution is available or the operator provides an approved
observation mechanism; this is an attribution limit, not a requirement for
exclusive ownership of the entire Ollama server.

**OBSERVED — revised preflight, 2026-10-22 16:56:38 UTC:** Ollama `/api/ps`
returned `{"models":[]}`. The Quadro RTX 5000 reported 15,360 MiB total,
2,216 MiB used, 12,694 MiB free, 0% utilization and 34 C; compute process
accounting attributed 2,212 MiB to the host Python process mapped to STT.
Gateway `/healthz` and `/readyz` returned `alive` and `ready`; Gateway, STT,
TTS and Ollama were running with zero restarts, and the three product workers
were healthy. The recent Ollama logs showed only the local bridge address for
read-only API checks. No generation request was sent. The server being idle at
this snapshot does not establish client exclusivity or future attribution.

## Abort conditions

Before each context, capture the model-residency and GPU baseline described
above; repeat the same capture after the run and throughout the natural expiry
window. Abort the run on any of these conditions:

- Gateway loses `/healthz` or `/readyz`, STT/TTS becomes unhealthy, or any
  product worker restart count changes.
- GPU free memory falls below 1,024 MiB, GPU reports an error, or host reports
  OOM/driver instability.
- Any inference exceeds its 300-second timeout, emits an API error, or does
  not finish; do not retry.
- Unexpected GPU process/resource use appears, another client request is
  observed, residency changes unexpectedly, or attribution becomes ambiguous.
- GPU utilization, memory pressure, or worker health degrades beyond the
  baseline limits. Do not attempt recovery by unloading models or restarting
  Ollama; preserve observations and stop.

If an abort occurs, preserve private evidence and do not continue to the next
context. Do not attempt recovery by restarting services or unloading another
client's model.

## Validation and live execution status

The nine private case IDs are `en-short`, `en-medium`, `en-long`, `sv-short`,
`sv-medium`, `sv-long`, `ru-short`, `ru-medium`, and `ru-long`. The case file is
synthetic, private and already passes the M05A runner schema with prompt v2.
The runner reported 9 valid cases and no runtime contact. The offline
validation command is listed below. No live command is currently provided
because the existing runner always unloads and a no-unload harness with the
required attribution monitoring is not available. Before any separately
reviewed execution, that harness must use the exact same corpus for both
contexts, send the request settings above, capture per-case completion and
token counts privately, and implement continuous residency/GPU/log sampling
and abort rules. Keep outputs private and inspect locally for successful
completion, API errors, required invariants, completeness and truncation; do
not copy generated text into tracked files.

## Results — partial 4K execution stopped on harness failure

### Partial 4K request — 2026-10-22 17:19 UTC

**OBSERVED:** Before the request, `/api/ps` was empty and the installed model
digest matched `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`.
The GPU baseline was 2,216 MiB used / 12,694 MiB free (15,360 MiB total).
Gateway, STT and TTS were healthy with restart count zero. The private harness
sent one 4K request for `en-short` with the prescribed prompt and generation
settings and `keep_alive: "60s"`. Ollama logged HTTP 200 in 10.219493 seconds;
backend timing logs recorded 452 prompt tokens, 24 completion tokens, 456 ms
prompt evaluation and 568 ms generation, with no truncation. The response
arrived in the harness, but its post-response invariant-check import failed
with `ModuleNotFoundError: No module named 'scripts'` before the response,
token counts or per-request record were saved. Consequently output quality,
Ollama `load_duration`, and client-measured total latency are not established.
This request was not retried.

**OBSERVED:** one-second GPU sampling recorded a peak of 8,508 MiB used / 6,402
MiB free, a 6,292 MiB increase over baseline. The expected Qwen digest was
resident at context 4,096 immediately afterward. No second generation POST
was observed in Ollama logs during this partial run; the shared bridge address
does not establish client identity. No concurrent generation activity was
observed, so this single request is not marked contaminated; exhaustive client
attribution remains NOT ESTABLISHED.

**OBSERVED:** Ollama reported natural expiry at approximately 17:20:49 UTC.
At 17:20:52 UTC `/api/ps` showed no model and GPU use was back at 2,216 MiB /
12,694 MiB free. Three consecutive samples through 17:20:54 confirmed the
model remained absent and memory remained at baseline. No unload request,
restart or configuration change was sent.

**OBSERVED:** no product health degradation or restart was detected. The
preflight validated all nine synthetic cases in English, Swedish and Russian.
The partial run used only `en-short`; the other eight cases were not sent.
The existing M05A runner was not used for live requests because its cleanup
path sends an unload request.

**INTERPRETATION:** the single response completed at 4K, stayed above the
1,024 MiB free-memory abort floor, expired naturally and released sampled GPU
memory to baseline. This does not establish output quality, cold-load latency,
the 4K nine-case envelope, or comparative 4K/8K behavior. The independent
8K smoke recorded below in the earlier history used different generation
parameters and is not a comparison result.

**NOT ESTABLISHED:** the harness failure ended the 4K run before the nine-case
set completed. Per the bounded procedure, no retry or continuation was made;
the 8K comparison run therefore did not start. Stage 2A remains incomplete.

**OBSERVED — execution evidence:** the private run directory is
`private/m05b/stage2a-20261022/` (mode 0700); inputs/outputs were not copied to
tracked files. The runner's post-response failure is preserved in
`context-4096-summary.json`, sampled telemetry in `samples.jsonl`, and natural
recovery polling in `recovery-observation.json`. These files are local private
evidence, not committed.

### Authorized one-request 8K smoke — 2026-10-22

**OBSERVED:** Before inference, Gateway `/healthz` and `/readyz` returned
`alive` and `ready`; STT and TTS `/healthz` returned `alive`; Gateway, STT,
TTS and Ollama were running with zero restarts. Ollama `/api/ps` was empty.
`/api/tags` confirmed `qwen3.5:9b-q4_K_M`, digest
`56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`.
The Quadro RTX 5000 baseline was 2,216 MiB used, 12,694 MiB free and 0%
utilization. GPU process accounting showed the existing 2,212 MiB STT process;
no other compute process was visible.

**OBSERVED:** Exactly one direct Ollama `/api/generate` POST was sent with
`num_ctx=8192`, `keep_alive="60s"`, `num_predict=64`, temperature 0 and
`think=false`. The short synthetic instruction asked for a concise rewrite
of a meeting rescheduling sentence. Ollama returned HTTP 200 with a completed
rewrite, 40 prompt tokens and 14 generated tokens. Client-observed latency was
10.607 seconds; Ollama's request log reported 10.201 seconds, including a
9.671-second model load. No retry or additional inference request was made.

**OBSERVED:** One-second GPU/residency sampling during inference observed
8,802 MiB used / 6,108 MiB free as the highest sampled use. Ollama reported
the exact model digest resident with `context_length=8192` and
`size_vram=5,828,646,010` bytes. Its expiry was scheduled for 17:02:12 UTC.
At the first 10-second poll at that time, `/api/ps` showed no models and GPU
use had returned to 2,216 MiB used / 12,694 MiB free. The model remained absent
and memory stayed at baseline for the rest of the 120-second observation
window, including at least three consecutive baseline samples. No unload,
restart or shared Ollama configuration change was issued.

**OBSERVED:** After the observation window, Gateway `/healthz` and `/readyz`
returned `alive` and `ready`, STT/TTS `/healthz` returned `alive`, all three
product containers remained healthy with restart count zero, `/api/ps` was
empty, and GPU use was back at 2,216 MiB / 12,694 MiB free / 0% utilization.
Ollama logs showed one `/api/generate` POST in the run interval and the
monitoring GET requests.

**INTERPRETATION:** This one request completed successfully at 8K, the sampled
GPU headroom remained above the documented 1,024 MiB abort floor, and natural
residency expiration coincided with GPU memory returning to baseline. This is
not a peak guarantee beyond the one-second sampling interval and does not
establish coexistence capacity or production suitability.

**NOT ESTABLISHED at the time of this earlier smoke:** Ollama logs identify
callers by bridge address rather than client identity, and GPU process
accounting groups use by process. No other generation request was visible in
the sampled Ollama logs, but complete attribution of every shared-server
client during that interval cannot be established. At that time, no 4K run,
nine-case corpus comparison, benchmark, Stage 2B coexistence test, or Gateway
deployment had been performed. The later partial 4K execution is recorded
above; the 8K smoke does not substitute for the comparison.

The table below distinguishes this partial comparison attempt from the earlier
one-request 8K smoke. The 8K smoke used `num_predict=64` and a different prompt,
so its timing and GPU readings are reference-only and cannot be compared with
the 4K corpus request.

**OBSERVED:** the private nine-case synthetic input file was prepared with
mode `0600` and validated by the existing runner (`--validate`); it contains
short/medium/long examples in English, Swedish and Russian. All source text
lengths fit the M05B 4K serialized-source ceiling of 867 UTF-8 bytes; the
longest is 843 bytes. The same file is ready for both contexts. The offline
validation command is:

```sh
.venv/bin/python scripts/m05a_eval.py --validate \
  --case-file private/m05a/stage2a-cases.jsonl \
  --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2
```

The existing evaluation runner always unloads after execution and was not used
for live Stage 2A requests. The private harness sent one request and stopped
after its post-response failure; it did not unload the model.

**NOT ESTABLISHED for the full comparison:** the nine-case corpus was not
completed at either context; only `en-short` was sent at 4K and no comparison
request was sent at 8K. Therefore nine-case VRAM peaks, latency distributions,
prompt-token maxima, output completeness across the corpus, or comparative
4K/8K results were not measured. Cold-start latency and explicit unload
behavior are unmeasurable under this safe shared-server procedure. No STT/TTS
inference was run.

| Measure | 4K | 8K | Difference / interpretation |
| --- | --- | --- | --- |
| Baseline GPU used / free (MiB) | 2,216 / 12,694 | NOT RUN | 8K comparison not run |
| Sampled peak used / minimum free (MiB) | 8,508 / 6,402 | NOT RUN | 4K partial delta +6,292 MiB; not comparable |
| Load latency | NOT CAPTURED | NOT RUN | NOT ESTABLISHED |
| Request latency | Ollama server log 10.219 s | NOT RUN | Client latency not saved |
| Ollama total-duration field | NOT CAPTURED | NOT RUN | Not interchangeable with server request latency |
| Generation latency | 0.568 s backend eval | NOT RUN | One 4K request only |
| Prompt token count | 452 (`en-short`) | NOT RUN | Not a nine-case maximum |
| Completed outputs | 1 API response completed; response text not saved | 0 | Quality review unavailable |
| Output quality / invariant review | NOT ESTABLISHED | NOT RUN | Harness failed after response |
| Model residency immediately after request | Qwen resident, context 4,096 | NOT RUN | 4K observed only |
| Natural idle expiry | Observed ~17:20:49 UTC | NOT RUN | 4K only |
| GPU memory returned to baseline for 3 samples | Yes: 2,216 / 12,694 MiB at 17:20:52–54 UTC | NOT RUN | 4K only |
| Gateway/STT/TTS health and restart deltas | Healthy; zero restart delta | NOT RUN | No speech inference |
| Contamination | No extra generation POST observed; shared-client attribution not exhaustive | NOT RUN | 4K request not marked contaminated |

Do not approve 8K as a production default from these results. Stage 2A is
incomplete due to the harness failure; the operator should review the partial
evidence before any further execution. 8K remains a proposed example setting
only; operational suitability is NOT ESTABLISHED. Stage 2B remains separate
and unauthorized.

## Offline harness repair after the partial attempt — 2026-10-22

**OBSERVED:** inspection of the private runner identified the exact failure in
`post_generate()`: after receiving and decoding the HTTP 200 body, it used
`__import__('scripts.m05a_eval', ...)` to compute lexical flags. When the script
was launched by its private path, the repository root was absent from
`sys.path`; this raised `ModuleNotFoundError: No module named 'scripts'`.
The call happened before a result record was returned or written. The saved
context summary confirms this exception and an empty results array. The HTTP
body was not retained, so no conclusion about its text or lexical invariants
can be made.

**INTERPRETATION:** this observed failure was a benchmark-harness defect. It
does not establish that the provider returned invalid text. The runner has
been repaired for a separately reviewed future execution: it explicitly adds
the repository root for imports, reads at most 1 MiB plus one sentinel byte,
saves the response body to an exclusive mode-0600 evidence file before JSON,
completion, or text-quality checks, and writes each operational result row
before deciding whether a failed check stops the run. A response over the
limit preserves only the bounded prefix and reports that quality was not
evaluated. Per-case records keep client latency, server load/total/prompt/eval
durations, prompt/completion token counts and completion status separate from
quality status. Diagnostics report the failed invariant index and expected
length without copying response text or invariant contents.

**OBSERVED — offline verification:** `scripts/test_m05b_stage2a.py` covers the
reproduced `ModuleNotFoundError` during quality validation, preservation of
the received response, separation of completion/quality status and timing /
token fields, missing-invariant diagnostics, incomplete responses and the
response-size limit. All four tests passed. The nine-case private corpus
validated successfully with prompt v2; the command made no runtime contact.
The modified private runner passed Python bytecode compilation. Formatting
checks passed for the tracked helper and regression test. A formatting attempt
on the pre-existing compact private runner was rejected by Ruff's parser at
its existing one-line compound-statement syntax; the runner itself compiles.

**NOT ESTABLISHED:** the lost 4K response cannot be recovered from the
available evidence, so its output quality remains unknown. No inference was
repeated, and the comparison was not resumed. This repair does not authorize
any further live request, unload, deployment, cloud call or stress test.
This repair was followed by a resumed Stage 2A comparison, recorded below.

## Resumed 4K/8K comparison — 2026-10-22 18:37 UTC

**OBSERVED — preflight and verification:** the operator accepted the harness
root-cause analysis and offline regression evidence and requested resumption.
Ruff lint and formatting checks passed for the private runner and tracked
response helper. The helper and invariant checker imported successfully with
the runner's actual `sys.path` setup. Four response-helper regression tests
passed, including save-before-validation and invariant failure classification.
The nine-case synthetic corpus validated without runtime contact. The runner
was launched from the repository root with its private script path; it wrote
to the new mode-0700 directory
`private/m05b/stage2a-20261022/resume-20261022T183731Z/`, preserving the
earlier failed attempt. Each response body was saved with mode 0600 before
parsing or quality validation.

**OBSERVED — execution:** Ollama 0.33.1 served the installed model with digest
`56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`. The run
sent exactly 18 sequential generation requests: the same nine English,
Swedish and Russian synthetic cases at 4K, followed by those cases at 8K. All
requests used prompt v2, the specified deterministic generation settings and
`keep_alive: "60s"`. The runner exited 0 with nine completed cases per
context, no infrastructure failure, no monitor error and no unexpected
generation log line. It issued no unload request. The independent result
record classifies text invariant failures as `quality_status: failed` while
keeping completion successful; those findings did not stop either corpus.

**OBSERVED — latency and tokens:**

| Measure | 4K | 8K |
| --- | ---: | ---: |
| Client latency min / median / max | 0.844 / 2.402 / 9.696 s | 0.837 / 2.399 / 9.544 s |
| Ollama total duration min / median / max | 0.829 / 2.385 / 9.680 s | 0.820 / 2.381 / 9.521 s |
| Load duration min / median / max | 0.004 / 0.008 / 8.630 s | 0.007 / 0.008 / 8.498 s |
| Prompt evaluation min / median / max | 0.220 / 0.229 / 0.466 s | 0.221 / 0.230 / 0.438 s |
| Completion evaluation min / median / max | 0.559 / 1.812 / 5.847 s | 0.562 / 1.822 / 5.863 s |
| Prompt token min–max | 452–675 | 452–675 |
| Completion token min–max | 24–250 | 24–250 |

The first request in each context included an approximately 8.5-second model
load; the remaining requests reported approximately 4–9 ms load duration.
These are observed request timings, not a general cold-start guarantee.

**OBSERVED — GPU, residency and health:** the baseline was 2,216 MiB used /
12,694 MiB free on a 15,360 MiB GPU. One-second samples recorded peak use of
8,510 MiB (6,400 MiB free) at 4K and 8,640 MiB (6,270 MiB free) at 8K. The
tested Qwen digest was the only resident Ollama model during each phase; each
context recorded nine distinct generation log lines and was not marked
contaminated. No monitor error or abort condition occurred. After each phase,
the model disappeared naturally and GPU memory returned within 128 MiB of
baseline for at least three samples. At 18:43:32 UTC `/api/ps` was empty, GPU
use was 2,216 MiB with 12,694 MiB free, Gateway health/readiness were alive and
ready, and Gateway/STT/TTS were healthy with zero restart counts.

**OBSERVED — output review:** all 18 raw responses reported `done: true` and
`done_reason: stop`; no truncation or missing completion was observed. At both
contexts, 2/9 cases passed lexical invariants and 7/9 failed, with 13 missing
invariants in total. The same output text and invariant outcome occurred at
4K and 8K. Private manual review found the Swedish short rewrite was in English
and included an erroneous term; the Russian short rewrite had awkward ordering
and omitted required details. The medium and long outputs were generally
coherent and retained the main status and instructions; exact lexical checks
also flagged dates rendered in natural-language formats. Case-level outcomes
and review notes, without generated text, are in the private
`output-review.json` and `case-results.jsonl`.

**INTERPRETATION:** in this corpus, moving from 4K to 8K did not change prompt
token counts, measured latency distribution, invariant outcomes or generated
text. Sampled peak GPU use increased by 130 MiB at 8K. Several quality failures
are substantive short-case defects; date-format flags include lexical
false-positive risk. This small synthetic run does not establish broader
multilingual quality, simultaneous speech/LLM coexistence, or production
suitability.

**NOT ESTABLISHED:** exhaustive identity attribution for all clients sharing
the local bridge address, GPU peaks between one-second samples, broad
tokenizer/template limits, simultaneous workload capacity, generalized
cold-start behavior, or production readiness. No speech inference, deployment,
cloud request, restart, unload or shared Ollama configuration change occurred.
**OPERATOR DECISION — 2026-10-22:** retain local Qwen for transformations only
when a user reviews the generated text. The observed 7/9 lexical-invariant
failures at each context remain failed results. The Swedish short output was in
English and included an erroneous term; the Russian short output had awkward
ordering and omitted required details. Medium and long outputs were generally
coherent, while date-format flags include lexical-only false-positive risk.
This decision accepts the model as a supervised candidate, not its failed
invariants as passing, and does not establish production readiness or guarantee
perfect meaning preservation, facts, or multilingual quality. Stage 2A's bounded result was accepted by the operator with these limitations
on 2026-10-22; M05B closeout remains pending.
