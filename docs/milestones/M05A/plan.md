# M05A — Local LLM evaluation

Status: **COMPLETE for bounded candidate evaluation and operator-reviewed selection; no production integration. Closed 2026-10-22.**

## Authorized continuation — Groq reference comparison

Compare `qwen/qwen3.8-27b` and `openai/gpt-oss-120b` through the Groq chat
completions endpoint using unchanged prompt v2 and the original 39 cases plus
seven unseen cases (46 each). Extend the existing Python runner with a small
standard-library adapter, preserve the Ollama CLI path, and add offline
security/serialization/error/resume/preview coverage. Store raw cloud output
only in ignored `private/m05a/`. Do not add production provider configuration,
Gateway behavior, M05B work, or a dependency. Sequential calls, a 2.1-second
default delay, a 60-second default bounded timeout, at most two retries, and
stop-on-quota behavior bound the run. Use Qwen reasoning off and GPT-OSS low
reasoning with reasoning output excluded. The exact settings, official API
documentation and manual semantic-review method are in
[`groq-cloud-evaluation.md`](groq-cloud-evaluation.md).

Required verification: focused offline tests, corpus validation, the full
`make verify PYTHON=.venv/bin/python`, `git diff --check`, and current
Gateway/STT/TTS health. Cloud full runs require the user's secret-safe
`GROQ_API_KEY` environment availability; a missing key must fail closed. The
cloud run and operator review remain required to complete the evaluation.

## Purpose and scope

Select whether a local model is suitable for planned rewriting, formatting and
translation by measuring quality and resources against synthetic English,
Swedish, Russian and mixed-language cases. Meaning preservation is the highest
priority. This work adds no production endpoint, service, provider framework,
or Gateway/STT/TTS behavior.

The evaluation covers modes `raw`, `written`, `polite`, `diplomatic`; mutually
exclusive formatting `normal`, `concise`, `structured`; and translation to
English, Swedish and Russian. `raw` with no translation is exact passthrough
and is excluded from model inference. Each included case uses one prompt and
one model call.

## Responsibilities and boundaries

- `cases.jsonl` is the synthetic, human-readable corpus and records
  case-specific factual constraints.
- `prompts/v1.md` defines the fixed one-call transformation instruction.
- `scripts/m05a_eval.py` validates the corpus, calls the existing Ollama HTTP
  API sequentially with fixed generation settings, records output/timing, and
  reports lexical invariant checks. It does not add a server or dependency.
- Raw responses, host telemetry and detailed run files are stored below
  ignored root `private/m05a/`; tracked records contain only synthetic examples
  and summarized evidence.
- Existing Gateway, STT, TTS, Ollama and Dify service configuration and
  lifecycle remain outside the change. Model artifacts may be added to the
  existing Ollama store for this explicitly authorized evaluation; only
  evaluation-created tags may be removed during cleanup.

No public API or compatibility surface changes. Do not call the STT or TTS
inference paths from the harness. Do not test simultaneous LLM/TTS GPU use
unless separate measurements show safe headroom.

## Candidate plan

Use the existing Ollama runtime (observed v0.33.1), if candidate pulls and
inference are supported:

1. [`qwen3.5:9b-q4_K_M`](https://ollama.com/library/qwen3.5/tags)
   (Ollama library; expected artifact about 6.6 GB; [Qwen3.5-9B model
   card](https://huggingface.co/Qwen/Qwen3.5-9B), Apache 2.0).
2. [`gemma3:12b-it-q4_K_M`](https://ollama.com/library/gemma3/tags)
   (Ollama library; expected artifact about 8.2 GB; [Gemma Terms of
   Use](https://ai.google.dev/gemma/terms/)).

Record exact Ollama digest after pull. Qwen3.5-9B model card declares Apache
2.0. Gemma 3 uses Google Gemma Terms of Use, which require separate review
before any production use. Model-format compatibility, actual quantization,
GPU offload and resource fit must be established on this host, not inferred
from catalog size.

## Evaluation procedure

1. Capture target identity, Docker/Compose state, Ollama version/model list,
   model-store state, STT/TTS readiness, RAM, disk and GPU baseline.
2. Validate the corpus and prompt. Pull only the two named model tags, one at
   a time. Do not update the Ollama container, restart services, or change
   STT/TTS settings.
3. For each model, run every included corpus case sequentially with context
   4096, one parallel request, fixed seed/temperature/top-p/output limit and
   finite timeout. Keep a model loaded only for its run; explicitly unload it
   after the run. Capture first streamed output time and Ollama duration
   counters where available.
4. Sample `nvidia-smi`, process/container memory and STT/TTS readiness around
   the run. Stop if GPU headroom becomes unsafe, inference is not bounded, or
   any existing service becomes unhealthy. Do not provoke OOM. Do not run TTS
   concurrently with an LLM on the GPU without a separate safe capacity case.
5. Compare the same cases and prompt for both models. Lexical checks flag
   missing exact names, dates, numbers and identifiers; they are not semantic
   proof. Review every case for factual preservation, omissions, additions,
   negation, uncertainty, tone, translation and formatting. Leave manual
   ratings pending if not actually reviewed.
6. Record cold versus warm latency, time to first output, tokens/s,
   peak-observed VRAM/RAM, offload, unload/reload and service impact. A single
   run does not establish sustained concurrency or production capacity.
7. Preserve exact cleanup commands; remove only tags created for this
   evaluation after operator review, and verify original Ollama models and
   service identities remain.

## Acceptance criteria

- [x] 30–40 valid synthetic cases cover the requested languages, modes,
      formats, translation directions and factual traps.
- [x] Both local candidates have verified identities, revisions, quantizations,
      runtime compatibility and license notes.
- [x] Same-case outputs and provenance are saved privately; objective
      invariants are checked without claiming semantic equivalence.
- [x] Manual quality and representative English, Swedish and Russian outputs
      are available for operator review.
- [x] Cold/warm latency, TTFT, throughput, VRAM/RAM, offload, unload/reload
      and STT/TTS status are reported with conditions and limitations.
- [x] Cleanup and operator validation instructions are prepared.
- [x] No M05B integration or production behavior was added. M05A closeout and
      commit were explicitly authorized by the operator on 2026-10-22.

## Validation commands

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/m05a_eval.py --validate`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_m05a_eval -v`
- `make verify PYTHON=.venv/bin/python`
- `docker compose --env-file .env -f compose.yaml config --quiet`
- target-host resource/readiness checks recorded in `verification.md`
- `git diff --check`

The operator's validation and closeout decision are recorded in
[`user-validation.md`](user-validation.md) and [`result.md`](result.md).
M05B implementation and its closeout remain separate decisions.

## Prompt refinement continuation

The authorized continuation adds immutable prompt v2, one targeted regression
set drawn from confirmed v1 failures, and a separate small unseen corpus. If
those findings justify it, run the unchanged original corpus with v2 and
compare semantic review, language, formatting, translation, latency, GPU and
throughput. Store all raw outputs and telemetry under ignored
`private/m05a/`; preserve v1 and baseline results. Do not iterate prompts after
critical v2 failures; stop for operator review. No M05B, service integration,
model download or model change is included. Detailed observed outcomes and the
stop recommendation are in [prompt-refinement.md](prompt-refinement.md).
