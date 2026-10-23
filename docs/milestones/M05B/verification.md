# M05B verification

Status: **M05B CLOSED with accepted limitations, operator-approved 2026-10-23. Stage 1 and Stage 2B integration are PASS; Stage 2A's seven lexical-invariant failures per context remain failures. Stage 2C production Gateway deployment and technical local-Qwen transformation are PASS; semantic preservation is PARTIAL. Cloud integration is qualified in isolation and production cloud inference remains disabled. Simultaneous local LLM inference and TTS cold-loading are not qualified. Generated transformations require user review.**

## Stage 2A preflight and safety gate — 2026-10-22

**OBSERVED:** the Stage 2A runtime preflight commands were read-only. The
environment was `/home/master/speech-platform`, branch `main`, at baseline
`0066c9a39fb09725137781cde114f912402033b4` before documentation edits.

| Command / observation | Result |
| --- | --- |
| `nvidia-smi` | Exit 0; Quadro RTX 5000, driver 580.178.04, 15,360 MiB total, 2,216 MiB used / 12,694 MiB free, 0% utilization, 35 C. The GPU process mapped to the running STT container. |
| `docker ps --format ...` | Exit 0; product Gateway/STT/TTS, shared Ollama, M01E containers, Dify and supporting services were running. No container was changed. |
| `curl ... http://127.0.0.1:11434/api/ps` | Exit 0; `{"models":[]}`. |
| `docker exec ollama ollama --version` | Exit 0; Ollama 0.33.1. |
| `curl ... /api/tags` filtered to `qwen3.5:9b-q4_K_M` | Exit 0; installed digest `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`, size 6,550,825,550 bytes. No download needed. |
| `curl ... http://127.0.0.1:8080/healthz` / `/readyz` | Both exit 0; `alive` / `ready`. |
| `docker inspect --format ...` on product Gateway/STT/TTS | Exit 0; all healthy, restart count 0. |
| `.venv/bin/python scripts/m05a_eval.py --validate --case-file private/m05a/stage2a-cases.jsonl --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2` | Exit 0; 9 private synthetic cases valid, prompt v2; runner explicitly reports no runtime contacted. All source texts are within 867 UTF-8 bytes; maximum 843. |

**OBSERVED (historical preflight):** the operator replied “No / not sure” to
the prior quiescence question. That gate is superseded by the non-destructive
procedure below; the historical response did not authorize exclusive use.

## Revised shared-server preflight — 2026-10-22 16:56 UTC

**OBSERVED:** read-only checks at 16:56:38 UTC returned empty Ollama
`/api/ps`; Quadro RTX 5000 15,360 MiB total, 2,216 MiB used, 12,694 MiB free,
0% GPU utilization and 34 C. `nvidia-smi` process accounting attributed
2,212 MiB to the host Python process mapped to the STT container. Gateway,
STT, TTS and Ollama were running with restart count zero; Gateway, STT and TTS
were healthy. Gateway health endpoints returned `alive` and `ready`. Recent
Ollama logs expose caller address and route but no client identity or request
owner; `/api/ps` exposes residency but not client use.

**INTERPRETATION:** the revised procedure can avoid explicit unload and use
finite `keep_alive: "60s"`, with sequential contexts, GPU/residency sampling,
contamination handling and a natural-expiry observation window. Current logs
and process accounting cannot reliably distinguish a concurrent local client
from this benchmark or attribute shared Ollama GPU use by client. The safety
condition requiring attributable resource use is not met.

This subsection records the earlier preflight before the subsequent one-request
authorization. Its “stopped before inference” observations remain historical;
the smoke execution evidence below supersedes that runtime status only for its
single 8K request.

## Authorized one-request 8K runtime smoke — 2026-10-22

**OBSERVED:** the actual command used Python 3's standard library to issue one
`POST /api/generate` directly to `http://127.0.0.1:11434`. The JSON payload used
model `qwen3.5:9b-q4_K_M`, a short synthetic sentence rewrite prompt,
`stream=false`, `keep_alive="60s"`, `think=false`, and options
`num_ctx=8192`, `num_predict=64`, `temperature=0`. The first harness attempt
used an unavailable `python` executable and exited before sending a request;
the successful `python3` invocation sent exactly one generation POST.

**OBSERVED:** client latency was 10.607 seconds; Ollama logged HTTP 200 in
10.201 seconds and reported a 9.671-second model load. The response completed
with 40 prompt tokens and 14 output tokens and read: “The meeting is
rescheduled to Friday for an additional report review.” No API error or
truncation was reported.

**OBSERVED:** one-second sampling recorded a highest sampled GPU use of 8,802
MiB used / 6,108 MiB free (baseline 2,216 / 12,694 MiB; 15,360 MiB total).
Ollama `/api/ps` showed the expected model digest resident at context 8,192,
with 5,828,646,010 bytes of VRAM and expiry `2026-10-22T17:02:12.198266162Z`.
At the 17:02:12 UTC poll the model was absent and GPU memory was already at
baseline. It remained absent and at baseline for subsequent 10-second samples
through 17:03:13 UTC (the 120-second observation window); several consecutive
samples also showed 0% utilization.

**OBSERVED:** Ollama logs for the run interval contained exactly one
`POST /api/generate`; other Ollama requests were the monitor's `GET /api/ps`
and preflight `GET /api/tags`. Logs expose only the bridge caller address, and
GPU process accounting aggregates by process. Thus no extra generation request
was observed, but attribution of every possible shared-client action is not
established.

**OBSERVED:** final Gateway `/healthz` and `/readyz` returned `alive` and
`ready`; in-container STT and TTS `/healthz` each returned `alive`. Gateway,
STT, TTS and Ollama remained running with their original restart counts of
zero. Final `/api/ps` was empty and GPU memory was 2,216 MiB used / 12,694 MiB
free / 0% utilization. No unload, restart, service configuration change,
cloud request, speech inference or Gateway deployment occurred.

**INTERPRETATION:** the one short 8K request succeeded, sampled free memory
remained above the 1,024 MiB abort floor, natural model expiration was observed,
and GPU memory returned to baseline. One-second sampling cannot guarantee the
true instantaneous peak; timing and residency support but do not prove exclusive
resource attribution to this request.

**NOT ESTABLISHED:** 4K behavior, nine-case quality or latency, exhaustive
client attribution, simultaneous STT/TTS inference capacity, full shared-GPU
coexistence, cold-start characteristics beyond this model-load duration, or
production suitability. No 4K/8K benchmark or Stage 2B work was performed.

## Authorized partial 4K comparison — 2026-10-22

**OBSERVED:** the repository was `/home/master/speech-platform`; case
validation used:

```sh
.venv/bin/python scripts/m05a_eval.py --validate \
  --case-file private/m05a/stage2a-cases.jsonl \
  --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2
```

It exited 0 and reported 9 valid cases with no runtime contact. Read-only
preflight showed an empty Ollama `/api/ps`, the exact installed Qwen digest,
GPU baseline 2,216 MiB used / 12,694 MiB free, and Gateway/STT/TTS healthy with
restart count zero. A private no-unload harness then sent the first 4K request
with `keep_alive: "60s"`. Ollama logged HTTP 200 and 10.219493 seconds; backend
logs recorded 452 prompt tokens, 24 completion tokens, 456 ms prompt evaluation
and 568 ms generation. The response reached the harness, which then failed with
`ModuleNotFoundError: No module named 'scripts'` while computing invariant
flags. The output, Ollama load duration and client-side total were not saved.
No retry was sent.

**OBSERVED:** one-second telemetry in
`private/m05b/stage2a-20261022/samples.jsonl` recorded peak GPU use of 8,508
MiB / minimum free 6,402 MiB and immediate Qwen residency at context 4,096.
The expected natural expiry passed; `/api/ps` was empty and GPU memory was back
at 2,216 / 12,694 MiB by 17:20:52 UTC. Three recovery samples through
17:20:54 confirmed baseline recovery. No extra generation POST, product health
degradation or restart was observed. The server logs identify only a shared
bridge address, so exhaustive client attribution is NOT ESTABLISHED; this
single request is not marked contaminated because no concurrent generation
activity was observed.

**OBSERVED — command outcome:** `.venv/bin/python
private/m05b/stage2a-20261022/run.py` exited 0 and printed a zero completed
case count because the harness caught the post-response exception and
serialized its partial state. Ollama's HTTP 200 generation log and backend
token timings independently establish that the request itself completed. The
zero count is not evidence that no request was made.

**INTERPRETATION:** the API completion, sampled resource use, natural expiry
and memory recovery are observed for one 4K request. The harness failure
prevented the required nine-case run, quality review and comparative 8K run.
Following the documented stop rule, no further inference requests were sent.
The earlier 8K smoke used different prompt and generation parameters and is
not an equivalent comparison point.

**NOT ESTABLISHED:** 4K load latency, saved response quality, a nine-case 4K
result, any nine-case 8K measurement, direct 4K/8K differences, tokenizer or
template limits, coexistence and production suitability.

## Revised procedure documentation checks — 2026-10-22

**OBSERVED:** `.venv/bin/python scripts/m05a_eval.py --validate --case-file
private/m05a/stage2a-cases.jsonl --prompt
docs/milestones/M05A/prompts/v2.md --prompt-version v2` exited 0 and reported
9 valid cases, prompt v2, no runtime contacted. This confirms the prepared
synthetic corpus remains valid.

**OBSERVED:** `make governance-check PYTHON=.venv/bin/python` exited 0; seven
skill structures/frontmatter and governance local references passed, followed
by two governance validator regression tests.

**OBSERVED:** a local link and trailing-whitespace check using
`validate_governance.validate_links` over `PLANS.md`, the M05 umbrella plan and
all M05B Markdown records exited 0 for 10 files. `git diff --check` exited 0.
These checks validate documentation structure only; they do not implement a
live no-unload harness or establish runtime behavior.

## Operator-reported Stage 1 verification confirmation — 2026-10-22

**OBSERVED (operator-reported evidence; commands were not rerun in this
documentation/commit turn):** the operator reports the following checks passed:

| Command | Operator-reported result |
| --- | --- |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0 |
| Dedicated TTS/SSML suite | PASS, 22 tests |
| `go test -race ./...` | PASS |
| `git diff --check` | PASS |
| Gateway configuration validation | PASS |

The operator supplied no additional environment/version details for this
confirmation. These results are not a claim that commands were executed again
in this turn. This evidence is limited to Stage 1 offline verification and does
not establish deployment, live inference, provider compatibility,
tokenizer/template fit, GPU coexistence, remote cancellation or unload, or
production readiness.

## Original planning inspection — 2026-10-22

- **OBSERVED:** `pwd`, `git status --short` and `rg --files` established the
  authorized repository and initial dirty state: modified `PLANS.md`, untracked
  M05A records and six evaluation/report scripts/tests. Existing work is preserved.
- **OBSERVED:** Read repository instructions/methodology, architecture principles,
  relevant ADRs, M00–M04 roadmap and operation patterns, M05/M05A records, Gateway
  loader/handlers/bootstrap, OpenAPI, Compose/Dockerfile, Make targets and
  evaluation adapters/prompts. These are source inspections, not executed tests.
- **OBSERVED (historical, superseded):** At the time of the original planning
  inspection, the then-present M05A result/validation files showed pending
  closeout and no explicit closeout authorization had been provided in that
  planning task. This observation was superseded by the subsequently committed
  M05A closeout; see Stage 1 verification below. Its bounded measurements and
  known quality limitations remain attributed to M05A records.
- **OBSERVED:** Consulted official Ollama generation and Groq compatibility/
  reasoning documentation, linked in ADR 0021. No inference calls were made.
- **INTERPRETATION:** Existing Gateway/config/HTTP infrastructure supports a small
  optional module and two adapters without another inference service. A reviewed
  outbound path is needed because current Compose disables publish masquerading;
  actual connectivity has not been probed.
- **NOT ESTABLISHED:** Proposed schema validity in a future Go implementation,
  OpenAPI conformance for the proposed route, Go/Groq and container/Ollama
  compatibility, cloud connectivity, runtime deadlines/fallback/privacy behavior,
  model quality, current account cost, concurrent GPU capacity or live health.

## Original planning checks (prior to Astra revision)

- **OBSERVED:** `make governance-check PYTHON=.venv/bin/python` exited 0:
  seven skill structures/frontmatter and governance local references passed;
  both existing governance-validator regression tests passed. This target does
  not automatically inspect every new milestone link.
- **OBSERVED:** An inline `.venv/bin/python` documentation check exited 0,
  applying `scripts.validate_governance.validate_links` and trailing-whitespace
  checks to all eight changed/new roadmap/planning documents. It asserted the
  five required milestone filenames, parsed the plan's YAML using
  `yaml.safe_load` and JSON using `json.loads`, and checked initial model order,
  provider references, explicit `think: false`, reasoning `none` and
  `allow_cloud: false`. Result: PASS. This proves example syntax and these
  structural properties, not the unimplemented schema's validation rules.
- **OBSERVED:** `git diff --check` exited 0. Untracked planning files were
  separately included in the inline whitespace/link check above. Final status
  contained documentation changes and the preserved pre-existing M05A work.
