# M05B verification

Status: **Stage 1 offline verification complete; live/runtime acceptance NOT ESTABLISHED.**

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
