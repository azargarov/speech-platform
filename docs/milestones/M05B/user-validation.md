# M05B operator validation plan

Status: **M05B closed with accepted limitations, operator-approved 2026-10-23.** Stage 1 and Stage 2B integration are PASS; Stage 2A lexical-invariant failures remain failures; Stage 2C deployment and technical production transformation are PASS with PARTIAL semantic preservation. Generated transformations require user review.

First review [plan.md](plan.md), [ADR 0021](../../adr/0021-configurable-text-transformation.md),
and Stage 1 evidence. M05A formal closeout is complete and remains unchanged.
Deployment and live qualification beyond the bounded Stage 2A scope require
their own reviewed scope, target identity, synthetic-data disclosure and
rollback inputs. No service failure is simulated
by stopping shared Ollama, revoking a real key or interrupting production Groq.

## Stage 1 — Operator acceptance (2026-10-22)

Review the completed Stage 1 implementation and actual test/full-verification
evidence in [verification.md](verification.md), including the dedicated
TTS/SSML suite (outside `make verify`). Check deterministic ordering, cloud
prohibition, explicit-selection behavior, bounded attempts, errors and metadata
against the plan. The operator's decision was **PASS**. The operator reports
`make verify PYTHON=.venv/bin/python` passed (exit 0), the dedicated TTS/SSML
suite passed (22 tests), `go test -race ./...` passed, `git diff --check` passed,
and Gateway configuration validation passed. These outcomes are operator-reported,
not rerun in this documentation/commit turn; see [verification.md](verification.md).

This acceptance is limited to Stage 1 offline implementation and did not itself
authorize deployment or live inference. A later request authorized Stage 2A; execution and its partial result are recorded below. This does not close M05B.

## Stage 2A — Local Qwen qualification

The operator authorized the bounded sequential 4K/8K comparison on 2026-10-22 and later accepted the harness root-cause analysis and offline regression evidence before requesting resumption. The resumed run completed all nine synthetic cases at each context, saved all 18 raw responses before validation, and recorded latency, token counts, passive GPU/residency samples, health checks, natural expiry and recovery. Seven outputs per context failed lexical quality invariants; manual review found the Swedish short output was in English and included an erroneous term, and the Russian short output had awkward ordering and omitted required details. Medium/long outputs were generally coherent, with exact date formatting causing some lexical-only flags. The text was identical between 4K and 8K for all nine cases. The operator accepts retaining local Qwen only as a candidate for user-reviewed transformations. The failed invariants remain failures; this decision is not a quality pass or a guarantee of meaning preservation or multilingual quality. See [stage-2a-qualification.md](stage-2a-qualification.md) for the complete evidence and limitations. Stage 2B is operator-accepted PASS; deployment, cloud calls, speech inference and M05B closeout remain separately gated.

## Stage 2 — Planned live setup and commands

After implementation and deployment authorization, prepare a private bounded
runner under `private/m05b/` that loads the configured loopback Gateway URL and
optional bearer token from the existing private mechanism. It must not print
credentials, expanded environment, prompts or provider bodies into tracked logs.
The runner sends one synthetic request per listed case, saves reviewed outputs
privately, and records only safe metadata in tracked verification.

Representative request commands, after setting `M05B_GATEWAY_URL` to the
reviewed loopback endpoint (and using the runner for authenticated requests):

```sh
curl --fail-with-body --max-time 245 "$M05B_GATEWAY_URL/v1/text/transformations" \
  -H 'Content-Type: application/json' \
  --data '{"text":"The test delivery is still late; I am not certain why.","mode":"written","model":"local-qwen","local_only":true}'
curl --fail-with-body --max-time 245 "$M05B_GATEWAY_URL/v1/text/transformations" \
  -H 'Content-Type: application/json' \
  --data '{"text":"The test delivery is still late; I am not certain why.","mode":"diplomatic","target_language":"sv","model":"groq-qwen"}'
curl --fail-with-body --max-time 245 "$M05B_GATEWAY_URL/v1/text/transformations" \
  -H 'Content-Type: application/json' \
  --data '{"text":"The test delivery is still late; I am not certain why.","mode":"polite","target_language":"ru","model":"groq-gpt-oss"}'
```