- **NOT ESTABLISHED:** No application tests, full `make verify`, OpenAPI
  semantic validation, build, Compose rendering, provider inference or live
  service checks were run for this documentation-only change. The existing
  production OpenAPI and deployment files were not edited.

## Future verification

The [plan](plan.md) maps risks to automated checks and gives implementation
commands. [Operator validation](user-validation.md) specifies later live checks
and external data transmission. Future evidence must include environment,
commands, exit status and limitations, separate from these source observations.


## Astra revision verification — 2026-10-22

Environment: `/home/master/speech-platform`, existing local Go toolchain,
`.venv/bin/python` and Docker Compose. Documentation-only scope; commands below
validate files offline and do not start/recreate containers or call providers.
The original planning evidence above is historical, not a rerun claim.

**OBSERVED:** inspected current Gateway loader/handler/bootstrap, public OpenAPI,
STT/TTS configuration/lifecycle, root Compose, Makefile, M05A prompt/evaluation
and all existing M05B documents. No M05B Astra review text was found by searching
project records; findings A–I supplied by the operator are the review input.
M05A reports 6,400 MiB minimum free; TTS config/factory requires 8,000 MiB before
load. Current Gateway signal handling calls Server.Shutdown without explicitly
cancelling active handler contexts. Current make verify omits the dedicated
services/tts/tests suite. These are source/historical observations, not live tests.

| Executed command | Outcome / scope |
| --- | --- |
| `make governance-check config PYTHON=.venv/bin/python` | Exit 0. Seven skill structures and governance links validated; 2 governance regression tests passed. Existing Gateway, STT base/product and TTS configurations passed check-config. Does not validate the future text schema. |
| `docker compose --env-file .env.example -f compose.yaml config --quiet` | Exit 0. Existing product Compose rendered with example inputs; no service mutation. |
| `.venv/bin/python /tmp/m05b-plan-review/check_docs.py` | Exit 0. Eight planning/roadmap files checked for links, local anchors and whitespace; plan YAML/JSON parsed; model order/references, default cloud prohibition, shared transport, context-budget arithmetic and removed duplicate fields asserted. Scratch checker contains no production implementation. |
| `git diff --check` | Exit 0. Tracked changes clean; the scratch checker also covers all untracked M05B/ADR documents. |

For reproducible basic document checks without the temporary checker, the
following equivalent subset was also executed successfully (exit 0):

```sh
.venv/bin/python - <<'PYDOC'
from pathlib import Path
import json, re, yaml
from scripts.validate_governance import validate_links
files = [Path('PLANS.md'), Path('docs/milestones/M05/plan.md'),
         Path('docs/adr/0021-configurable-text-transformation.md')]
files += sorted(Path('docs/milestones/M05B').glob('*.md'))
assert len(files) == 8
for path in files:
    assert not validate_links(path), str(path)
    assert all(line.rstrip() == line for line in path.read_text().splitlines())
plan = Path('docs/milestones/M05B/plan.md').read_text()
config = yaml.safe_load(re.search(r'```yaml\n(.*?)\n```', plan, re.S)[1])
assert config['text_transform']['selection'] == {'policy': 'ordered', 'allow_cloud': False}
for block in re.findall(r'```json\n(.*?)\n```', plan, re.S):
    assert 'review_required' not in json.loads(block)
print('PASS: eight documents, local links, whitespace and YAML/JSON examples')
PYDOC
```

**OBSERVED (historical):** reviewed final Git diff and task-start snapshot comparisons for
pre-existing untracked M05B/ADR files. Exactly eight planning/roadmap documents
were revised; prior M05A work, source, public contract and production configuration
remain untouched. `diff -u` returns 1 when expected document differences exist;
that is not a failed validation. No commits or milestone advancement occurred.

**INTERPRETATION (historical):** the revised specification addresses all nine findings.
Conservative context limits trade usable input length for a bounded preflight;
model/template assumptions still require qualification.

**NOT ESTABLISHED (historical):** no full make verify, application/STT/TTS regression suite,
M05B fake-server/handler tests, live inference, GPU tests, runtime shutdown,
network qualification or rollback was executed in this revision. In particular,
the mandatory future TTS/SSML command has been added to the plan, not claimed
passed. Tokenizer/template bounds and illustrative overhead values, actual
remote stop/unload and safe GPU coexistence remain Stage 2 gates. At the time of
this historical record M05B was not implemented and M05A was not yet closed.
No running service or private data was changed in those planning checks.

## M05A closeout verification — 2026-10-22

**OBSERVED:** `git show --no-patch --format='commit %H%nsubject %s%ncommitted %cI' a5d22ab2ce7e52b2dc15380b5391832d0523ab8e` reports commit
`a5d22ab2ce7e52b2dc15380b5391832d0523ab8e`, subject `docs: close M05A evaluation`,
committed `2026-10-22T15:50:07+00:00`. The same commit's
`docs/milestones/M05A/result.md` records **PASS; COMPLETE**, bounded candidate
evaluation, and user-reviewed retention of local Qwen3.5 9B Q4_K_M, Groq
Qwen3.8 27B, and Groq GPT-OSS 120B. It preserves critical-case counts of 17
original/3 unseen, 4/0, and 5/1 respectively. The committed operator decision
accepts the documented quality limitations subject to user review and explicitly
does not claim production readiness, account-cost suitability, independent
linguistic validation or safe concurrent LLM/TTS operation.

**OBSERVED:** `git diff --name-only -- docs/milestones/M05A` returned no paths;
no M05A file was modified. The stale pending-closeout text in this M05B record
is retained above as a historical observation and explicitly superseded by the
committed evidence here. M05A was not reopened or recommitted.

## Stage 1 offline implementation verification — 2026-10-22

Environment: `/home/master/speech-platform`, Go 1.24 toolchain, `.venv` and
Docker Compose. All commands below are offline checks. Compose commands render
configuration only; no service was started or changed.

| Executed command | Outcome / scope |
| --- | --- |
| `go run ./cmd/gateway --config configs/gateway-text.example.yaml --check-config` | Exit 0. Validates the non-secret example, strict nested YAML, cross-field constraints and fixed-prompt fit; no credentials are resolved and no network request is made. |
| `go test -race ./...` | Exit 0 after the final Go test edits. Covers config, Gateway route/auth, provider serialization/parsing, selection/fallback, cloud policy, context boundary, duplicate/invalid JSON, cancellation, and existing Go regressions. |
| `make verify PYTHON=.venv/bin/python` | Exit 0. Ran lint, configuration checks, Compose rendering/static checks, release checks, `go test -race ./...`, 472 script tests, 64 STT tests, Go build, governance and lock checks. The Compose actions are render-only. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest services.tts.tests.test_tts -v` | Exit 0; all 22 TTS/SSML tests passed. This suite remains outside `make verify`. |
| `.venv/bin/python` local-link/whitespace check over `PLANS.md`, M05 plan, ADR 0021 and five M05B records | Exit 0; eight files checked. |
| `git diff --check` | Exit 0; no whitespace errors. |

One first `make verify` attempt exited 2 because `cmd/gateway/main.go` had not
yet been gofmt'd. Ran `gofmt -w cmd/gateway/main.go`, then reran the full target
successfully. Later test-only additions were verified by the final
`go test -race ./...` command above.

**OBSERVED (local arithmetic only):** the production-owned system prompt is
1,477 UTF-8 bytes. With default serialized options, 512 framing bytes, configured
prompt overhead and a 1,024-token completion reservation, the example leaves
459 serialized input bytes for local Qwen at context 4,096, and 4,555 bytes for
each cloud model at context 8,192. The preflight bounds serialized byte length,
not provider tokenization. This is conservative, can reject useful inputs before
the configured 10,000-byte input ceiling, and requires Stage 2 tokenizer/template
qualification before model enablement decisions.

**OBSERVED — context-budget review addendum (2026-10-22):** after prompt
compaction, the system prompt is 1,069 bytes and the local example leaves 867
serialized ASCII text bytes. This supersedes the earlier arithmetic above for
the current worktree; that paragraph records the pre-review prompt. The focused
offline boundary command passed:
`go test ./internal/texttransform -run 'Test(ExampleLocalSerializedInputBudget|ContextBoundaryAndMultilingualInputAreNotTruncated|ContextBoundaryCountsJSONEscaping|ContextRejectionMakesNoCall|ValidateConfigRejectsFixedPromptThatCannotFit)$'`.
It checks the pinned budget, exact fit and one-over rejection (including JSON
escaping), multilingual preservation, fixed-prompt validation and no provider
call on overflow. See [context-budget review](context-budget-review.md).

**INTERPRETATION:** offline evidence supports the Stage 1 Go/config/API and
Gateway integration behavior in the tested cases. It does not demonstrate the
quality or meaning preservation of generated text.

**NOT ESTABLISHED:** no Ollama/Groq request, live Gateway request, deployed
configuration, provider compatibility, cloud/local network reachability, model
tokenizer/template bound, GPU coexistence or VRAM recovery, remote cancellation
or model unload, latency/capacity, production secret provisioning, rollback or
live semantic review was performed. The existing 6,400 MiB local-Qwen free-memory
observation remains below the 8,000 MiB TTS load requirement recorded in M05A;
local production enablement remains restricted until Stage 2 evidence or a
separately approved enforceable policy exists. The automated fallback/error
tests exercise representative branches, not every cell and coincidence in the
authoritative failure table; expand that matrix before live qualification.
# Stage 1 context expansion offline verification — 2026-10-22

- **OBSERVED:** `go test ./internal/texttransform` — PASS; exit 0. This includes
  the 8K example budget (4,963 bytes), existing multilingual and JSON escaping
  boundaries, and synthetic long-dictation 4K reject/8K accept behavior.
- **OBSERVED:** `python3 -m unittest scripts.test_m05a_eval -v` — PASS, 12 tests;
  exit 0.
- **OBSERVED:** `python3 scripts/m05a_eval.py --help` — PASS, exit 0; CLI shows
  4K/8K context selection and preserves 4K default.
- **OBSERVED:** `go run ./cmd/gateway --config configs/gateway-text.example.yaml
  --check-config` — PASS, exit 0. This validates the example offline and does
  not contact configured providers.
- **OBSERVED:** initial `python -m unittest scripts.test_m05a_eval -v` could not
  run because `python` is absent (exit 127); the same suite passed under
  `python3` above.
- **INTERPRETATION:** the offline guard now permits a materially longer
  serialized request at 8K with the existing conservative arithmetic.
- **NOT ESTABLISHED:** exact model tokenizer/template fit, live 4K/8K
  acceptance, VRAM use, latency, load/unload behavior, output quality for the
  longer dictation, STT/TTS coexistence or whether >8K is worthwhile. No live
  inference or simultaneous service testing was performed.

## Stage 1 verification follow-up — 2026-10-22

**OBSERVED — root causes:**

- The reported Ruff formatting failure did not reproduce with the repository's
  installed Ruff version. `.venv/bin/python -m ruff format
  scripts/m05a_eval.py` exited 0 and reported `1 file left unchanged`;
  `make verify`'s `ruff format --check services scripts` also passed and
  reported `102 files already formatted`. Therefore no formatting-only source
  diff was needed or created for `scripts/m05a_eval.py`.
- `TestTextTransformExampleAndStrictNestedConfig/invalid_output_budget` changed
  `num_predict` from 1,024 to 4,096. The local example now configures
  `context_limit_tokens: 8192`, making 4,096 valid. The validator correctly
  requires `num_predict < context_limit_tokens`; it was not defective. Updated
  the invalid case to use 8,192, which equals the configured context limit and
  is rejected by the existing validation. No validator or 8K proposal change
  was made.

**OBSERVED — executed verification:**

| Command | Result |
| --- | --- |
| `.venv/bin/python -m ruff format scripts/m05a_eval.py` | Exit 0; `1 file left unchanged`. |
| `make verify PYTHON=.venv/bin/python` | Exit 0. Includes Ruff lint/format checks, configuration and Compose checks, `go test -race ./...`, Python script suite, 64 STT tests, build, governance, and dependency lock checks. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest services.tts.tests.test_tts -v` | Exit 0; 22 TTS/SSML tests passed. |
| `go test -race ./...` | Exit 0; all Go packages passed (packages without tests reported accordingly). |
| `git diff --check` | Exit 0; no whitespace errors. |

**INTERPRETATION:** the output-budget failure was a stale negative fixture
caused by the accepted 8K context update. Existing strict validation and Stage 1
behavior remain intact. Ruff formatting is satisfied in the installed
verification environment, with no formatting-only diff required.

**NOT ESTABLISHED:** this follow-up is offline verification only. It does not
establish live inference, provider compatibility, GPU coexistence, tokenizer or
template fit, deployment behavior, or Stage 2 acceptance. No services were
started or changed, no live inference or deployment was performed, and M05B
remains at Stage 1; operator acceptance is recorded in
[user-validation.md](user-validation.md). Stage 2 remains pending.

## Stage 2A resumed 4K/8K comparison — 2026-10-22

