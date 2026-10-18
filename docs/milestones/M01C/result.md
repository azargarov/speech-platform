# M01C result

Status: INCOMPLETE — corrected variant implementation is committed and verified locally and in GitHub CI; first GHCR publication remains pending.

## Acceptance status

| Criterion | Status | Evidence |
|---|---|---|
| Reuse existing Make/Compose image builds | Local PASS | `make image` and `make verify` passed; see [verification](verification.md) |
| Explicit versioned publication and safe input failures | Local PASS | Unit tests and Make negative cases passed; publication itself pending |
| Separate Gateway, STT and health-only TTS images | Local PASS | All three built; local architecture and role labels inspected; registry check pending |
| Tag workflow with read-only ordinary verification and scoped publish permission | PASS | `actionlint` passed; ordinary verification succeeded in [GitHub Actions run 39160390567](https://github.com/azargarov/speech-platform/actions/runs/39160390567); publish-job permission remains scoped to the tag workflow |
| Registry OCI digests and minimal metadata | Pending release | Requires approved GHCR publication and digest inspection |
| No deployment or baseline modification | PASS | No runtime/remote action; baseline SHA matches `HEAD` |
| Separate CPU/CUDA STT build and publication identities | Local PASS | CPU and CUDA Make builds use the corresponding existing Dockerfiles/locks; release defaults to CUDA, distinct repository names, explicit variant/service labels and metadata. See [verification](verification.md). |
| Previous release gate | Corrected and verified | The earlier publisher selected CPU STT and was uncommitted. Variant selection now defaults publication to CUDA and explicitly sets CUDA in the release workflow. Implementation is committed and hosted verification/builds pass. No tag was created or pushed. |

## Remaining requirements for first release

- Confirm GHCR package creation/write access in `azargarov` as part of the separately approved release execution.
- Run the tag workflow, inspect Gateway, CUDA STT and health-only TTS by immutable OCI digest, and record source revision, architecture and workflow identity.
- User validates the evidence and explicitly approves M01C closeout.
