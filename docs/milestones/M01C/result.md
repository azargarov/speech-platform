# M01C result

Status: INCOMPLETE — the `v0.1.1` release built images but failed before publication because image resolution depended on Compose containers. The local resolution/prevalidation fix and requested local checks pass; GitHub CI, GHCR publication and digest verification remain pending.

## Acceptance status

| Criterion | Status | Evidence |
|---|---|---|
| Reuse existing Make/Compose image builds | Local PASS | `make image` and `make verify` passed; see [verification](verification.md) |
| Explicit versioned publication and safe input failures | Local PASS | Unit tests and Make negative cases passed; publication itself pending |
| Separate Gateway, STT and health-only TTS images | Local PASS | All three built; local architecture and role labels inspected; registry check pending |
| Tag workflow with read-only ordinary verification and scoped publish permission | Recovery in progress | Release verification passed in [run 39161408151](https://github.com/azargarov/speech-platform/actions/runs/39161408151); publish job failed before its first step because the artifact action SHA resolved to deprecated v3.1.2. Corrected pin is committed; ordinary CI passed in [run 39161979320](https://github.com/azargarov/speech-platform/actions/runs/39161979320). |
| Registry OCI digests and minimal metadata | Pending release | Failed run did not start publication and produced no metadata artifact; requires an approved corrected release and digest inspection |
| No deployment or baseline modification | PASS | No runtime/remote action; baseline SHA matches `HEAD` |
| Separate CPU/CUDA STT build and publication identities | Local PASS | CPU and CUDA Make builds use the corresponding existing Dockerfiles/locks; release defaults to CUDA, distinct repository names, explicit variant/service labels and metadata. See [verification](verification.md). |
| Previous release gate and first release attempt | Recovery in progress | The artifact pin was fixed and `v0.1.1` remains immutable, but its run failed after builds because `docker compose images -q` needs created containers. The correction resolves stable Compose image references and validates all selected images before writes. Preserve `v0.1.0` and `v0.1.1`; do not recommend another version until GitHub CI passes. |

## Remaining requirements for first release

- Confirm ordinary CI passes on the workflow-fix commit.
- After approval, tag the corrected commit as `v0.1.1`; leave `v0.1.0` unchanged.
- Run publication, inspect Gateway, CUDA STT and health-only TTS by immutable OCI digest, and record source revision, architecture and workflow identity.
- User validates the evidence and explicitly approves M01C closeout.


## Current recovery status — 2026-10-18

The regression fix, explicit Compose image references and documentation are ready locally. The fresh-daemon mock and real local build/inspection evidence are in [verification](verification.md). The exact cause of release run 39162673061 was publisher use of `docker compose images -q` after image build; no containers existed, so it returned an empty result. The fix does not start containers. The requested checks passed locally; the correction still needs a commit/push and successful GitHub CI. Keep M01C incomplete. After CI passes, propose `v0.1.2` without creating it; only a separately approved release attempt can satisfy the registry publication/digest criteria.