**OBSERVED — prerequisite checks:** after the operator accepted the harness
root-cause analysis and offline regression results, the existing private runner
was formatted in conventional Python syntax. The runner explicitly adds the
repository root before importing the tracked helper, and the helper imports the
invariant checker from that launch path. Its response helper writes the
bounded raw body using an exclusive mode-0600 file, flushes and fsyncs it,
then parses and validates it. The resumed runner creates a new mode-0700
output directory so prior failed-attempt evidence is preserved. An invariant
failure is stored as `quality_status: failed` without stopping the request
corpus; checker/import errors, incomplete responses and infrastructure errors
remain stop conditions.

| Executed command | Outcome |
| --- | --- |
| `.venv/bin/python -m ruff check private/m05b/stage2a-20261022/run.py scripts/m05b_stage2a.py` | Exit 0; all checks passed. |
| `.venv/bin/python -m ruff format --check private/m05b/stage2a-20261022/run.py scripts/m05b_stage2a.py` | Exit 0; both files already formatted. |
| Python import-path check setting `sys.path[0]` to the private runner directory and inserting the repository root as the runner does | Exit 0; `scripts.m05a_eval.invariant_flags` and `scripts.m05b_stage2a.record_response` imported and the checker executed. |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2a -v` | Exit 0; 5 response persistence/classification tests passed, including an assertion that the raw body is present on disk when invariant validation begins. |
| `.venv/bin/python scripts/m05a_eval.py --validate --case-file private/m05a/stage2a-cases.jsonl --prompt docs/milestones/M05A/prompts/v2.md --prompt-version v2` | Exit 0; 9 cases valid, prompt v2, no runtime contacted. |
| `.venv/bin/python -m py_compile private/m05b/stage2a-20261022/run.py scripts/m05b_stage2a.py` | Exit 0. |
| `.venv/bin/python private/m05b/stage2a-20261022/run.py` | Exit 0; 18 requests, 9 completed cases per context, no infrastructure failure, no monitor error, no unexpected generation log line, natural expiry and GPU recovery at both contexts. |
| `make governance-check PYTHON=.venv/bin/python` | Exit 0; seven skill structures/frontmatter and governance references passed; 2 governance regression tests passed. |
| `git diff --check` | Exit 0. |

**OBSERVED — live environment and results:** Ollama 0.33.1 served model digest
`56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`. The
runner executed nine sequential cases at context 4096, observed natural expiry
and memory recovery, then executed the same nine at context 8192. Every
response file was mode 0600. All responses reported completed stop reasons.
The complete response bodies, case rows, samples, context summaries and
redacted review notes remain in private directory
`private/m05b/stage2a-20261022/resume-20261022T183731Z/`; no generated text was
copied into tracked evidence.

| Measure | 4K | 8K |
| --- | ---: | ---: |
| Client latency min / median / max | 0.844 / 2.402 / 9.696 s | 0.837 / 2.399 / 9.544 s |
| Server total duration min / median / max | 0.829 / 2.385 / 9.680 s | 0.820 / 2.381 / 9.521 s |
| Load duration min / median / max | 0.004 / 0.008 / 8.630 s | 0.007 / 0.008 / 8.498 s |
| Prompt evaluation min / median / max | 0.220 / 0.229 / 0.466 s | 0.221 / 0.230 / 0.438 s |
| Completion evaluation min / median / max | 0.559 / 1.812 / 5.847 s | 0.562 / 1.822 / 5.863 s |
| Prompt tokens min–max | 452–675 | 452–675 |
| Completion tokens min–max | 24–250 | 24–250 |
| Sample count; sampled peak used / minimum free | 145; 8,510 / 6,400 MiB | 143; 8,640 / 6,270 MiB |
| Quality status | 2 passed; 7 failed; 13 missing invariants | 2 passed; 7 failed; 13 missing invariants |
| Contamination / monitor errors | No / none | No / none |
| Natural expiry / 3-sample GPU recovery | Yes / yes | Yes / yes |

The pre-run GPU baseline was 2,216 MiB used / 12,694 MiB free. At 18:43:32
UTC Ollama `/api/ps` was empty, GPU memory was at baseline, Gateway health and
readiness passed, and Gateway/STT/TTS were healthy with zero restart counts.
No unload request, restart, model change, deployment, cloud call or speech
inference occurred. Sampled peaks are one-second observations and do not bound
transient peaks between samples. The shared bridge address prevents exhaustive
identity attribution to all possible Ollama clients; no extra generation log
line was observed and both runs are marked uncontaminated under the defined
monitor.

**OBSERVED — output review:** all 18 saved outputs were manually reviewed and
also checked for completion, stop reason, truncation and exact lexical
invariants. Output text was identical between 4K and 8K for every case. The
Swedish short case was generated in English and contained an erroneous term;
the Russian short case had awkward word order and omitted required details.
The English short case omitted required identifier/date tokens. Medium/long
outputs were generally coherent and retained the main status and instructions;
some lexical failures were dates rendered as localized natural-language text.
These are model-quality results, not a harness crash. The output review and
case-level diagnostics remain private and contain no generated transcript in
Git.

**INTERPRETATION:** the larger context produced no changed text, token counts,
quality results or meaningful latency shift for this corpus; its sampled peak
GPU use was 130 MiB higher. The results demonstrate bounded sequential
inference and recovery only. They do not establish broader language quality,
complete client identity attribution, between-sample GPU peaks, simultaneous
speech/LLM coexistence, generalized cold-start behavior or production
suitability.

**NOT ESTABLISHED:** operator acceptance of the mixed quality/resource results,
Stage 2B live-service behavior, production policy, deployment and M05B
closeout. No milestone advancement is claimed.

## Stage 2B Gateway integration preparation — 2026-10-22

**OBSERVED:** baseline was branch `main`, HEAD
`0066c9a39fb09725137781cde114f912402033b4`, with pre-existing dirty M05B
Stage 2A/M06 documentation and private-runner files. The running product
Gateway/STT/TTS containers were healthy with restart count zero; Gateway
`/healthz` and `/readyz` returned `alive` and `ready`, and STT/TTS
`/healthz` returned `alive`. The product Gateway image is M03B, not the M05B
source. No container was changed or restarted.

**OBSERVED:** the isolated private Gateway profile is ignored by Git and has
mode 0600, within a mode-0700 directory. `docker compose config -q` passed
without changing Compose. A private config validation first rejected
`keep_alive: 60s` with the current 5-second maximum; after setting `5s`,
`go run ./cmd/gateway --config private/m05b/stage2b/gateway.yaml
--check-config` passed. The 60-second attempt was a config-only check and
made no provider request.

**OBSERVED:** shared Ollama `GET /api/ps` returned an empty model list. A
default-trust-store TLS handshake to `api.groq.com:443` succeeded with TLS 1.3
and certificate verification. No Groq HTTP request or provider inference was
made. `private/groq_api` is present with mode 0600; its contents and validity
were not inspected.

**OBSERVED — PASS:** `go test ./internal/config ./internal/texttransform
./internal/gateway` and `go test ./...` exited 0. The offline additions test
all 36 written/polite/diplomatic × normal/concise/structured × none/en/sv/ru
option combinations and explicit selection of all three configured aliases
against a fake generator; configured Groq reasoning
payloads for both accepted models against `httptest`; and an authenticated
generated request through the public Gateway handler with a fake provider.
Existing tests cover policies, raw passthrough, fallback, cloud restrictions,
credentials, invalid/incomplete provider responses, context limits, provider
and total timeouts,
cancellation and shutdown. No live provider, GPU inference or speech request
was used. Some Go test results were cache hits; the changed Go test packages
ran and passed.

**OBSERVED — PASS:** `make verify PYTHON=.venv/bin/python` exited 0. This ran
Go vet, Ruff lint/format checks, configuration validation, static Compose and
release checks, `go test -race ./...`, Python scripts/STT unit suites, build,
governance validation and STT/TTS lock checks. It did not start or mutate
containers. No live provider inference was part of the target.

**OBSERVED:** `docker compose config -q` exited 0. Gateway config check exited
0 for the final isolated profile. The private Stage 1 source binary was built
with `go build -o private/m05b/stage2b/gateway ./cmd/gateway`; its SHA-256 is
`d9d97d1a32bc48d59651edebca32ef6ec5a079a7fbfb2755007ce93f6ec4bbf6`. The
binary's `--check-config` exited 0. No Compose deployment/start command was run.

**OBSERVED (post-check):** Gateway health/readiness remained `alive`/`ready`,
STT and TTS remained `alive`, and all three product containers remained
healthy with unchanged start times and zero restarts. `nvidia-smi` reported
15,360 MiB total, 2,216 MiB used, 12,694 MiB free and 0% utilization. No test
loaded a GPU model.

**OBSERVED — isolated API process:** the private Gateway binary briefly bound
`127.0.0.1:18080`. `/healthz` returned `alive`; an unauthenticated transform
POST returned 401; an authenticated raw-only POST returned 200. The private
response had `generated=false` and null model/provider, while metrics reported
zero provider attempts and one passthrough. The isolated process stopped
cleanly. It was given the existing private Groq credential in its environment
but made no provider request. No production service or container changed.

**INTERPRETATION:** the offline Gateway/provider boundary is suitable for a
separately authorized live trial using the isolated source profile. Read-only
host network checks do not establish the running Gateway process's ability to
authenticate with or use either live provider.

**NOT ESTABLISHED:** authenticated Groq availability, live Ollama generation,
actual Go-adapter acceptance of Groq reasoning fields, model output quality,
provider quotas/cost, production deployment, fallback under live provider
failure, remote cancellation, shared-GPU coexistence or production readiness.
The complete matrix and unexecuted exact commands are in
[Stage 2B qualification](stage-2b-qualification.md). The later authorized live
attempt is recorded below.

## Stage 2B authorized live smoke attempt — 2026-10-22

**OBSERVED:** preflight confirmed the production Gateway, STT and TTS healthy
with unchanged container IDs/start times and restart counts zero. Gateway
`/healthz` and `/readyz` returned `alive` and `ready`. GPU baseline was
15,360 MiB total, 2,216 MiB used, 12,694 MiB free, 0% utilization; Ollama
`/api/ps` was empty.

**OBSERVED — failed before provider dispatch:** one authenticated request using
the prepared `explicit-local.json` corpus was attempted against the isolated
loopback Gateway. Curl reported HTTP 000, exit 7, connection refused on port
18080. The exact request was preserved; the response body is empty. The
isolated Gateway had answered its earlier health probe but its process had
exited before the request, with only a startup line in its private log. No
retry or Groq call was made. No provider inference or cloud transmission
occurred.

**OBSERVED — postflight:** the Ollama resident model list remained empty and
GPU was at the same 2,216 MiB used / 12,694 MiB free / 0% baseline. Production
Gateway/STT/TTS health, IDs, start times and zero restart counts were
unchanged. No inference occurred, so GPU residency during inference and
natural model recovery are NOT ESTABLISHED.

**INTERPRETATION:** this is an isolated test-process lifetime failure before
the HTTP/provider boundary. It does not qualify or disqualify any model.
Groq authentication and protocol/reasoning compatibility remain NOT
ESTABLISHED. See [Stage 2B qualification](stage-2b-qualification.md) for the
preserved private evidence paths and remaining stop conditions. The live
qualification is incomplete and Stage 2C must not begin automatically.

## Stage 2B authorized live resume and controller fault — 2026-10-22

**OBSERVED:** the private controller's preflight checks passed and launched a
fresh isolated Gateway child on a loopback ephemeral port. It verified the
prepared configuration, finite `keep_alive: 5s`, explicit model mappings and
private Groq-key presence without displaying the key. However, the preflight
snapshot was not flushed to disk before request execution.

**OBSERVED — one local request, failed:** exactly one authenticated request
using the prepared local synthetic body selected `local-qwen` and
`local_only: true`. The passive monitor thread raised `AttributeError` because
it called `.chmod()` on a file object. Sampling stopped at zero records. During
the safe controller interrupt, the Gateway returned HTTP 503
`text_transform_unavailable`; the raw request, response body and headers are
private under `private/m05b/stage2b/live-20261022T195506Z/`.

Ollama logs show one `POST /api/generate`, status 500, server duration
14.338775556 seconds. The request reached Ollama, but the reason for its 500
and any effect from Gateway cancellation are NOT ESTABLISHED. No valid model
response, public provider/model metadata, complete output, or semantic review
was available. Client latency was not persisted. No retry or fallback was
made.

**OBSERVED:** neither Groq request ran. Groq authentication, response
compatibility and reasoning-option acceptance remain NOT ESTABLISHED. The
error body exposed only the Gateway's public error code/message, without
reasoning text or provider-internal fields.

**OBSERVED — recovery and production:** postflight at 19:58:23 UTC showed an
empty Ollama `/api/ps` and GPU at 2,216 MiB used / 12,694 MiB free / 0%
utilization. This single sample does not establish natural expiry or memory
recovery. Production Gateway/STT/TTS remained healthy with restart count zero;
Gateway `/healthz` and `/readyz` returned `alive` and `ready`. Current
postflight container IDs match the last recorded production baseline. Exact
same-run preflight identity comparison was not persisted. The isolated Gateway
was waited/reaped and no orphan remained; its exit status was not saved. The
controller exited 1 after `UnboundLocalError` while writing its final report
on the interrupt path.

**OBSERVED — offline fix check:** monitor file permission handling and
controller interruption/reporting were corrected in the private controller.
A fake-only monitor smoke wrote samples successfully with mode 0600; Ruff and
Python compilation passed. The live controller was not resumed after this
failure.

**NOT ESTABLISHED:** successful local inference, model output quality, local
natural unload, any Groq authentication/protocol/reasoning compatibility, or
Stage 2B acceptance. The bounded three-model qualification is incomplete; do
not retry or advance to Stage 2C without operator review.

## Stage 2B isolated Gateway process-lifecycle repair — 2026-10-22

**OBSERVED — root-cause evidence:** the earlier launcher backgrounded the Go
Gateway from a short-lived shell/`exec_command`; the HTTP attempt ran in a later
command session. The private log contains only `gateway starting`; the
subsequent curl got HTTP 000 / exit 7 (connection refused), and the Gateway
process was absent. That attempt did not record the old process exit status or
signal. The session/process-owner boundary is the best-supported cause, while
the exact termination mechanism is NOT ESTABLISHED. No provider inference was
sent.

**OBSERVED — correction and offline check:** added
`scripts/test_m05b_stage2b_lifecycle.py`. One controlling Python test process
builds and owns the isolated Gateway child, uses only loopback fake worker and
Ollama protocol endpoints, waits for `/healthz` and `/readyz`, sends requests
sequentially, checks process liveness between requests, then terminates and
reaps the child in `finally`. The temporary config disables cloud and does not
use shared Ollama or Groq.

| Command / evidence | Outcome |
| --- | --- |
| `.venv/bin/python scripts/test_m05b_stage2b_lifecycle.py` | PASS; readiness succeeded; two authenticated raw passthroughs and one fake-provider transformation returned HTTP 200; process stayed alive; cleanup exit status 0. |
| `private/m05b/stage2b/offline-lifecycle.json` | Private evidence records PID, request statuses, process liveness, fake-provider count and exit status; no orphan remained after test. |
| `go test ./internal/gateway ./internal/texttransform` | PASS. |
| `.venv/bin/python -m ruff check scripts/test_m05b_stage2b_lifecycle.py` | PASS. |
| `.venv/bin/python -m ruff format --check scripts/test_m05b_stage2b_lifecycle.py` | PASS. |
| `make verify PYTHON=.venv/bin/python` | PASS after adding the test; exit 0, including Ruff, full Go tests/race tests, Python suites, configuration checks and static Compose checks. |
| `git diff --check` and Stage 2B Markdown link/whitespace checks | PASS. |

The first full-suite run of this new test hit an occupied fixed port 18080 in
the test's port preflight and failed before Gateway startup. The controller
was changed to select an ephemeral port bound only to `127.0.0.1`; focused
test, Ruff checks and the subsequent full `make verify` all passed. No
production service was involved in that initial test-only failure.

**OBSERVED — production remained unchanged:** baseline and post-test production
Gateway/STT/TTS container IDs and start times matched; each remained healthy
with restart count zero. Production Gateway `/healthz` and `/readyz` returned
`alive` and `ready`. The process table had no orphan isolated Gateway.

**NOT ESTABLISHED:** this offline result does not establish live Ollama or Groq
availability, response compatibility, model quality, GPU residency/recovery,
or Stage 2B acceptance. The authorized three-provider smoke test remains
stopped; do not retry or advance without operator review.

## Stage 2B Ollama HTTP 500 and controller diagnostics — 2026-10-22

**OBSERVED — logs and timestamps:** read-only inspection of preserved
`private/m05b/stage2b/live-20261022T195506Z/ollama-window.log` found Ollama
runner startup at 19:55:11, successful model load at 19:55:19, 270 prompt
tokens, 125 generated tokens by 19:55:23, then runner `cancel task` at
19:55:24. The Ollama access log recorded one `POST /api/generate`, HTTP 500,
`14.338775556s`, at 19:55:24. The Gateway response headers record HTTP 503
`text_transform_unavailable` at 19:55:24. The controller report states SIGINT
was sent after its monitor failure. No common monotonic timestamp or Ollama
response body was retained.

**INTERPRETATION:** the close timing of runner cancellation and the controller
interrupt, and the Gateway's stopped-service 503, make lifecycle cancellation
the strongest explanation for the Ollama 500. This is probable, not proven:
the Ollama server's returned error body was absent, so an independent model or
backend error cannot be ruled out. The public Gateway 503 is consistent with
root/service cancellation rather than direct translation of Ollama HTTP 500.

**OBSERVED — resource/model checks:** retained Ollama logs show successful
CUDA memory fitting (12,523 MiB free at fit, projected 5,142 MiB allocation),
context initialization at 8,192 and a loaded runner. No CUDA allocation error,
OOM, runner crash or model-load failure appears in the log. Read-only kernel
log filtering and Docker events found no OOM/Xid match or Ollama restart in
19:54:30–19:58:30 UTC. The failed run has zero monitor samples, so instantaneous
GPU peak and resource causality remain NOT ESTABLISHED. Postflight found
Ollama running with restart count zero, empty `/api/ps`, and 2,216 MiB used /
12,694 MiB free GPU memory. Current `/api/tags` reports the Stage 2A tag and
digest; the exact digest during this request was not durably recorded.

| Parameter | Stage 2A success | Stage 2B failure | Finding |
| --- | --- | --- | --- |
| Model | `qwen3.5:9b-q4_K_M`, digest `56671c2a…` | Same selected tag; historical digest absent | Exact historical digest equivalence not established |
| Context | 4K and 8K | 8K | Runner log confirms `n_ctx=8192` |
| `num_predict` | 512 | 1024 | Different budget; only 125 tokens generated before cancellation |
| `think` | false | false | Runner logged thinking disabled |
| `keep_alive` | 60s | 5s | Difference affects idle residency, not active task completion |
| Sampling | temp 0, top_p 1, seed 20261022, batch 128, threads 8 | Same | No conflicting duplicate context/output parameter found |
| Prompt | Stage 2A prompt v2 | Gateway system prompt plus options and JSON-string text | Different framing; Ollama counted 270 prompt tokens |
| Timeout | 300s direct | 180s provider / 240s Gateway / 245s client | 14.34s failure excludes configured timeout as the likely cause |

**OBSERVED — construction and classification:** inspected
`internal/texttransform/provider.go` constructs the Ollama JSON using the
selected model, system and prompt fields, `stream:false`, configured
keep-alive, and `options` for context, prediction count, batch/thread, thinking
and sampling. The saved private profile matches those expected values. HTTP
5xx is `FailureTransport` and remains eligible for existing automatic fallback;
an explicit model request has only that candidate and returns
`503 text_transform_failed` on uninterrupted provider HTTP 500. Cancellation
returns the separate `503 text_transform_unavailable` path and does not fall
back. No policy changed.

**OBSERVED — controller corrections and offline coverage:** added explicit
interrupt recording, a reusable terminate/wait/reap helper, and final-report
write error reporting to stderr with nonzero result. The monitor preserves
exceptions as abort conditions. New Python regressions exercise an active fake
request interrupted by monitor failure, keyboard interruption, mode-0600
durable request evidence, and child-process reaping. A new Go fake Ollama 500
test checks the existing explicit-model error mapping. The existing Gateway
shutdown cancellation test confirms cancellation does not dispatch fallback.

**NOT ESTABLISHED:** the exact Ollama 500 cause; whether GPU pressure contributed;
instantaneous resource peak; historical model digest; client latency; valid
output; and natural model expiry/recovery for this attempt.

**Recommendation:** do not send more live requests under this diagnostic task.
For any separately authorized next attempt, rerun offline regressions, ensure
preflight snapshots are durable, and then send only the still-authorized local
synthetic request first with raw Ollama response evidence and active GPU/
residency sampling. Groq calls remain unattempted and require renewed explicit
authorization. Stage 2C remains pending operator review.

## Stage 2B authorized single-local Gateway repeat — 2026-10-22 20:12 UTC

**OBSERVED — prior regression gate:** five tests passed in
`.venv/bin/python scripts/test_m05b_stage2b_controller.py`, including a check
that this controller run is capped to one local request. The existing
`.venv/bin/python scripts/test_m05b_stage2b_lifecycle.py` passed. Ruff check,
Ruff format check and Python compilation passed for the private controller
and regression file.

**OBSERVED — bounded execution:** the private controller set its request list
to exactly the explicit `local-qwen` request, set cloud selection false in
the isolated config, removed Groq credentials from the child environment,
and recorded a maximum of zero Groq requests. It used local readiness-only
`/readyz` stubs for the isolated Gateway's STT/TTS readiness probes; no
speech inference was run. Production preflight passed: Gateway/STT/TTS were
healthy with restart count zero, production Gateway `/healthz` and `/readyz`
returned `alive` / `ready`, GPU baseline was 2,216 MiB used / 12,694 MiB free,
and Ollama `/api/ps` was empty. The isolated Gateway's health and readiness
both passed on its dedicated loopback port and the process remained alive.

**OBSERVED — inference and response:** exactly one authenticated synthetic
request was sent, selecting `local-qwen` with `local_only:true`, context 8192
and `keep_alive:5s`. Client latency was 32.898676 seconds. Gateway returned
HTTP 502 `invalid_provider_response`, with no public model/provider metadata
and no transformed text. The Gateway log classifies the Ollama provider
attempt as `invalid_response`. Ollama logs record HTTP 200 in 32.861139467
seconds, `n_ctx=8192`, 270 prompt tokens and exactly 1,024 generated tokens,
matching configured `num_predict`. The provider body and `done_reason` were not
preserved. **INTERPRETATION:** the configured output cap was reached, likely
leading to a length-finished response that the strict adapter correctly
rejects; exact completion fields are NOT ESTABLISHED. Since no valid text was
returned, semantic text quality was not reviewed. No retry or fallback was
made.

**OBSERVED — resources and cleanup:** 27 passive samples (25 during
inference) recorded peak GPU use of 8,638 MiB, minimum free 6,272 MiB, maximum
82% utilization and 54 C. Ollama showed the expected Qwen resident during the
request. Immediate postflight still showed it resident at 8,638 MiB used /
6,272 MiB free; the unhandled 502 triggered the stop condition before the
normal natural-expiry window. No unload was issued. The controller stopped
the monitor/readiness stub, reaped the isolated Gateway with status 0, and
recorded no orphan. Production Gateway/STT/TTS retained the same identities,
healthy status and zero restart counts after the test.

**NOT ESTABLISHED:** valid transformation output, public model/provider
success metadata, exact Ollama completion reason, semantic quality, natural
expiry/memory recovery, Groq compatibility, and Stage 2B fallback coverage.
The exact request, 87-byte Gateway error response, controller report, samples
and Ollama log are private under
`private/m05b/stage2b/live-20261022T201232Z/`. Stop for operator review; this
task authorizes no further inference or Stage 2C work.

## Invalid Ollama completion diagnosis — 2026-10-22

**OBSERVED:** the adapter rejects oversized responses, malformed JSON or
invalid UTF-8, non-empty Ollama `error`, `done:false`, non-empty
`done_reason` other than `stop`, and missing/blank `response` text. It ignores
separate thinking fields. The saved live evidence establishes generation of
exactly 1,024 tokens against `num_predict=1024`, but not the response's
`done_reason` or which validation predicate failed. Token-cap exhaustion is
strongly supported; the precise response failure remains NOT ESTABLISHED.

**OBSERVED — verification commands:**

| Command | Result |
| --- | --- |
| `go test ./internal/texttransform -count=1` | PASS |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_controller -v` | PASS, 6 tests including fake Ollama metadata capture |
| `.venv/bin/ruff check private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS |
| `.venv/bin/ruff format --check private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS |
| `git diff --check` | PASS |