These are future commands, not permission to execute. The latter two transmit
synthetic text to Groq; local-to-cloud fallback and cloud-first tests also may
transmit it. Do not substitute private transcripts or user audio. `curl`
examples demonstrate JSON only; do not put a bearer credential in shell history
or process arguments. The protected runner supplies it in memory.

Before recreating Gateway, prepare exact Compose commands using actual
captured image/config/overlay paths and project identity. The planned shape is
`docker compose --env-file <private-env> -f compose.yaml -f <reviewed-overlay>
up -d --no-deps --no-build --wait gateway`. Angle-bracket values are intentionally
unresolved until deployment inspection; they are not executable commands.
Record concrete rollout and matching rollback commands before execution.

## Live acceptance matrix

| Case | Setup / expected outcome | External text? |
| --- | --- | --- |
| Raw passthrough | Default options; exact whitespace/Unicode equality, null model/provider, generated/fallback false, no provider calls | No |
| Local inference | Explicit local-qwen, local_only true; final text, logical IDs, no fallback; measure cold duration and zero keep-alive release | No |
| Groq Qwen | Explicit groq-qwen, global cloud allowed, configured reasoning none; final response and no fallback | Yes, synthetic only |
| Groq GPT-OSS | Explicit groq-gpt-oss, reasoning low; final response and no fallback; no reasoning returned | Yes, synthetic only |
| Cloud-to-local fallback | Private test config: cloud first endpoint deliberately unreachable, next real local; success local, fallback true | No text reaches the failed endpoint; do not rely on this if any real cloud call is used |
| Local-to-cloud fallback | Private test config: local first unreachable, then real Groq; success cloud, fallback true | Yes, synthetic only |
| Cloud-model ordering | Private fake-server record plus authorized bounded real successes; both Groq models remain individually selectable | Real Groq cases only |
| Complete outage | Private config with all endpoints unreachable, bounded attempts and 503/504 as specified; no original-text success | No |
| Malformed response / deadline | Private local fake HTTP provider yields invalid/slow completion, enforce all-or-nothing output and total time | No |
| Explicit selection | Explicit failing alias does not contact another model/provider | Use local fakes |
| Cloud prohibition | Global false rejects explicit cloud; request local_only true tightens global true; zero cloud calls shown by controlled listener | No |
| Missing optional key | Private configuration with cloud allowed but missing Groq key: Gateway/check-config succeed, speech stays usable, enabled raw succeeds, inference skips unavailable provider or returns specified 503 | No |
| Caller authentication | Missing/invalid bearer on generated, raw, disabled and unavailable cases yields 401 with zero provider calls; valid token follows normal behavior | Use local fakes |
| Context limits | Qualify actual tokenizer/template bounds and context caps for each enabled model; exact-boundary synthetic cases fit, oversized explicit/all-model requests reject before calls; full input arrives without truncation | Cloud qualification uses synthetic text |
| Provider-wide 429 | Fake Groq endpoint returns unknown/provider scope: second Groq model never called; established model-only scope permits it; fresh request resets suppression | No |
| Cancellation and shutdown | Controlled client disconnect/timeout/service stop; no later fallback or admission after stopping, bounded local cleanup, record remote termination separately; subsequent speech and text recover | Synthetic only if real cloud used |
| Speech isolation | Before/after `/healthz`, `/readyz`, scoped Compose state and synthetic STT/TTS smoke via existing accepted procedures; unchanged worker IDs/start times/restarts | No cloud inference |
| Rollback | Restore captured Gateway image/config/networks; confirm baseline health and unchanged STT/TTS, Ollama and Dify identities | No |

Use isolated private config/fake listeners for fault injection; no new public
service or modification of existing provider runtime. Review English, Swedish,
Russian and mixed-language preservation using bounded M05A cases. Review mode
and translation combinations manually; record language switches and other
defects as accepted limitations or reasons to revise. No semantic fallback
or accuracy guarantee is inferred from transport success.

### Shared GPU acceptance

