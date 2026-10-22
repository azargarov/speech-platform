# M03 result

Status: **M03A PASS for bounded evaluation and candidate selection. M03B PASS
and COMPLETE (2026-10-22) for the agreed implementation, live technical
validation and operator acceptance of the tested quality-mode baseline. This
does not claim unrestricted production readiness.**

## M03A closeout

| Criterion | Result | Evidence |
|---|---|---|
| Evaluation provenance and measured performance preserved | PASS | Prior isolated-run evidence, revisions, resource observations, warnings and limitations remain in [verification.md](verification.md) and private run directories. |
| Listening assessment across required and mixed-language inputs | PASS for operator-reported assessment | Operator reports VoxCPM2 good across English, Russian, Swedish and mixed-language inputs; MOSS acceptable in pure English and unsatisfactory in the other three categories. |
| Candidate decision | PASS for selection only | VoxCPM2 selected for initial M03B integration; MOSS is not selected. This is not production acceptance. |
| Quality and faster settings | 10-step baseline retained; 8-step unaccepted | 8-step run reduced wall time 7.5% and weighted RTF 11.3%, with 4.3% more rendered audio; listening parity is not established. |
| Language API behavior | PASS for accurate characterization | Neither native pinned API returns a detected language code; VoxCPM2 generated multilingual text without explicit language metadata. Explicit Gateway hints must not be represented as detected results. |
| Licensing | Open for production acceptance | VoxCPM2 pinned Apache-2.0 observations and conditions are preserved. Dataset lineage/output grant are unspecified and production review remains required. MOSS's redistribution/custom-code issues remain; it is not selected. |

The operator supplied the final M03A listening assessment and explicitly
requested M03A closeout and M03B implementation in this task. M03A is therefore
closed for its bounded evaluation/selection scope. That approval does not close
M03B or declare the model production ready.

## M03B closeout

| Criterion | Result | Evidence |
|---|---|---|
| Agreed Gateway/worker implementation, pinned model artifact, configuration and operational documentation | PASS | Implementation record, pinned manifest, contract and configuration changes, `make verify PYTHON=.venv/bin/python` and `git diff --check` recorded in [verification.md](verification.md). |
| Live technical acceptance on the target RTX 5000 and canonical Gateway | PASS for recorded checks | Image/model identity and integrity, health/readiness, four valid WAV responses, input validation, lifecycle/warm-up/unload/reload, cancellation recovery, normal stop/restart, and one short STT/TTS overlap are recorded in [verification.md](verification.md). |
| Operator listening acceptance of quality-mode baseline | PASS for four tested samples | Operator listened to English, Russian, Swedish and mixed-language quality recordings and reports that all sound good; see [user-validation.md](user-validation.md). |
| Fast mode | Not accepted; unavailable | Eight-step quality has not been accepted; runtime returns structured `mode_unavailable`. |
| Production licensing | Open / not fully cleared | Production review and applicable model/dependency/data/output terms are not fully resolved. |
| Sustained concurrent-load behavior | NOT ESTABLISHED | Only one short overlapping STT/TTS pair was observed; no sustained load run is claimed. |
| Cold-model loading latency | Limitation | Initial quality request took 78.17 seconds; an observed reload path took 69.66 seconds. |

M03B is complete for its agreed implementation and technical validation
scope. This bounded closeout records operator acceptance of the four tested
quality-mode recordings; it does not assert unrestricted production
readiness. No next milestone is started. Commit remains pending separate
operator review.
