# M05A verification record

Status: **Local and bounded technical evaluation complete; operator validation and M05A closeout recorded 2026-10-22.**

## Environment baseline — 2026-10-22

- **OBSERVED:** Repository `/home/master/speech-platform`, branch `main`,
  working tree clean before M05A edits. Target is the active shared `llm`
  Docker host, based on the live Speech Platform, Ollama and Dify containers.
- **OBSERVED:** `docker compose --env-file .env -f compose.yaml ps --all`
  reported Gateway, STT and TTS running/healthy. `docker compose ls --all`
  showed existing Speech Platform, Ollama, Dify, M01E and STT smoke projects;
  none were restarted or modified for baseline collection.
- **OBSERVED:** GPU is NVIDIA Quadro RTX 5000, driver 580.178.04, CUDA 13.0,
  15,360 MiB physical capacity. `nvidia-smi` reported 2,216 MiB used at
  0% utilization, attributed to one Python process (2,212 MiB), consistent
  with STT residency. TTS was idle/unloaded.
- **OBSERVED:** `free -h`: 61 GiB total, 5.2 GiB used, 20 GiB free, 56 GiB
  available, 3.8 GiB swap with 3.0 GiB used. `df -hT . /var/lib/docker`:
  492 GiB filesystem, 296 GiB used, 176 GiB available.
- **OBSERVED:** Ollama container `ollama`, image `ollama/ollama`, running since
  2026-10-17T09:04:51Z, zero restarts, image version 0.33.1, model volume
  `/var/lib/docker/volumes/ollama/_data`, host port 11434 published on all
  interfaces. Its model store contained no exact Qwen3.5 9B or Gemma 3 12B
  candidate. Existing models are listed in the command output of the original
  environment inspection and are to be preserved.
- **OBSERVED:** STT `/readyz` and TTS `/healthz` returned HTTP 200 when probed
  inside their containers. Gateway `/health` returned 404; its Compose health
  check is `/readyz`, so `/health` was not a valid endpoint probe. This did
  not affect service health.
- **OBSERVED:** `git status --short --branch` showed `## main` with no changes
  at initial inspection. `ollama` was absent from the host PATH; the active
  runtime is the existing container, not a host installation.
- **OBSERVED (post-download):** Disk availability was 162 GiB after pulling
  both candidates (baseline 176 GiB). Both models remain installed but are
  unloaded; only their tags were added to the existing model store.
- **INTERPRETATION:** Catalog sizes suggest the candidates may fit in disk and
  potentially GPU memory at 4K context, but available VRAM after STT is only
  about 12.4 GiB by `nvidia-smi` free-memory baseline, before runtime/KV/cache
  needs. This was a reason for sequential bounded measurement, not a fit
  guarantee.

## Candidate identities and licenses — 2026-10-22

- **OBSERVED:** Existing Ollama runtime was v0.33.1. The installed Qwen tag is
  `qwen3.5:9b-q4_K_M`; full Ollama digest
  `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`,
  6,550,825,550 bytes, architecture `qwen35`, 9.0B parameters, Q4_K_M,
  catalog context 262,144. `/api/show` reports Apache-2.0.
- **OBSERVED:** The installed Gemma tag is `gemma3:12b-it-q4_K_M`; full
  Ollama digest
  `b92b218582c521ba287f38f1d6057dcd3c6cbff036f13cac97b5d861f5e58ec3`,
  8,164,039,732 bytes, family `gemma3`, 11.8B parameters, Q4_K_M, model
  context 131,072. Gemma 3 uses Google's Gemma Terms of Use, not Apache 2.0.
- **OBSERVED:** Both exact tags were absent at baseline and added through
  `docker exec ollama ollama pull <exact-tag>`. Both pull commands exited 0
  and Ollama verified the downloaded SHA-256 layers. No runtime installation,
  image update, service restart or model-store deletion was performed.
- **INTERPRETATION:** These tags loaded successfully with the installed
  runtime; this establishes compatibility for these exact tags on this host.
  It does not establish compatibility with other Ollama versions or formats.

## Prompt, corpus and generation settings

- **OBSERVED:** `cases.jsonl` contains 39 valid synthetic cases spanning
  English, Swedish, Russian and mixed-language inputs; all three formats;
  raw/written/polite/diplomatic modes; English/Swedish/Russian targets; short,
  medium and long inputs; technical identifiers, names, numbers, dates,
  negation, uncertainty, complaints and commitments.
- **OBSERVED:** Prompt v1 was used with one `/api/generate` call per case.
  Options were `num_ctx=4096`, `num_predict=512`, `temperature=0`, `top_p=1`,
  `seed=20261022`, `num_batch=128`, `num_thread=8`, `think=false`, one request
  at a time and `keep_alive=10m`; each run ended with `keep_alive=0`.