Execute the complete [plan section 8.1](plan.md#81-shared-gpu-qualification-and-production-restriction)
matrix, not only sequential inference. Record actual temporal overlap for STT
with active Qwen, cold TTS load during Qwen, and cold Qwen with resident TTS.
Keep the existing TTS memory guard and all worker configuration unchanged.
Record the 6,400/8,000 MiB conflict as a hypothesis to test, not a passing result.
Include cancellation, disconnect, timeout and Gateway shutdown, subsequent
requests, and observed Ollama unload/VRAM recovery after each outcome. Define
bounded repetitions, sampling/window/tolerance and abort criteria in the
reviewed run sheet before execution; abort on OOM, worker restart, unhealthy
speech or failure to recover within that window.

Use existing telemetry/read-only residency observations and operator-owned test
windows; do not kill shared inference or force-unload models belonging to other
clients. If safe overlap or actual release cannot be demonstrated, record a
failed/inconclusive qualification and leave local production models disabled
until a restricted operational policy is approved. Only an explicit operator
acceptance may adopt that restricted scope; do not label it unrestricted
coexistence or assume cloud capacity compensates automatically.

Record first-use/warm distinction, provider attempts, latency, finish state,
actual unload observations, speech results and errors. Keep payloads/results in
ignored private storage until operator review; remove them on the operator's
retention decision. Verify rollback and unchanged shared service identities.

## Stage 2B — Gateway integration qualification

The compiled-Gateway offline acceptance and bounded live provider
compatibility evidence are recorded in
[stage-2b-qualification.md](stage-2b-qualification.md) and
[verification.md](verification.md). The operator accepts the three live model
compatibility results. The final consolidated Stage 2B qualification is ready
for operator review. This does not authorize production deployment, shared
GPU concurrency testing, or M05B closeout.

## Decision record (current at closeout)

- Plan/ADR reviewer and date: **PENDING**
- M05A formal closeout decision: **COMPLETE; committed 2026-10-22**
- Stage 1 implementation authorization: **GRANTED; PASS accepted 2026-10-22**
- Stage 2A local Qwen qualification: **bounded result accepted with limitations 2026-10-22; retain Qwen only for user-reviewed transformations; 7/9 lexical invariant failures at each context remain failed**
- Stage 2B offline compiled-Gateway acceptance: **PASS; completed 2026-10-22**
- Stage 2B bounded live provider compatibility: **three model requests completed; accepted by operator 2026-10-22**
- Stage 2B technical integration qualification: **PASS; operator-accepted 2026-10-22**
- Cloud production permission and initial selection policy: **PENDING**
- Production deployment and local-only synthetic smoke authorization: **GRANTED AND COMPLETED; 2026-10-23**
- Shared GPU qualification / any restricted local operating policy: **PENDING**
- Tokenizer/template bounds for all enabled models: **PENDING**
- Runtime deployment evidence: **PASS; see Stage 2C verification**
- User review of each generated transformation: **REQUIRED; no quality guarantee**
- M05B explicit closeout: **ACCEPTED; CLOSED 2026-10-23 with limitations**
- Commit authorization: **PENDING separate operator approval under repository policy**
# Context expansion review — Stage 1 operator acceptance recorded

Review [qwen-context-comparison.md](qwen-context-comparison.md),
[context-budget-review.md](context-budget-review.md), and the focused
verification above. Offline validation can be repeated with:

```sh
go test ./internal/texttransform
python3 -m unittest scripts.test_m05a_eval -v
go run ./cmd/gateway --config configs/gateway-text.example.yaml --check-config
```

Expected result: the example accepts the 8K setting; the 4,963-byte budget,
multilingual and JSON escaping boundaries pass; the synthetic long request is
rejected at 4K and accepted at 8K without provider dispatch at rejection; the
M05A harness remains 4K by default and supports explicit 8K. No live benchmark
is included in this validation. Stage 2 live comparison remains pending a separate authorization. Reviewer: operator; date: 2026-10-22; feedback: PASS for Stage 1 only.


## Final M05B acceptance and closeout — 2026-10-23

The operator accepts M05B closeout with these conclusions: implementation and integration **PASS**; production Gateway deployment **PASS**; production local-Qwen transformation **technically PASS**; semantic preservation **PARTIAL, accepted with limitations**; cloud provider integration qualified in isolation; production cloud inference disabled; simultaneous local LLM inference and TTS cold-loading not qualified. Every generated transformation requires user review.

The Stage 2A result remains bounded: seven of nine outputs at each of 4K and 8K failed lexical invariants. Those failures remain documented as failures and are not overridden by acceptance. The Stage 2C production response retained the date, budget and uncertainty, while delivery timing may have been expressed more definitively than its source. Detailed output remains private.

M06 is the next planned milestone and remains inactive. This acceptance closes M05B; it does not authorize a commit.
