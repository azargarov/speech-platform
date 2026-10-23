# M05B result

Status: **M05B IN PROGRESS; Stage 1 and Stage 2A/2B qualification are operator-accepted. Stage 2A completed 18 requests with natural expiry and GPU recovery at both contexts; seven outputs per context failed lexical quality invariants, including substantive short-case defects. The operator retains local Qwen only for user-reviewed transformations; the failures remain failures and no quality guarantee is made. Stage 2B passed. Stage 2C deployment tooling is prepared and offline-verified; production deployment and closeout remain unauthorized.**

The [plan](plan.md) supplies the current architecture assessment, proposed
module boundaries, complete configuration example, stable selection semantics,
failure table, cloud policy, API proposal, security/reliability controls, staged
acceptance gates, affected files and verification/operator acceptance.
[ADR 0021](../../adr/0021-configurable-text-transformation.md) is accepted for
the implemented M05B scope. Stage 2A/2B qualification is accepted with the
limitations recorded below; production deployment and milestone closeout are
separate decisions.

M05A is formally closed and committed. Its accepted three-model retention and
documented quality limitations remain unchanged. This result does not claim
runtime acceptance from implementation or offline checks.

Stage 1 implementation and offline verification evidence are recorded in
[implementation.md](implementation.md) and [verification.md](verification.md).
The operator accepted Stage 1 with PASS on 2026-10-22. The Stage 2A limitations
and Stage 2B acceptance are recorded in [user-validation.md](user-validation.md)
and [verification.md](verification.md). Deployment and closeout remain separately gated.
The initial 4K attempt stopped after the private harness failed to import the checker. After the operator accepted that root-cause analysis and offline regressions, the harness was repaired and the authorized comparison resumed. All nine cases completed at 4K and 8K; all responses were saved before validation. Measurements, output review, natural expiry/recovery and limitations are recorded in [stage-2a-qualification.md](stage-2a-qualification.md). Stage 2A awaits operator acceptance of the mixed quality and resource evidence.
This result does not close M05B; explicit closeout remains pending.

All supplied findings A–I have design-level corrections; the plan's section 12
lists them. Simplifications include shared transport settings, zero same-model
retries, no fallback toggle or reasoning capability list, stable YAML ordering,
and logical model metadata without a redundant review flag. There is no open
architecture decision blocking authorized offline implementation.

Live tokenizer/template bounds, provider compatibility, shared-GPU coexistence,
actual remote cancellation/unload, network reachability and rollback remain
NOT ESTABLISHED. Failed/inconclusive GPU qualification restricts local production
use pending an approved policy; it cannot be reported as a coexistence pass.
Production cloud settings, Stage 2B live inference authorization and deployment
remain operator decisions. See [Stage 2B qualification](stage-2b-qualification.md)
for connectivity, offline verification, the 5-second Ollama keep-alive limit,
and the proposed three-request live envelope.
Stage 1 is accepted for its offline implementation scope only. The Stage 1
code and offline checks do not establish production qualification.
# Stage 1 context expansion investigation — accepted offline scope

The offline implementation and focused checks are recorded in
[implementation.md](implementation.md) and [verification.md](verification.md).
The example local Qwen budget is now 4,963 serialized ASCII bytes at 8K while
retaining existing prompt and overhead checks and the 1,024-token output
reservation. A controlled live comparison is prepared but not executed.

**INTERPRETATION:** 8K is suitable to evaluate in Stage 2A because the
conservative input budget increases while the output reservation and guards
remain intact. This is not a production qualification.

**NOT ESTABLISHED:** measured memory/latency, cold load/unload, actual model
context acceptance, long-request quality, coexistence, or value of a context
larger than 8K. A larger context is not presently justified for investigation
until representative inputs exceed the 8K budget or live acceptance fails.

Stage 1 operator acceptance includes this offline context-budget change.
The operator authorized Stage 2A on 2026-10-22 and requested resumption after accepting the harness root-cause and offline regression results. The resumed 4K/8K comparison completed all 18 sequential requests. Both contexts naturally expired and GPU memory recovered; seven outputs at each context failed lexical invariants, with substantive short-case defects in the private output review. Stage 2A was accepted with limitations: local Qwen is retained only for user-reviewed transformations, and its seven lexical failures per context remain failed. Stage 2B was separately accepted PASS; deployment and closeout remain pending.


Stage 2A execution is complete and the operator accepted retaining local Qwen only for user-reviewed transformations despite the documented quality failures. This decision does not convert failed invariants into passes.

**8K assessment:** retain 8K only as the proposed example setting for
qualification. Its operational suitability and memory/latency trade-off remain
NOT ESTABLISHED; do not treat it as a production default on current evidence.
No further Stage 2A requests are needed for the authorized corpus. Stage 2B live and offline Gateway integration qualification was accepted PASS. Stage 2C deployment remains subject to review and explicit authorization; see [Stage 2B qualification](stage-2b-qualification.md).