The offline Ollama metadata proxy is loopback-only and accepts only the
prepared `127.0.0.1` Ollama endpoint. It forwards a response capped at 1 MiB
plus one byte and records a mode-0600 JSONL allowlist of non-content
completion metadata. Its fake-server regression verifies byte forwarding and
that output/reasoning/prompt strings do not appear in capture. The proxy has
not been exercised against a live endpoint and no inference was made in this
diagnostic task. Stage 2B remains incomplete and stopped for operator review.

## Authorized Ollama metadata-capture attempt — 2026-10-22

**OBSERVED:** the controller regression suite passed six tests and Ruff lint/
format checks passed before execution. One explicitly selected local request
was sent with the same synthetic request and settings as the prior failed run.
The passive monitor aborted when NVIDIA process accounting briefly labeled
the newly starting Ollama GPU process `[No data]`, treating it as an unknown
compute process. Gateway returned HTTP 503 `text_transform_unavailable`; the
Ollama log records the client disconnect before model loading completed and
HTTP 499. No completion body reached the metadata proxy, so no upstream
completion metadata was written and no adapter validation condition was
tested. This is not a provider completion result. No retry was made.

**OBSERVED — recovery and health:** no unload was requested. Passive samples
recorded Ollama `/api/ps` empty and GPU back at its 2,216 MiB baseline for
three consecutive samples by 20:21:39 UTC after a sampled 8,634 MiB post-abort
peak. Production Gateway/STT/TTS health, identities, start times and zero
restart counts were unchanged. The isolated Gateway exited status 0 and was
reaped; no orphan was recorded.

