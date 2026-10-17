# M01 implementation

## Historical baseline record

OBSERVED (baseline work recorded 2026-10-17, before the initial Git commit): the original foundation was created in an empty repository workspace. The then-present recording was left outside Git. A read-only remote source lookup failed because its SSH alias did not resolve. The historical verification and implementation details remain in [baseline verification evidence](evidence/make-verify.txt) and [baseline verification record](verification.md).

The earlier statement “no commit made” described the state at that time only. The approved initial baseline is now commit `4beb6216b57696dcce28e8ee282c7633b74cdb5a`. The private recording is now under ignored `private/audio/russian.m4a`; it is not part of the commit.

## Current remediation

OBSERVED: remediation was authorized on 2026-10-17 after the read-only audit. Gateway and worker boundaries, public/internal API separation and fail-closed inference routes are retained.

Changes made during this remediation: use `SPEECH_LISTEN_PORT` for the Gateway process and Compose target; validate rendered port and bind agreement; enforce the Gateway body-size limit; remove unused worker model path, request-size and inference-drain settings and defer them to M02/M03; validate listen hosts and port boundaries; tighten OpenAPI limits and response declarations; make process limits configurable; and reconcile milestone evidence. Verification results are in [remediation evidence](evidence/remediation-verify.txt).

OBSERVED: the checked local benchmark-source candidate was absent. No remote system was accessed. The original benchmark sources have not been recovered or preserved in this repository. `benchmarks/README.md` records the supplied observations and this limitation.

USER-APPROVED SCOPE DECISION (2026-10-17): original benchmark scripts and configuration were not recovered; the existing M00 measurements and provenance remain recorded; benchmark reproduction is not claimed. Recovery is deferred and does not block M01 closure. This is an acceptance-scope exception, not a passed source-preservation test.

INTERPRETATION: the current changes improve configuration truthfulness and regression protection without changing the component architecture or adding inference/routing behavior.

NOT ESTABLISHED: target-host deployment, runtime service behavior, Docker image rebuild after remediation, runtime inference, authentication, GPU passthrough, available VRAM at inspection time, and original M00 source recovery/preservation. The source-recovery gap is explicitly deferred under the user-approved scope decision above and is not a closure blocker. User validation is recorded in [user-validation.md](user-validation.md).
