# M01 result — PASS

M01 foundation and architecture acceptance passed after user validation on 2026-10-17. The approved M00 source-recovery scope exception applies. No deployment was performed.

## Acceptance matrix

| Acceptance area | Evidence | Status |
|---|---|---|
| Gateway port config and Compose target stay aligned; defaults, overrides and invalid values are covered | `make verify`; Compose/config regression tests | PASS |
| Gateway bind validation, request-size boundaries and worker isolation | Go/Python tests and rendered Compose checks | PASS |
| Strict Gateway/worker configuration and settings with effective M01 behavior | Configuration tests; deferred inference-only settings removed | PASS |
| Public/internal OpenAPI schemas and response declarations | OpenAPI validation and focused contract assertions | PASS |
| Governance, formatting, static analysis, tests and builds | Final local verification recorded in [verification.md](verification.md) | PASS |
| Private audio exclusion and benchmark-source exception | Ignore check; user-approved scope decision; source preservation remains NOT ESTABLISHED | PASS WITH APPROVED SCOPE EXCEPTION |
| Host preflight and existing-service non-interference | User-reported read-only host inspection; no services modified | PASS |
| Deployed runtime behavior and GPU passthrough | No deployment or GPU test container run | NOT ESTABLISHED; outside M01 closeout scope |

OBSERVED: the approved initial baseline is commit `4beb6216b57696dcce28e8ee282c7633b74cdb5a`. The audio sample is kept at ignored `private/audio/russian.m4a`. Initial verification records and the pre-commit implementation note are historical. Current remediation verification is recorded in [verification.md](verification.md).

OBSERVED: on 2026-10-17, the user approved an explicit acceptance-scope decision for the M00 source gap: original benchmark scripts/configuration were not recovered; the existing measurements and provenance remain recorded; benchmark reproduction is not claimed; source recovery is deferred and does not block M01 closure. This is not a passed preservation test.

OBSERVED (user-reported): local verification passed. The read-only host inspection found existing Ollama and Dify containers with published ports 80, 443, 5003 and 11434; no listener on 8080; NVIDIA Quadro RTX 5000 visible with driver 580.178.04 and NVIDIA Docker runtime registered; approximately 58 GiB RAM and 105 GB root filesystem space available. No containers or services were modified. Details are in [user validation](user-validation.md).

INTERPRETATION: the host observations and passing static checks support the single-host M01 foundation and isolation design. The absent 8080 listener is an observation at inspection time, not a future availability guarantee.

NOT ESTABLISHED: deployed service behavior, post-remediation image build, inference, authentication enforcement, complete routing, streaming, GPU passthrough, available VRAM at inspection time, and M00 source recovery/preservation. The M00 source-recovery exception does not establish source preservation and must not be represented as a passed test. These limitations do not block M01 closure under the approved scope.

M01 is **PASS**. No deployment, commit, push, tag or M02 work occurred. M02 remains not started and requires separate approval.