**NOT ESTABLISHED:** `done`, `done_reason`, token counts, response/thinking
field presence, provider duration, and the exact adapter rejection condition
from the prior HTTP 502. The current single-request authorization is consumed.
Fix and offline-test transient GPU process identity handling, then stop for
operator review before seeking any further live authorization.

## Stage 2B GPU monitor stabilization — 2026-10-22

**OBSERVED:** `private/m05b/stage2b/run_live.py` now separates memory/resource
checks from process attribution. The 1,024 MiB free-memory floor remains an
immediate abort. Recognized driver/CUDA/OOM telemetry errors abort immediately;
unreliable memory measurements abort after three consecutive one-second sample
failures, while one or two failures are recorded and may recover. Compute-app
list failure with valid memory records attribution uncertainty independently.
Unknown process names, including `[No data]`, no longer cancel a request. A
known additional process with adequate free memory marks measurements
contaminated; it does not bypass the memory floor. Ollama process correlation
uses process identity together with the local request phase and expected model
residency, and is explicitly non-exclusive. Gateway health is sampled every
second; production Gateway/STT/TTS identity, health and restart snapshots are
checked every five samples.

**OBSERVED — regressions:**

| Command | Result |
| --- | --- |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_controller -v` | PASS, 15 tests |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_lifecycle -v` | PASS, 1 test |
| `make verify PYTHON=.venv/bin/python` | PASS, including `go test -race ./...`, script and STT tests, lint, config/Compose checks, build and governance/lock checks |
| `.venv/bin/ruff check private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS |
| `.venv/bin/ruff format --check private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS |
| `.venv/bin/python -m py_compile private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py scripts/test_m05b_stage2b_lifecycle.py` | PASS |
| `git diff --check` | PASS |

The controller suite covers `[No data]` followed by identity resolution,
continued fake request execution under attribution uncertainty, additional GPU
process contamination with safe memory headroom, the hard memory floor,
transient and persistent memory telemetry failures, process-list telemetry
failure with valid memory, driver-error abort, production worker health loss,
and cleanup/reaping after an active-request abort. No live request or shared
Go code change was made; Go regression tests were not needed for this Python
controller-only change.

**INTERPRETATION:** the aborted 20:20 diagnostic demonstrated why treating
process-name uncertainty as resource failure was incorrect. The offline tests
now show that attribution uncertainty does not cancel a healthy request while
memory and health gates remain valid. A later live metadata request still
requires separate operator authorization because the previous single-request
authorization was consumed.

## Stage 2B completion diagnosis — 2026-10-22

**OBSERVED:** before the single authorized local request, these offline gates
passed:

| Command | Result |
| --- | --- |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_controller -v` | PASS, 15 tests, including fake-provider metadata capture |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_lifecycle -v` | PASS, 1 test |

Private configuration and request hashes were recorded before and after; both
were unchanged. Explicit preflight assertions confirmed context 8192,
`num_predict: 1024`, `keep_alive: 5s`, and the prepared inference options. The
controller confirmed production service health and captured unchanged
container IDs/restart counts, GPU baseline, empty Ollama residency and the
isolated Gateway's readiness before sending exactly one request.

**OBSERVED:** the request returned HTTP 502 `invalid_provider_response` after
33.557 seconds. Ollama's HTTP 200 completion metadata showed
`done=true`, `done_reason=length`, `eval_count=1024`, a present but empty
`response`, and a separate present `thinking` field with 4,267 characters.
The Gateway adapter rejects the non-stop `done_reason` and blank final
response. The configured 1,024 output-token limit was exhausted. No retry or
fallback occurred. Full sanitized metadata is saved under
`private/m05b/stage2b/live-20261022T205331Z/`; generated text and reasoning
were not copied into tracked documentation.

**OBSERVED:** controller-sampled GPU peak was 8,638 MiB used / 6,272 MiB free.
After controller cleanup, 15 passive samples showed no Ollama model resident
and 2,216 MiB GPU use / 12,694 MiB free, without an unload request. The
isolated Gateway exited with status 0 and its PID was absent. Production
Gateway/STT/TTS remained healthy with unchanged identities and restart counts.

**INTERPRETATION:** the observed failure is an output-budget/reasoning-field
interaction, not a GPU or service-health failure. Evaluate any token-budget or
reasoning-setting change only after operator review; provider validation was
not weakened and no inference setting was changed in this task.

**NOT ESTABLISHED:** semantic quality with a larger output allowance, live
Groq protocol/authentication, broader Stage 2B acceptance, deployment
readiness, and Stage 2C readiness. The single-request authorization is
consumed; stop for operator review.

## Ollama thinking-control serialization correction — 2026-10-22

**OBSERVED:** Ollama 0.33.1 request construction had placed configured `think`
inside `options`, despite the Ollama Generate API defining it as a top-level
field. The prior Ollama warning `invalid option provided`, `option=think`, is
consistent with that misplaced member. The installed Qwen 3.5 9B model reports
the `thinking` capability and requires Ollama 0.30.0; `/api/show` did not
enumerate thinking levels. Versioned Ollama 0.33.1 API source documents a
top-level boolean `think`, where false requests no thinking.

The adapter now emits top-level `"think": false` and omits `think` from
`options`. No context/output limit, keep-alive, sampling setting, or provider
response validation changed. `TestHTTPGeneratorOllamaSerialization` asserts
this wire structure and all configured generation options; existing
`TestOllamaCompletionValidation` continues to assert strict handling of length
completion, missing/blank final text, malformed and oversized responses.

**OBSERVED — verification:**

| Command | Result |
| --- | --- |
| `go test ./internal/texttransform -run 'TestHTTPGeneratorOllamaSerialization|TestOllamaCompletionValidation' -count=1 -v` | PASS |
| `make verify PYTHON=.venv/bin/python` | PASS, including race-enabled Go tests, all script and STT tests, lint, configuration/Compose checks, build and governance/lock checks |

No live inference or service/configuration operation was performed.

**NOT ESTABLISHED:** corrected-field runtime behavior on the installed Ollama
and model, final-text completion within the unchanged 1,024-token budget, and
semantic output quality. A separately authorized bounded live request is
required to establish those observations.

## Single-request Ollama thinking-control verification — 2026-10-22

**OBSERVED:** focused serialization and validation tests, 15 Stage 2B
controller tests, and the lifecycle regression passed before the live request.
The controller built a fresh isolated Gateway binary from corrected source.
Private profile settings, hashes, explicit local selection and `local_only`
were verified before execution. Exactly one local inference request was sent.

Ollama returned HTTP 200, `done=true`, `done_reason=stop`,
`prompt_eval_count=272`, `eval_count=34`, a present 144-character `response`,
and no `thinking` field. Client latency was 10.646 seconds. Gateway returned
HTTP 200 with `model=local-qwen`, `provider=host-ollama`,
`generated=true`, and `fallback_occurred=false`. The output preserved the key
facts but strengthened “should keep” to “must maintain”; record this as minor
meaning/register drift for later output review.

GPU peaked at 8,638 MiB used / 6,272 MiB free. Natural model expiry was
observed; GPU returned to its 2,216 MiB baseline / 12,694 MiB free, confirmed
by eight subsequent passive samples with no Ollama model resident. No unload
request was sent. Production service health, IDs and restart counts were
unchanged. The isolated Gateway exited status 0, was reaped, and its PID was
absent.

**Evidence note:** the controller's `report.json` retained `state=in_progress`
because it copied request results before later response and recovery fields
were populated. A mode-0600 private `result-reconciliation.json` reconciles
the preserved headers, body, completion metadata, samples and health snapshots.
The raw output and request text were not copied into tracked documentation.

**NOT ESTABLISHED:** broader transformation quality, Groq compatibility,
deployment readiness or Stage 2C readiness. This single-request verification
does not complete Stage 2B; stop for operator review.

## Stage 2C deployment readiness preparation — 2026-10-22

**OBSERVED — read-only baseline:** the running Compose labels identify project
`speech-platform`, working directory `/home/master/speech-platform`, files
`compose.yaml` plus `private/m04/live-20261022/rollback.compose.yaml`, and
private `.env`. Gateway image is
`speech-platform-gateway:m03b-high-quality-20261022` (image ID
`sha256:d4cfd90de08651cc79e97632ab6ea904a2c0951f1e9e7ff562c923e1242241b9`),
container ID
`03df6c803d3fee76c29919a19b19f02cb6eaf89f9e381d356277451cee536665`, started
`2026-10-22T10:24:54.29065455Z`, healthy, restart count 0, published only at
`127.0.0.1:8080`. Its only config mount is `configs/gateway.yaml`, SHA-256
`d64ac8b07c7e2040e8107d08ea0fffbb2dc211339bbc3f1eb94ced4536143d93`, which
has no text-transform block. Gateway `/readyz` returned 200.

STT container
`02110b11d58c6d842316a29f29295383cab47a0865284cb69485165a17c79e23` uses
`speech-platform-stt-cuda:3aa5f68c1d9a058ed2714b7b257c5b258a23c00a`, started
`2026-10-21T11:07:40.29861024Z`; TTS container
`cbda986a4e9ace938023a8ccdb571d4169b2855814970ccab7dd49c82cd19569` uses
`speech-platform-tts:m03b-high-quality-20261022`, started
`2026-10-22T10:24:48.2400378Z`. Both were healthy with zero restarts. No
post-task container mutation occurred. Ollama remained the existing
`ollama/ollama` container on Docker's default bridge at `172.17.0.2`, publishing
11434 on all host interfaces; no configuration or lifecycle operation was
performed. Baseline GPU: Quadro RTX 5000, 15,360 MiB total, 2,216 MiB used,
12,694 MiB free; Ollama `/api/ps` was empty.

**OBSERVED — prepared artifacts:** built a uniquely tagged local candidate
image `speech-platform-gateway:m05b-stage2c-20261022`, ID
`sha256:6b17635aa2a61b615d0680cfb1e9e1a8666c12c1b4b81ea482f91f2832b88e20`,
with revision label `m05b-stage2c-0066c9a-working-tree`. Build source HEAD was
`0066c9a39fb09725137781cde114f912402033b4`; the working tree was dirty, so
this is not a production release artifact. The private, Git-ignored config
`private/m05b/stage2c/gateway.yaml` has SHA-256
`a6ddfb6dd69a688616880ed68483ab4b937973c2182dbbf2ecc4ea4571c2200e`; it
enables the feature with `allow_cloud:false`, local Qwen context 8192, and
finite `keep_alive:5s`. No Groq key was supplied. The prepared overlay is
`deployments/compose/compose.m05b-stage2c.yaml`; it selects the image/config,
resets Compose build, and adds a host-gateway alias. No rollout command was
executed.

**OBSERVED — network:** `speech-platform_publish` has subnet `172.28.0.0/16`,
Gateway address `172.28.0.2`, gateway `172.28.0.1`, and
`com.docker.network.bridge.enable_ip_masquerade=false`. A temporary diagnostic
container on that network with the proposed host-gateway mapping timed out
connecting to `host.docker.internal:11434/api/version`; a second read-only
probe to `172.17.0.2:11434/api/version` also timed out. TCP connect-only to
`api.groq.com:443` failed. No inference request or cloud payload was sent.
Adding the hostname alone does not provide the missing Ollama route. Network
changes require separate design/review; cloud remains disabled. Candidate
Compose rendering preserved the Gateway's existing network set and the exact
observed STT/TTS image refs.

**OBSERVED — executed offline verification:**

| Command | Outcome |
| --- | --- |
| `docker run --rm --network none --read-only --user 65532:65532 -v "$PWD/private/m05b/stage2c/gateway.yaml:/config/gateway.yaml:ro" speech-platform-gateway:m05b-stage2c-20261022 --config /config/gateway.yaml --check-config` | PASS, exit 0 |
| `docker compose --env-file .env -f compose.yaml -f private/m04/live-20261022/rollback.compose.yaml -f deployments/compose/compose.m05b-stage2c.yaml config --quiet` with candidate image/config variables set | PASS, exit 0 |
| Candidate Compose render inspection | PASS: candidate image/config and host-gateway alias selected; build reset; STT/TTS image refs unchanged |
| `make verify PYTHON=.venv/bin/python` | **FAIL, exit 2**: lint, config, Compose checks, release check and race-enabled Go tests passed. Python discovery ran 501 tests; one shutdown-cancellation test failed because the child exited `-15` instead of expected 0. The rest of that discovery passed; later Make targets did not run. |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_gateway_acceptance.GatewayAcceptanceTest.test_gateway_shutdown_cancels_active_provider_request -v` | PASS on focused rerun |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_gateway_acceptance -v` | PASS, 4 tests, including active-request shutdown |
| `.venv/bin/python -m unittest scripts.test_acceptance.Acceptance.test_openapi -v` | PASS |
| `.venv/bin/python -m unittest discover -s services/tts/tests -p 'test_*.py' -v` | PASS, 22 tests |
| `git diff --check` | PASS for tracked changes; new untracked artifacts were separately reviewed for whitespace |