- **OBSERVED:** Raw without translation was excluded from LLM execution,
  consistent with the planned exact-passthrough behavior. It is not a future
  production implementation test.

## Actual model runs and resource evidence

Full runs used the same 39 cases in the same order. Detailed inputs, outputs,
per-request times and raw samples are in ignored `private/m05a/` directories.

| Measurement | Qwen3.5 9B Q4_K_M | Gemma 3 12B IT Q4_K_M |
|---|---:|---:|
| Full run | 39/39; 62.7 s | 39/39; 91.5 s |
| True first-use preflight, total / first-fragment latency | 166.5 s / 166.1 s | 41.2 s / 40.7 s |
| Preflight Ollama model-load / prompt-evaluation / generation | 92.0 / 74.1 / 0.45 s | 22.7 / 18.0 / 0.52 s |
| Subsequent full-run first load | 9.26 s | 11.39 s |
| Warm total-latency median (38 requests) | 1.02 s | 1.29 s |
| Warm first-fragment median | 0.238 s | 0.320 s |
| Warm total-latency range (includes long case) | 0.67–9.52 s | 0.89–16.45 s |
| Median generation throughput | 42.1 tokens/s | 36.2 tokens/s |
| Short / medium / long median latency | 0.93 / 1.57 / 9.52 s | 1.14 / 2.02 / 9.42 s |
| `/api/ps` GPU model size at 4K context | 5,517,187,481 bytes | 7,871,670,517 bytes |
| Peak total GPU use / minimum free, 39-case run | 8,510 / 6,400 MiB | 10,946 / 3,964 MiB |
| Peak Ollama container RAM, 39-case run | 1,947,767,668 bytes | 2,179,695,902 bytes |
| CPU offload | none; 100% GPU | none; 100% GPU |
| API model list after explicit unload | empty | empty |

- **OBSERVED (first-use preflights):** The Qwen preflight used the `perf-short`
  case and measured 166.53 s total, 166.07 s to first response fragment,
  91.96 s model load, 74.08 s prompt evaluation and 42.45 output tokens/s.
  Gemma's same case measured 41.23 s total, 40.70 s to first fragment,
  22.71 s model load, 17.97 s prompt evaluation and 36.74 output tokens/s.
  Each was a single cold first-use request; the 39-case runs provide the
  separate warm multi-request evidence.
- **OBSERVED (supplementary RAM):** Three short/medium/long cases were run per
  model with one-second host `/proc/meminfo` sampling. Qwen minimum
  `MemAvailable` was 59,862,208,512 bytes (about 55.8 GiB); Gemma minimum was
  59,773,616,128 bytes (about 55.7 GiB). Sampled host peak used RAM was about
  6.17 GB and 6.26 GB respectively. These are brief samples, not a sustained
  system-load maximum.
- **OBSERVED:** All six candidate runs (two first-use preflights, two full
  corpus runs, and two supplementary resource runs) completed without request
  errors. Each runner recorded successful explicit unload and an empty
  `/api/ps` model list afterward. No OOM was observed or deliberately
  provoked.
- **INTERPRETATION:** Local inference is technically feasible at 4K context
  for these tags with full GPU offload and serialized requests. Gemma's 39-case
  run used about 2.4 GiB more peak GPU memory than Qwen's and left at least
  3,964 MiB free in the observed samples. Warm latency is low for the
  synthetic set; it does not establish sustained concurrency or production
  throughput.
- **NOT ESTABLISHED:** Concurrent LLM/TTS inference was not tested. During
  Gemma inference the measured free GPU memory fell to 3,964 MiB; adding the
  historically observed combined STT/TTS use would not be a safe controlled
  test on this GPU. No scheduler or production resource policy is inferred.

## Quality outcome

- **OBSERVED:** Lexical invariant checker flagged 28/39 Qwen and 26/39 Gemma
  full-run cases. Many flags reflect legitimate translated date/number
  spelling; they are not semantic failure rates.
- **INTERPRETATION:** Case-by-case review found critical preservation and
  language-retention failures in both candidates. See
  [quality comparison](quality-comparison.md). Neither candidate is
  recommended for M05B at this time.

## Post-run service state

- **OBSERVED:** After runs, `nvidia-smi` returned to 2,216 MiB used, 12,694 MiB
  free and 0% GPU utilization; Ollama `/api/ps` was empty. STT `/readyz` and
  TTS `/healthz` returned HTTP 200. Gateway, STT and TTS retained their
  pre-run container IDs, image IDs, start times and zero restart counts; all
  remained healthy with `OOMKilled=false`. Ollama retained its original
  container ID/image/start time and zero restarts. Existing Ollama model tags
  remained present alongside the two new candidates.
