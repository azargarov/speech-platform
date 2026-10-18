# M01C result

Status: INCOMPLETE — corrected variant implementation is committed; the first release attempt failed before publication because the pinned artifact action was deprecated. The action pin has been corrected; publication and digest verification remain pending.

## Acceptance status

| Criterion | Status | Evidence |
|---|---|---|
| Reuse existing Make/Compose image builds | Local PASS | `make image` and `make verify` passed; see [verification](verification.md) |
| Explicit versioned publication and safe input failures | Local PASS | Unit tests and Make negative cases passed; publication itself pending |
| Separate Gateway, STT and health-only TTS images | Local PASS | All three built; local architecture and role labels inspected; registry check pending |
| Tag workflow with read-only ordinary verification and scoped publish permission | Recovery in progress | Release verification passed in [run 39161408151](https://github.com/azargarov/speech-platform/actions/runs/39161408151); publish job failed before its first step because the artifact action SHA resolved to deprecated v3.1.2. Corrected pin is in the working tree; commit and ordinary CI are pending. |
| Registry OCI digests and minimal metadata | Pending release | Failed run did not start publication and produced no metadata artifact; requires an approved corrected release and digest inspection |
| No deployment or baseline modification | PASS | No runtime/remote action; baseline SHA matches `HEAD` |
| Separate CPU/CUDA STT build and publication identities | Local PASS | CPU and CUDA Make builds use the corresponding existing Dockerfiles/locks; release defaults to CUDA, distinct repository names, explicit variant/service labels and metadata. See [verification](verification.md). |
| Previous release gate and first release attempt | Recovery in progress | The CPU/CUDA selection gate is corrected. Remote `v0.1.0` exists at `418297b1170fefce004639bc044444a4c80737ed`; the tag-triggered workflow's verify job passed, but publish setup failed before publishing due to the deprecated artifact action pin. Preserve `v0.1.0`; recommend `v0.1.1` for a corrected release, pending approval. |

## Remaining requirements for first release

- Confirm ordinary CI passes on the workflow-fix commit.
- After approval, tag the corrected commit as `v0.1.1`; leave `v0.1.0` unchanged.
- Run publication, inspect Gateway, CUDA STT and health-only TTS by immutable OCI digest, and record source revision, architecture and workflow identity.
- User validates the evidence and explicitly approves M01C closeout.