The full-suite shutdown result is intermittent: the focused test and full
Gateway acceptance module both passed afterward, with no source change. Treat
the first run as a test flake/uncertain signal, not proof of a runtime defect.
**OBSERVED:** a second `make verify PYTHON=.venv/bin/python` completed without
failure after the focused reruns; all later build, governance and dependency
lock targets ran. Retain the first-run failure in this record because one
passing repeat does not explain why the signal was intermittent.

**INTERPRETATION:** deployment is blocked because the running Gateway cannot
reach Ollama on the existing topology and a dirty-tree image is not suitable
as a release. Groq connectivity is also absent; this is compatible with the
required `allow_cloud:false` initial configuration. The overlay is a prepared
shape, not a validated production network solution.

**NOT ESTABLISHED:** any deployed M05B behavior, live STT/TTS or local text
transformation after deployment, a valid Gateway-to-Ollama path, Groq HTTPS
compatibility from the product network, or concurrent local-Qwen/TTS safety.
Stage 2A lexical invariant failures remain 7/9 at both 4K and 8K; generated
text needs operator/user review. The exact rollout and rollback commands and
operational gates are in [Stage 2C readiness](stage-2c-deployment-readiness.md).

## Stage 2C Gateway network diagnosis — 2026-10-22

**OBSERVED — topology and listener:** Gateway currently has three networks:
`speech-platform_publish` (`172.28.0.2/16`, gateway `172.28.0.1`,
non-internal, masquerading disabled), `speech-platform_stt_private`
(`172.30.0.3/16`, internal), and `speech-platform_tts_private`
(`172.29.0.3/16`, internal). STT and TTS each share only their respective
internal network with Gateway. Ollama is not Compose-managed by this project;
it is alone on Docker default `bridge` at `172.17.0.2`, with port 11434
published on `0.0.0.0` and `::`. Its `OLLAMA_HOST` is `0.0.0.0:11434`.
Gateway's route table has the three connected networks plus a default route
via `172.28.0.1`; it has no `172.17.0.0/16` connected route. Host
`net.ipv4.ip_forward=1`, IPv6 forwarding is 0.

**OBSERVED — name resolution and connectivity, no inference:**

| Probe | Result |
| --- | --- |
| Host `127.0.0.1:11434/api/version` | HTTP 200, Ollama 0.33.1 |
| Host `192.168.1.106:11434/api/version` | HTTP 200 |
| Host `172.17.0.2:11434/api/version` | HTTP 200 |
| Current Gateway `host.docker.internal` lookup | Docker DNS `127.0.0.11` returned NXDOMAIN; no `ExtraHosts` mapping |
| Gateway to `172.28.0.1:11434` with proposed host-gateway mapping | TCP timeout |
| Gateway to Ollama `172.17.0.2:11434` | TCP timeout |
| Gateway DNS lookup for `api.groq.com` | A and AAAA records returned |
| Gateway TCP to Groq IPv4 and IPv6 port 443 | Both failed |
| Host TCP to Groq IPv4 port 443 | Connected |

**INTERPRETATION:** local Ollama failure is not a model/listener failure. The
current hostname is absent, but mapping it to `172.28.0.1` still leaves the
host/bridge port path unavailable. Direct access to `172.17.0.2` crosses
separate Docker bridge networks. Host packet forwarding is enabled, but Docker
filtering can still isolate bridges. The most direct low-scope fix is a new
internal user bridge attached only to Gateway and Ollama, using Docker DNS
alias `ollama`; change the candidate endpoint to
`http://ollama:11434/api/generate`. This requires an additive live network
attachment to the shared Ollama container but no Ollama configuration change,
container replacement, or change to existing clients' bridge/published-port
path. STT/TTS private networks remain unchanged.

**INTERPRETATION — cloud egress:** host TCP to Groq succeeds; container DNS
also succeeds, but Gateway's publish network explicitly sets
`com.docker.network.bridge.enable_ip_masquerade=false`. This prevents outbound
source NAT, so replies to private container address `172.28.0.2` have no
external return route. The evidence strongly identifies disabled masquerading
as the egress cause. Do not enable it to solve local Ollama access. If Groq is
authorized in a future change, use a separate Gateway-only egress design with
explicit outbound restrictions; cloud remains disabled.

**NOT ESTABLISHED:** the exact host firewall/Docker filter rule dropping the
host-gateway or cross-bridge packets. `nft list ruleset`, `iptables -S` and
`iptables-save` failed with permission errors because this environment lacks
network-administration capability. An additional firewall filter cannot be
excluded. No container, network, route, NAT, firewall or service configuration
was modified. Diagnostic containers were ephemeral and performed only
read-only version/TCP probes.

The readiness record compares dedicated Ollama networking, narrowly scoped
host-gateway forwarding and a Gateway-only egress network, and gives the
operator-gated verification/rollback sequence. The recommended network must
first be authorized and validated with DNS plus `/api/version`; this establishes
transport only and must not load a model. Deployment still requires a clean
candidate build, Stage 2A user review and explicit deployment authorization.
Groq egress is not a prerequisite while `allow_cloud:false` remains in force.

## Stage 2B Groq live qualification and report-finalization regression — 2026-10-22

**OBSERVED — verification before live calls:**

| Command | Result |
| --- | --- |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_controller scripts.test_m05b_stage2b_lifecycle -v` | PASS, 19 tests |
| `.venv/bin/ruff check private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS |
| `.venv/bin/ruff format --check private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS, both files formatted |
| `.venv/bin/python -m py_compile private/m05b/stage2b/run_live.py scripts/test_m05b_stage2b_controller.py` | PASS |
| `go test ./internal/config ./internal/texttransform ./internal/gateway -count=1` | PASS |
| `go build -o /tmp/m05b-stage2b-preflight-gateway ./cmd/gateway` | PASS |
| `git diff --check` | PASS |

The controller regression tests reproduce the former `in_progress` report bug,
assert successful response metadata and latency are durably copied, preserve
partial failure evidence, and reject marking an incomplete request successful.
The controller-generated isolated Gateway was also freshly built and passed
`--check-config` before either live request.

**OBSERVED — live qualification:** exactly two sequential explicit Groq
requests were sent using the synthetic payloads: `groq-qwen` returned HTTP 200
in 0.235598 seconds, and `groq-gpt-oss` returned HTTP 200 in 0.360139 seconds.
Both report entries finalized as `success` with status, latency, public model
and provider metadata, generated=true, and fallback=false. Authentication
succeeded. The response bodies are preserved privately for review and are not
included in this tracked record. No retry, fallback, local inference or
additional provider request occurred.

The isolated profile alone enabled cloud access. The private key remained in
the existing mode-0600 file and was supplied only through the isolated Gateway
environment. The public responses contained no reasoning text or internal
provider metadata. Configured reasoning options were `none` for Qwen and `low`
for GPT-OSS; offline adapter tests validate their serialization. Successful
live completions establish protocol compatibility for the two configured
requests, but raw upstream payloads were not retained to establish provider
internals or reasoning-control interpretation independently.

Production Gateway, STT and TTS were healthy before and after, with unchanged
container IDs, start times and zero restarts. GPU remained at 2,216 MiB used /
12,694 MiB free and Ollama residency remained empty. The isolated Gateway
exited with status 0, was reaped, and no process remained; controller exit
status was 0 with no cleanup or monitor error.

**NOT ESTABLISHED:** broad transformation quality, live automatic model
selection/fallback, quota/cost behavior, deployment readiness and Stage 2C
readiness. Stop for operator review; these results do not authorize deployment
or milestone advancement.

## Stage 2B consolidated offline integration acceptance — 2026-10-22

**OBSERVED:** `scripts/test_m05b_stage2b_gateway_acceptance.py` builds and
owns a fresh compiled Gateway child and exercises the public transformation
API with deterministic loopback Ollama and OpenAI-compatible fake providers.
The fake cloud endpoint uses an ephemeral certificate trusted only by the
test Gateway process; certificate verification remains enabled. Four
process-level acceptance tests passed, covering all selection policies,
fallback and response metadata, model/provider rate-limit scope, explicit
selection without substitution, both cloud restrictions, authentication
before provider calls, missing credentials with speech readiness intact, raw
passthrough, provider errors, invalid responses, total timeout, and active
request cancellation during Gateway shutdown. Evidence is sanitized and
private at `private/m05b/stage2b/offline-gateway-acceptance.json`.

Existing Go tests cover caller cancellation, service shutdown, provider
timeouts and bounded fallback, invalid/oversized provider responses, and
credential handling. No live provider, production service, STT/TTS model, or
GPU inference was used for these tests.

**OBSERVED — final verification:**

| Command | Result |
| --- | --- |
| `.venv/bin/python -m unittest scripts.test_m05b_stage2b_gateway_acceptance -v` | PASS, 4 compiled-Gateway integration tests |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0; Go vet/race tests, Ruff, config/static Compose, release checks, all discovered script and STT tests, build, governance and lock checks |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest services.tts.tests.test_tts -v` | PASS, 22 TTS/SSML tests |
| `git diff --check` | PASS |

The full verification includes the new acceptance controller through Python
test discovery. The standalone TTS/SSML suite was run separately because it
is not included in `make verify`. Verification did not start or mutate
services.

**INTERPRETATION (at the time of this entry):** Stage 2B technical integration
acceptance was ready for operator review. The operator later accepted the
bounded Stage 2B results on 2026-10-22. This is not a production deployment or
M05B closeout result.

**NOT ESTABLISHED:** production resource isolation, live quota/rate-limit
behavior, broad translation quality, all-model lexical invariants,
deployment safety, or Stage 2C readiness. Stage 2A quality results were later
accepted with limitations: the lexical invariant failures remain failed and
local Qwen is retained only for user-reviewed transformations.

## Stage 2C Gateway-to-Ollama network qualification — 2026-10-22

Scope was limited to the authorized additive Docker network, a candidate-only
Compose/config update, read-only connectivity checks and documentation. No
production Gateway attachment, Gateway deployment, service restart, inference,
model load/unload, or cloud request occurred.

**OBSERVED — preflight:** Docker context `default` targeted host `llm` on
Docker Engine 29.1.3. Network name `speech-platform_ollama_private` did not
exist. Existing Docker networks used `172.17.0.0/16` through
`172.30.0.0/16`; no subnet overlapped the Docker-assigned `172.31.0.0/16`.
Ollama container ID was
`72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba`, started
`2026-10-17T09:04:51.619335472Z`, running with restart count 0, attached to
Docker `bridge`, and published port 11434 on `0.0.0.0` and `::`. Before the
change Gateway, STT and TTS were healthy with restart count 0; Gateway
`/readyz` returned HTTP 200.

**OBSERVED — network change:**

| Command/action | Result |
| --- | --- |
| `docker network create --driver bridge --internal speech-platform_ollama_private` | PASS; ID `f45063e992ba78f6c2499173af314d03d3b917349bd7ef8b15da7ea6f39c3fbd`; bridge, `internal=true`, subnet `172.31.0.0/16`, gateway `172.31.0.1` |
| `docker network connect --alias ollama speech-platform_ollama_private ollama` | PASS; Ollama received `172.31.0.2`, alias `ollama`, and retained its original `bridge` attachment |
| Disposable DNS/API probe, ID `65a578a73f99d89fd9b03de34c641d92ad7bc4b76e0c3b1e1aeccf3ee008e746` | PASS; attached only to the new network; `ollama` resolved to `172.31.0.2`; `GET /api/version` returned HTTP 200, `0.33.1`; stopped and removed |
| Disposable external DNS/HTTPS probe | External name resolution timed out (curl exit 28) from the internal-only network |
| Disposable direct-IP HTTPS probe to `1.1.1.1:443`, ID `346ea8e7129107e9fcc32b3174efa1ffcfc2cd9bcd98d810177b639b6e9dd87a` | Connection failed immediately (curl exit 7); TLS verification was not disabled; probe removed |

After probe cleanup the new network had only Ollama attached. Host
`GET /api/version` returned `0.33.1`; host `GET /api/ps` returned
`{"models":[]}`. No inference/model lifecycle endpoint was called. An
immediate pre-change `/api/ps` capture was not made, so identical model
residency before and after is **NOT ESTABLISHED**.

**OBSERVED — candidate overlay:** `deployments/compose/compose.m05b-stage2c.yaml`
declares `speech-platform_ollama_private` external and adds only that network
to the Gateway service. Rendered configuration retained Gateway's existing
`publish`, `stt_private`, and `tts_private` networks and its
`127.0.0.1:8080` published bind; `extra_hosts` is empty. The private candidate
config endpoint is `http://ollama:11434/api/generate`; `selection.allow_cloud`
remains `false`. Compose rendering exited 0 using validation-only placeholder
environment values. No rendered configuration was applied to a service. The
previous candidate overlay/config versions were preserved mode 0600 in
`private/m05b/stage2c/pre-network-rollback-20261022/`.