- **OBSERVED:** The first combined `docker inspect` formatting probe expected
  a health object on Ollama and returned a template error because that
  container has no Docker healthcheck. A corrected read-only inspection
  verified Ollama's running state and unchanged identity; this was not a
  service failure.
- **INTERPRETATION:** No STT/TTS service impact was observed in readiness,
  health, identity, restart or OOM evidence. This does not prove zero latency
  impact to other users of the shared Ollama service during the runs.

## Verification commands

- **OBSERVED PASS:**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_eval.py --validate`
  validated 39 cases and prompt v1 without contacting Ollama.
- **OBSERVED PASS:** Focused tests (10 tests):
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_m05a_eval -v`
  (final count pending after host-RAM sampler tests).
- **OBSERVED PASS:** `.venv/bin/python -m ruff check scripts/m05a_eval.py scripts/test_m05a_eval.py`
  and Ruff format checks for the changed runner/test files.
- **OBSERVED PASS:** `docker compose --env-file .env -f compose.yaml config --quiet`.
- **OBSERVED PASS (final run):** `make verify PYTHON=.venv/bin/python` exited
  0 after the final runner and test changes. It included `go test -race ./...`,
  configuration/Compose/release checks, repository script tests, 64 STT tests,
  build, syntax, governance and lock checks.
- **OBSERVED PASS (final review):** `git diff --check` exited 0. A trailing
  whitespace search returned no matches (its `rg` exit status was 1, meaning
  no matching lines).


## Prompt v2 retest verification — 2026-10-22

- **OBSERVED PASS:** Original corpus and prompt v2 validation:
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_eval.py --validate --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2`
  (39 valid cases; no runtime contacted).
- **OBSERVED PASS:** Unseen corpus and prompt v2 validation:
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_eval.py --validate --case-file docs/milestones/M05A/unseen-cases.jsonl --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2`
  (7 valid cases; no runtime contacted).
- **OBSERVED PASS:** Focused tests:
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_m05a_eval -v`
  (12 tests passed).
- **OBSERVED PASS after formatting correction:** `make verify PYTHON=.venv/bin/python`
  exited 0. The first run stopped at Ruff format check because
  `scripts/m05a_eval.py` needed formatting; Ruff formatted that file, then the
  complete verify target passed (including Go vet/build, Ruff, Compose/config
  validation, repository script tests, 64 STT tests and governance checks).
- **OBSERVED PASS:**
  `docker compose --env-file .env -f compose.yaml config --quiet` and
  `git diff --check` exited 0 after the final edits (rerun below recorded).
- **OBSERVED:** Targeted v2 run (`private/m05a/qwen-targeted-v2b-20261022`)
  completed 10/10; unseen run (`private/m05a/qwen-unseen-v2-20261022`)
  completed 7/7; full v2 run
  (`private/m05a/qwen-full-v2-20261022`) completed 39/39. Settings and model
  digest match the v1 baseline. All three run summaries record successful
  unload and empty `/api/ps`. One earlier launch attempt left an empty result
  directory at `private/m05a/qwen-targeted-v2-20261022`; it is retained as an
  incomplete attempt and is not used as evidence.
- **OBSERVED:** After inference, GPU returned to 2,216 MiB used / 12,694 MiB
  free at 0% utilization. Gateway, STT and TTS retained their prior container
  IDs, all were healthy, each had zero restarts and `OOMKilled=false`. Ollama
  retained its prior identity, was running with zero restarts, and had no model
  loaded.
- **NOT ESTABLISHED:** No simultaneous LLM/TTS test, alternate quantization
  test, or operator acceptance was performed.
- **INTERPRETATION:** See [prompt refinement](prompt-refinement.md) for semantic
  review: v2 retains 17 distinct critical-failure cases in the 39-case corpus
  and is not recommended for acceptance.

## Groq cloud adapter implementation verification — 2026-10-22

- **OBSERVED:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest
  scripts.test_m05a_eval scripts.test_m05a_groq_eval -v` passed 26 focused
  tests after final edits. Coverage includes missing-key rejection before
  artifacts/network, request serialization, per-model reasoning settings,
  completion parsing, 429/Retry-After, auth/quota classification, transient
  retry, 5xx sanitation, timeout, malformed response, persistence, secret
  omission, preview and resume.
- **OBSERVED:** Both direct preview commands for `qwen/qwen3.8-27b` and
  `openai/gpt-oss-120b` exited 0, validated the 46-case combined corpus and
  made no provider request. Each forecast 46 successful calls, with at most
  138 attempts including two retries per request.