**OBSERVED — production services after:** Gateway, STT and TTS retained their
preflight container IDs, start times, network attachments, healthy status and
restart count 0. Gateway `/readyz` remained HTTP 200. Ollama retained its
container ID, start time, bridge attachment, host port bindings and restart
count 0, and was running. The production Gateway was not attached to the new
network. Existing Ollama network/configuration and Dify resources were not
changed.

The final inspection found only Ollama attached to the dedicated network; no
diagnostic probe container remained. Host `/api/version` returned 200 and
`/api/ps` returned an empty model list. One combined `docker inspect` template
initially failed because Ollama has no `.State.Health` field; separate product
and Ollama inspection templates then exited 0 and reported the expected
identities and states.

**OBSERVED — offline verification:** the candidate image's
`--check-config` passed with `--network none`, a read-only root filesystem and
the private config mounted read-only. The full accepted Compose source set
(`compose.yaml`, the existing rollback overlay and the Stage 2C overlay)
rendered successfully using the private `.env`; only sanitized selected
fields were printed. It retained the expected Gateway networks and loopback
port and kept STT/TTS image references unchanged. Link validation via
`scripts.validate_governance.validate_links`, trailing-whitespace checks on
the two changed milestone documents, and `git diff --check` all exited 0.

**INTERPRETATION:** direct DNS, TCP and read-only HTTP connectivity are
qualified from an isolated probe attached only to the internal bridge. This
supports attaching the future Gateway through the candidate overlay; it does
not prove Gateway runtime behavior or authorize its deployment. Cloud remains
disabled in candidate configuration, and the new internal network supplies no
general external route to clients attached only to it.

**NOT ESTABLISHED:** Gateway-to-Ollama connectivity after Gateway recreation,
live text transformation, model quality, unchanged model residency at the
instant of attachment, or deployment readiness. The existing Ollama published
port remains bound to all host interfaces, unchanged by this task. This result
does not close M05B or advance to deployment.

## Stage 2C Ollama network provisioning automation — 2026-10-22

**OBSERVED:** added idempotent deployment tooling to the canonical
`make plan` / `make install` workflow. When an enabled local Ollama model is
configured, preparation validates or creates an external internal bridge and
attaches the existing running Ollama container using alias `ollama`. It keeps
Ollama's existing network attachments and published ports. The optional
Compose overlay adds only the external network to Gateway. STT/TTS-only and
cloud-only configurations do not include or prepare the Ollama network.
`OLLAMA_CONTAINER_NAME` and `OLLAMA_NETWORK_NAME` are configurable in the
private `.env`, defaulting to `ollama` and
`speech-platform_ollama_private`.

The Gateway adds `--check-ollama`, a bounded DNS/TCP/read-only `/api/version`
check used by installation after service readiness. It does not perform model
loading or inference. A Gateway-only install is available with
`make install SERVICE=gateway` and requires healthy existing STT/TTS workers.
The runbook documents fresh install prerequisites, upgrades, cloud-disabled
behavior, failures, Gateway rollback, and separately reviewed network cleanup.

**OBSERVED — exact verification:**

- `.venv/bin/python -m unittest scripts.test_ollama_network scripts.test_product_deployment -v` — PASS, 22 tests.
- `go test ./internal/texttransform ./cmd/gateway` — PASS.
- Ruff lint and format checks for the new/changed deployment Python modules — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS on rerun, including all Go vet/race/build checks, configuration and Compose checks, 513 repository Python tests, 64 STT worker tests and governance/lock checks.
- `git diff --check` — PASS.
- Root Compose plus `deployments/compose/compose.ollama.yaml` rendered and asserted Gateway's four expected networks, unchanged STT/TTS private attachments, external network name and loopback publication.

The first full verification attempt caught the application-source static guard
for hardcoded deployment URLs. The probe was adjusted to use configured
endpoint data and explicit port; the subsequent full verification passed. No
Docker mutation, service restart, model inference, cloud request or production
configuration change was performed in this task.

**INTERPRETATION:** this automates network provisioning for future installation
and upgrade operations without making SpeechPlatform responsible for Ollama's
container/model lifecycle. Failure handling intentionally leaves externally
managed resources untouched for operator inspection. Network retirement is
never automatic.

**NOT ESTABLISHED:** production Gateway deployment through the new path, a
clean release build, runtime connectivity from the deployed Gateway, live
transformation, cloud egress, or Stage 2A model-quality acceptance. Stage 2C
remains subject to the existing operator gates and does not advance or close
M05B.

## M05B release-candidate preparation — 2026-10-22

**OBSERVED — source review:** the deployment installer previously always
validated and mounted `configs/gateway.yaml`, which leaves the optional text
service disabled. This prevented the canonical `make plan` / Gateway-only
install path from selecting the private local-only M05B configuration. Added an
optional `GATEWAY_CONFIG` setting (default remains `configs/gateway.yaml`),
restricted to an in-repository regular file without symlink or parent-directory
traversal. Compose mounts the selected file read-only. Network selection,
preflight validation and `--check-ollama` now use that same selected
configuration. No Docker resource or service was changed.

**OBSERVED — local-only candidate:** the ignored private candidate config
validated successfully with `go run ./cmd/gateway --config
private/m05b/stage2c/gateway.yaml --check-config`. It enables text transformation
and has `allow_cloud=false`. The file is ignored by Git and is under the
mode-0700 private evidence tree; its file mode is 0644. The candidate image
listed in the readiness record predates these source changes and was built from
a dirty tree, so it is not a reproducible release artifact.

**OBSERVED — verification commands:**