- **OBSERVED:** `make verify PYTHON=.venv/bin/python` completed successfully
  after the final adapter and test changes: Go vet/race tests/build, Ruff,
  configuration/Compose/release checks, all 461 script tests, AST validation,
  governance and lock validation passed. `git diff --check` exited 0.
- **OBSERVED:** After verification, `docker compose --env-file .env -f
  compose.yaml ps --format '{{.Service}} {{.State}} {{.Health}}'` reported
  `gateway running healthy`, `stt running healthy`, and `tts running healthy`.
  No service was restarted or modified.
- **OBSERVED:** The execution environment did not contain `GROQ_API_KEY`
  (only presence was checked; no credential value was read or printed).
  No Groq request was sent; cloud output, API errors, billing, latency, token
  totals and quality results are **NOT ESTABLISHED**. The implementation is
  verified offline, but the requested cloud evaluation is incomplete pending
  secret-safe key availability.
- **NOT ESTABLISHED:** User/operator semantic review, Groq account-specific
  quota and cost, and whether either cloud model merits acceptance. M05A
  remains IN PROGRESS; no M05B work or closeout occurred.


## Groq requests transport and provider execution — 2026-10-22

- **OBSERVED:** `requests.post` with the exact runner payload for a real corpus
  case returned HTTP 200 and model `qwen/qwen3.8-27b`. After adapting
  `call_groq`, a live request through that function also returned HTTP 200 with
  a response ID and parsed response. The API key was read from
  `private/groq_api`; it was not printed or added to arguments or artifacts.
- **OBSERVED PASS:**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_m05a_groq_eval -v`
  passed 15 focused adapter tests, including transport response parsing,
  sanitized errors, 429 retry-after, timeout, result persistence and resume.
- **OBSERVED:** Qwen run `private/m05a/groq-qwen3.8-27b-v2-requests-20261022`
  completed all 46 cases in 50 attempts (four retries, zero failed cases).
  GPT-OSS run `private/m05a/groq-gpt-oss-120b-v2-requests-20261022` completed
  all 46 cases in 46 attempts (zero retries, zero failed cases). Both used the
  configured sequential 2.1-second delay, 60-second timeout and maximum two
  retries. Run/result/summary files were mode 0600.
- **OBSERVED PASS:** `make verify PYTHON=.venv/bin/python` exited 0 after the
  transport change. Go vet, Ruff lint/format, configuration and Compose checks,
  release checks, `go test -race ./...`, `go build ./...`, script test discovery
  (64 tests), AST validation, governance tests and dependency lock checks passed.
- **INTERPRETATION:** The `requests` success supports HTTP-client behavior as
  the cause of the earlier 403 in this environment; it does not establish the
  specific Cloudflare rule.
- **NOT ESTABLISHED:** Semantic quality review, account-specific quota and
  billing review, and operator acceptance remain pending. M05A remains in
  progress; M05B has not started.

## Groq semantic review and documentation verification — 2026-10-22

- **OBSERVED:** Offline review covered every source case, transformation
  option and stored response for the 39 original and seven unseen cases for
  both models. Authoritative records were the existing private
  `groq-qwen3.8-27b-v2-requests-20261022/results.jsonl` and
  `groq-gpt-oss-120b-v2-requests-20261022/results.jsonl`. No Groq API request
  was made during this review.
- **OBSERVED:**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_eval.py --validate --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2`
  exited 0: 39 cases validated, no runtime contacted.
- **OBSERVED:**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_eval.py --validate --case-file docs/milestones/M05A/unseen-cases.jsonl --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2`
  exited 0: seven cases validated, no runtime contacted.
- **OBSERVED:**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_m05a_eval scripts.test_m05a_groq_eval -v`
  exited 0: 27 offline tests passed. Provider tests use mocks; no live request
  was made.
- **OBSERVED:** `make governance-check PYTHON=.venv/bin/python` exited 0:
  governance structural validation and two governance tests passed.
- **OBSERVED:** A local consistency check verified both private results files
  contain the 46 expected unique case IDs, exact model labels, prompt v2 and
  successful outcomes. A documentation check verified all 46 IDs appear in
  the case disposition tables and all local Markdown links in the review,
  execution, operator-validation and result documents resolve.
- **OBSERVED:** `git diff --check` exited 0.
- **INTERPRETATION:** These checks establish corpus/run/document consistency
  and offline runner/governance integrity. They do not independently validate
  linguistic quality or substitute for operator judgment.
- **NOT ESTABLISHED:** Independent second-reviewer agreement, operator
  acceptance, account billing/cost, or suitability beyond this synthetic
  corpus. M05A remains open; M05B is not started.