| Command/check | Result |
| --- | --- |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0; Go vet, Ruff, Gateway/STT/TTS config checks, Compose checks, OpenAPI/governance/release checks, `go test -race ./...`, 515 Python script tests, 64 STT tests, Go build, Python compilation and lock checks. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest services.tts.tests.test_tts -v` | PASS, 22 TTS/SSML tests. |
| `.venv/bin/ruff format scripts/product_deployment.py scripts/test_product_deployment.py` and `.venv/bin/ruff check scripts/product_deployment.py scripts/test_product_deployment.py` | PASS. |
| `.venv/bin/python -m unittest scripts.test_product_deployment scripts.test_ollama_network -v` | PASS, 24 tests including `make plan` local-Ollama reporting, missing/conflicting network, valid reuse, attachment failure, idempotency, config-path security and conditional Compose overlay. |
| Default and Ollama-overlay `docker compose ... config --quiet` rendering | PASS; optional overlay preserves loopback publication and STT/TTS private networks. |
| Candidate-config Compose render and Gateway `--check-config` | PASS; selected private config, four Gateway networks including Ollama, unchanged STT/TTS network sets, loopback-only publication. |
| `git diff --check`; `scripts.validate_governance.validate_links` via repository verification | PASS. |

No image was built from the modified source because repository governance
requires separate operator authorization before commit, and the worktree is
not clean. No production or shared container was started, recreated or
restarted; no live inference or cloud transmission occurred. Private
qualification artifacts and generated binaries remain ignored and were not
staged.

**INTERPRETATION:** the source is ready for a reviewed checkpoint after
separate commit authorization. The candidate image must be rebuilt and its
image/config identities re-recorded from that clean source revision before any
deployment review. The exact proposed Gateway-only rollout and rollback are in
[Stage 2C readiness](stage-2c-deployment-readiness.md#12-release-candidate-proposal--2026-10-22).

**NOT ESTABLISHED:** reproducible release image identity, production Gateway
runtime connectivity, live post-deployment behavior, or deployment readiness.
No commit, production rollout or M05B closeout is authorized by this
verification.

## Stage 2C approved release image and controlled deployment preflight — 2026-10-23

**OBSERVED — source and image:** HEAD was the approved commit
`c3f0079227af573f7715640afa5b229a22c46ab6`; tracked files and index were
clean, with six M06 planning files untracked and preserved. The image was
built with
`SOURCE_REVISION=c3f0079227af573f7715640afa5b229a22c46ab6 docker compose
--env-file .env.example -f compose.yaml build gateway`. The tag is
`speech-platform-gateway:c3f0079227af573f7715640afa5b229a22c46ab6`, image ID
and RepoDigest
`sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159`,
platform `linux/amd64`, created `2026-10-23T05:28:13.060921951Z`. OCI
revision/service labels matched the approved source. Docker client/server
29.1.3 and Compose v5.6.0 were observed.

**OBSERVED — candidate offline checks:** image `--check-config` passed with
the private candidate config and `--network none`; config SHA-256 was
`0c5e22b499187dd413a9b47103db833b91e6869809dddf113cc8afc45c165c95`. The
config selected local Ollama, 8192 context and 5s keep-alive with cloud
disabled. Base and candidate Compose rendering passed: Gateway remained
loopback-bound and attached to the expected networks, while rendered STT/TTS
definitions were unchanged.

**OBSERVED — live preflight:** at 2026-10-23 05:35 UTC, Gateway, STT and TTS
were running and healthy with restart count 0. Their IDs/start times were
unchanged from the prior deployment baseline; Gateway `/healthz` and
`/readyz` returned HTTP 200. Gateway still used M03B image ID
`sha256:d4cfd90de08651cc79e97632ab6ea904a2c0951f1e9e7ff562c923e1242241b9`
and loopback port 8080. Ollama was running with restart count 0, retained its
original `bridge` and private network attachments, and had no model resident.
Host `GET /api/version` returned HTTP 200. The private network was internal
and contained only Ollama before Gateway deployment. GPU baseline was 2,216
MiB used / 12,694 MiB free of 15,360 MiB. The M03B rollback tag was present
and resolved to the exact currently running Gateway image ID; its Compose
overlay rendered a Gateway-only rollback without the Ollama network.

**OBSERVED — deployment gate:** `.env` initially had no `GATEWAY_CONFIG`.
The candidate path was added temporarily with mode 0600 preserved. Running
`make plan PYTHON=.venv/bin/python` returned exit 2 during read-only model
integrity verification: the configured model store is root-owned and the
installer reported that `sudo -v` is required. No model files or Docker
resources were changed. The temporary `.env` setting was removed, restoring
the prior file contents and mode. `make install SERVICE=gateway` and all
post-deployment checks were not run. The installer also requires a clean Git
worktree; the six untracked M06 planning files were not hidden or removed.

Private sanitized evidence is in
`private/m05b/stage2c/deployment-preflight-20261023T053556Z/report.json`
(mode 0600). **INTERPRETATION:** artifact, config and rollback identities
matched; canonical preflight could not complete without sudo authorization.
The production Gateway remains on M03B. **NOT ESTABLISHED:** candidate runtime
health, production-namespace Ollama connectivity, live transformation,
post-inference GPU recovery, or natural model expiry through the deployed
Gateway. Resume only after model-integrity authorization and a clean-source
install path are available; preserve all M06 files and recheck candidate
identities before `make install`.

## Stage 2C deployment preflight blocker investigation — 2026-10-23

**OBSERVED — deployment-tooling review:** `scripts.product_deployment.checks`
unconditionally runs release model verification and the TTS model verifier
for both `plan` and `install`, including `SERVICE=gateway`. The read-only
check loads repository-pinned manifests, traverses the content-addressed
STT/TTS artifact directories, validates file sets and sizes, and hashes all
payload bytes. The store root is owned by `root:stt-model-reader`, mode 2710;
the current `master` process is not in GID 988 and cannot traverse the digest
directories. No artifact files, permissions or ownership were modified.
Historical M01E checks are not accepted by the current helper as current
payload attestations. The supported minimum authorization is interactive
`sudo -v`; the helper then invokes only its existing read-only checker
commands as root via `sudo -n`. The preflight check is not needed to mutate a
Gateway-only container, but it is a current mandatory deployment gate and was
not bypassed.

**OBSERVED — worktree/install semantics:** only the current checkout appears
in `git worktree list`. The installer checks `git status --porcelain` for a
clean source tree. It also checks that the running `speech-platform` Compose
project's recorded config path equals the resolved `compose.yaml` under its
own `ROOT`. Docker records `/home/master/speech-platform/compose.yaml`; a
detached worktree at another path will fail project-ownership validation (or
be a different project and collide with host port 8080). The six M06 files
and two modified Stage 2C docs therefore cannot be left in the current tree
while running the installer, and no alternate existing release checkout is
available. The readiness record now describes a private backup/restore
procedure at the original canonical path; it does not alter source checks or
commit the documentation.

**OBSERVED — image behavior:** `install` unconditionally invokes Compose
`build gateway` before `up`; there is no no-build or expected-image-ID option.
The approved image/tag remains locally present, but exact identity after an
installer rebuild is not established and the helper does not assert the
expected ID between build and `up`. Direct `compose up --no-build` was not
used because it bypasses installer checks and the post-start read-only
Ollama probe. No application/deployment tooling change was made. A validated
no-build/image-ID option would need focused regression tests and separate
implementation/commit approval if exact artifact reuse is required.

**OBSERVED — offline verification:**

| Command/check | Result |
| --- | --- |
| `.venv/bin/python -m unittest scripts.test_ollama_network scripts.test_product_deployment -v` | PASS, 24 tests. |
| Candidate image `--check-config` with private config, `--network none`, read-only filesystem and dropped capabilities | PASS, exit 0. |
| `make config PYTHON=.venv/bin/python` | PASS; Gateway, STT, TTS and product configuration validators. |
| `make compose-check PYTHON=.venv/bin/python` | PASS; base/optional Ollama and supported CPU/CUDA Compose rendering checks. |
| `make release-check PYTHON=.venv/bin/python` | PASS; v0.1.2 descriptor validation. |
| Candidate Gateway Compose render assertion | PASS after correcting the assertion to the rendered network-map shape; render retained loopback binding, external Ollama network and isolated worker network sets. The first ad-hoc assertion expected arrays and failed without affecting infrastructure. |
| `make governance-check PYTHON=.venv/bin/python` | PASS; structural/reference checks and 2 governance tests. |
| `git diff --check` | PASS. |

No `make install`, container lifecycle operation, Docker network mutation,
model-store access with privilege, inference, or cloud request was run in this
investigation. **INTERPRETATION:** the model permission issue can be resolved
without data changes by using the existing privileged read-only fallback;
the local workspace can be made clean temporarily with a private backup and
restoration at the same Compose path. Exact reuse of the approved image is
still unsupported by the installer and needs a separate decision. **NOT
ESTABLISHED:** a successful privileged model check, post-check deployment
plan, installer build identity, candidate deployment, or runtime behavior.

## Verified no-build installer implementation — 2026-10-23

**OBSERVED — focused regression checks:**

| Command | Result |
| --- | --- |
| `.venv/bin/python -m py_compile scripts/product_deployment.py scripts/test_product_deployment.py` | PASS. |
| `.venv/bin/python -m ruff format scripts/product_deployment.py scripts/test_product_deployment.py` | PASS; formatted 2 files. |
| `.venv/bin/python -m ruff check scripts/product_deployment.py scripts/test_product_deployment.py` | PASS. |
| `.venv/bin/python -m ruff format --check scripts/product_deployment.py scripts/test_product_deployment.py` | PASS. |
| `.venv/bin/python -m unittest scripts.test_product_deployment scripts.test_ollama_network -v` | PASS; 32 tests. |
| `make -n plan SERVICE=gateway NO_BUILD=1 PYTHON=.venv/bin/python` | PASS; expands to Gateway-only `plan --no-build`. |
| `make -n install SERVICE=gateway NO_BUILD=1 PYTHON=.venv/bin/python` | PASS; expands to Gateway-only `install --no-build`. |
| `make -n install SERVICE=stt NO_BUILD=1 PYTHON=.venv/bin/python` | Expected rejection: no-build requires `SERVICE=gateway`. |
| `make -n status SERVICE=gateway NO_BUILD=1 PYTHON=.venv/bin/python` | Expected rejection: no-build is limited to plan/install. |
| `make compose-check PYTHON=.venv/bin/python` | PASS; base, optional Ollama and supported worker Compose renders. |
| `make config PYTHON=.venv/bin/python` | PASS; Gateway, STT and TTS configuration validation. |
| `go run ./cmd/gateway --config private/m05b/stage2c/gateway.yaml --check-config` | PASS; private local-only candidate config. |
| `make verify PYTHON=.venv/bin/python` | PASS; race-enabled Go tests, 523 repository script tests, 64 STT tests, build, lint/format, config, Compose, governance and dependency-lock checks. |
| `git diff --check` | PASS. |

The focused installer coverage verifies exact image ID, local tag availability,
revision/service/role/runtime labels and platform; missing, malformed,
ambiguous and mismatched image identities; no-build scope validation; normal
build-path preservation; plan identity reporting; and Gateway-only install
without build/pull while retaining worker-health, Ollama-network preparation,
readiness and read-only provider checks. No provider inference, production
container operation, Docker network mutation, model-store check, deployment or
commit occurred.

**INTERPRETATION:** the implementation is ready for a separate commit review.
It is not yet available to a clean release checkout until reviewed changes are
committed. Deployment still requires explicit operator authorization, the
interactive `sudo -v` preflight, clean canonical worktree preparation described
in the readiness record, and a successful installer plan. **NOT ESTABLISHED:**
actual no-build image inspection against the live Docker daemon through this
new code path, successful privileged preflight, deployment, or runtime behavior.


## Stage 2C production smoke-test attempt — 2026-10-23

**OBSERVED — target and preflight (execution environment, 2026-10-23 UTC):**
read-only Docker inspection found the production Gateway running image
`sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159`,
healthy with restart count 0. Gateway `/healthz` and `/readyz` each returned
HTTP 200. STT and TTS were healthy with restart count 0; their observed
container and image identities are retained in the private report. The
operator reports that both workers retain their original image IDs. The
mounted Gateway configuration matched
`private/m05b/stage2c/gateway.yaml` (SHA-256
`0c5e22b499187dd413a9b47103db833b91e6869809dddf113cc8afc45c165c95`), with
`allow_cloud:false`, logical model `local-qwen` mapped to
`host-ollama` / `qwen3.5:9b-q4_K_M`, and finite `keep_alive: 5s`. Read-only
Ollama `/api/ps` showed no resident model. GPU baseline was 2,216 MiB used,
12,694 MiB free of 15,360 MiB, 0% utilization, 34 C.

**OBSERVED — authentication blocker:** the running Gateway container had an
empty `SPEECH_API_TOKEN`; `.env` had no token value, and the existing private
Stage 2B auth values did not match the running Gateway configuration.
Credential values were not recorded. The smoke controller stopped before
issuing the request. Its private report records `request_count_sent: 0`. No
unauthenticated request, retry, additional inference, TTS operation, service
restart, Docker mutation, deployment or infrastructure change occurred.
Private evidence:
`private/m05b/stage2c/production-smoke-20261023T063422Z/report.json` (mode
0600); the bounded runner is also private in the same directory hierarchy.

**NOT ESTABLISHED:** HTTP 200 for a transformation, public response identity,
`generated`/fallback flags, nonempty output, reasoning-leak review, material
fact and uncertainty preservation, request latency, GPU use during inference,
natural model expiry, or post-request worker identity/health. Because no
request was sent, the final production smoke test is **BLOCKED**, not PASS.
Cloud access remained disabled in the mounted configuration during the
preflight. Stop for operator review before any further attempt; do not reuse a
mismatched credential. M05B Stage 2C and milestone closeout remain open.


## Stage 2C production local-transformation smoke — 2026-10-23

**OBSERVED — request and response:** after the private controller was corrected
to follow the effective optional-auth configuration, it sent exactly one
synthetic `POST /v1/text/transformations` request to the production Gateway.
The effective token was empty, so no Authorization header was sent. The request
explicitly selected `local-qwen`, set `local_only:true`, mode `written`, format
`normal`, and target language `none`. HTTP status was 200; public metadata was
model `local-qwen`, provider `host-ollama`, `generated:true`,
`fallback_occurred:false`. Output was nonempty (159 characters), matched the
public response schema, and contained no reasoning markers or internal
provider fields. No retry or fallback occurred. The synthetic request and full
response remain private.

**OBSERVED — meaning review:** the output retained the November 18 date, the
$1,250 budget, and uncertainty about whether the supplier can meet the
deadline. However, delivery timing may sound more definite than the source
supports, strengthening an expectation into a firmer schedule. Overall meaning
preservation is **PARTIAL, not PASS**; this issue is called out for operator
review. The generated text is not reproduced here.

**OBSERVED — network and resource recovery:** the in-container read-only
Gateway Ollama check passed DNS, TCP and `GET /api/version`. The mounted config
remained the Stage 2C config with `allow_cloud:false`, model `local-qwen`,
provider `host-ollama`, and `keep_alive:5s`. The model was observed resident
during inference and absent 5.84 seconds after the HTTP response completed; no
unload command was sent. GPU baseline was 2,216 MiB used / 12,694 MiB free.
Sixteen approximately one-second passive samples recorded a sampled peak of
8,638 MiB used, minimum free 6,272 MiB and maximum utilization 76%. After
expiry, GPU memory returned to 2,216 MiB used / 12,694 MiB free. Samples are
host-wide measurements and do not establish an instantaneous peak. The raw
sampler phase label failed to transition during the POST; raw samples were
preserved and a separate private file classifies them by UTC request boundaries
(1 pre-request, 9 inference, 6 natural-expiry samples). The 8,638 MiB peak was
sampled during the request and remained at that level in cooldown. Cloud access
remained disabled and the request used only the local provider.

**OBSERVED — service preservation:** the approved Gateway image ID was
`sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159`.
Gateway `/healthz` and `/readyz` returned HTTP 200 after the request. Gateway,
STT and TTS container identities, image IDs, start times, health and restart
counts matched the before-request snapshot; all remained healthy with zero
restarts. No STT/TTS inference or TTS cold-load occurred.

**OBSERVED — controller verification:** `PYTHONDONTWRITEBYTECODE=1 python3
-m unittest discover -s private/m05b/stage2c -p 'test_auth_policy.py' -v`
passed three cases covering absent-token header omission, YAML token use when
environment is empty, and nonempty environment override. Syntax checks passed
for the private controller and helper. The controller change is private and
did not weaken Gateway auth enforcement.

| Command | Result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 python3 private/m05b/stage2c/run-production-smoke.py` | Completed exactly one production POST; HTTP 200 and technical routing/metadata/resource-recovery/service checks passed. Manual meaning result is PARTIAL because of the possible arrival-modality shift. No retry. |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s private/m05b/stage2c -p 'test_auth_policy.py' -v` | PASS; 3 offline tests. |
| `git diff --check` | PASS. |
| Local Markdown link check for the three updated M05B records | PASS. A broader link check on `PLANS.md` still reports its existing links to `docs/milestones/M06/plan.md` and `docs/adr/0022-model-lifecycle-predictive-warmup.md` unresolved while those planning files are preserved in the private Stage 2C backup; those files were not moved or changed by this task. |

Private detailed evidence (mode 0600 files under a mode 0700 directory):
`private/m05b/stage2c/production-smoke-20261023T093750Z/`. **INTERPRETATION:**
transport, routing, local-only provider selection, bounded sampled GPU use,
natural expiry and service preservation passed this run. Semantic acceptance
remains partial because delivery timing may sound more definite than the source
supports. **NOT
ESTABLISHED:** broader transformation quality, concurrent GPU behavior, TTS
cold-load safety, or long-duration production behavior. No services were
restarted, no Docker/network configuration was changed, no cloud call occurred,
and M05B remains open pending operator review.

## M05B final closeout verification — 2026-10-23

**OBSERVED — final requested checks:**

| Command / check | Result |
| --- | --- |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0. Lint, format, Gateway/STT/TTS config validation, Compose rendering, release validation, test suites, build, governance validation and lock checks completed. The Go/Python verification tests completed successfully. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s services/tts -p '*test*.py' -v` | PASS, 22 tests, including SSML parsing, synthesis, lifecycle and HTTP behavior. |
| `make release-check PYTHON=.venv/bin/python` | PASS; v0.1.2 release descriptor, three services, linux/amd64. |
| `make config PYTHON=.venv/bin/python` | PASS; Gateway, STT, product STT and TTS configuration checks. |
| `make compose-check PYTHON=.venv/bin/python` | PASS; Compose profiles and static policy checks. No services were started. |
| Local Markdown link check for `PLANS.md` and all M05B Markdown records | PASS, 11 files checked; restored M06 and ADR-0022 links resolve. |
| M06/ADR-0022 backup hash comparison | PASS; all five M06 planning files and ADR-0022 exactly match the preserved private copies. |
| `git diff --check` | PASS. |

**OBSERVED — read-only production health:** Gateway container `9fee4bc2beed`
uses approved image ID
`sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159`;
it is running, healthy, and has zero restarts. `/healthz` and `/readyz` each
returned HTTP 200. STT container `02110b11d58c` uses image ID
`sha256:41bea815f2c06a64205583255a8fd1e84937c858f2e6a65bfa784dca5e4b867e`;
TTS container `cbda986a4e9a` uses image ID
`sha256:0e39b7bfba33cc2a8ba6bbb459fad3fbd2c827fa51e9b2d774787517678e4c2d`;
both are running, healthy, and have zero restarts. These identities match the
pre-smoke records. The Gateway's read-only mounted config
reports `allow_cloud:false`. No inference was invoked during final verification.

**OBSERVED — planning restoration:** the five M06 planning files and proposed
ADR-0022 were restored from the private preservation directory. SHA-256 values
match the recorded backup hashes exactly. No M06 planning substance was edited.
M06 is the next planned milestone and remains inactive.

**INTERPRETATION — final acceptance:** M05B implementation/integration,
production Gateway deployment and technical production local-Qwen transformation
are PASS. Semantic preservation remains PARTIAL, accepted with limitations.
Stage 2A lexical-invariant failures remain failures. Cloud integration is
qualified in isolation while production cloud inference remains disabled.
Simultaneous local LLM inference and TTS cold-loading are not qualified.
Generated transformations require user review. The operator accepted these
limitations and closed M05B on 2026-10-23. This closeout does not authorize a
commit; commit authorization remains separate.

**NOT ESTABLISHED:** quality beyond the bounded Stage 2A corpus and one Stage
2C request, simultaneous local LLM/TTS cold-loading behavior, or long-duration
production behavior.
