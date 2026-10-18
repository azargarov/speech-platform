# M01C result

Status: **PASS — closed 2026-10-18 after successful v0.1.2 publication and user-reported independent XMG GHCR manifest inspection.** The acceptance is limited to versioned image publication and immutable digest verification. It does not claim deployment or GPU inference.

## Acceptance status

| Criterion | Status | Evidence |
|---|---|---|
| Reuse existing Make/Compose image builds and publish only by explicit version | PASS | Local verification and publisher regression checks are recorded in [verification](verification.md). The release workflow invokes `make publish VERSION="$GITHUB_REF_NAME" VARIANT=cuda`. |
| Publish separate Gateway, CUDA STT, and health-only TTS images | PASS | The three v0.1.2 GHCR repositories and runtime identities are recorded in [verification](verification.md). |
| Verify source, platform, service/variant labels, and CUDA lock identity | PASS | The publishing job's digest-pull checks passed. The user independently inspected all three manifests from XMG using authenticated `docker buildx imagetools inspect`; registry digests matched release metadata. STT CUDA lock SHA-256 is recorded in the verification table. |
| Release metadata names the actual immutable artifacts | PASS | Workflow artifact `release-metadata-v0.1.2` (ID `12150139581`) contains three service JSON records. Their source revision, version, workflow identity, repository and digests match the release and independent inspection. |
| Preserve failed release attempts and prior tags | PASS | v0.1.0's deprecated artifact-action pin and v0.1.1's Compose-container image-resolution failure remain documented in [verification](verification.md). Neither tag was moved or recreated; v0.1.2 is the recovery release. |
| Avoid deployment and preserve the historical CUDA baseline | PASS | No Ubuntu host or running container was accessed or changed. `releases/stt-cuda-baseline-001.yaml` is unchanged. |

## Release identity

- Tag: annotated `v0.1.2`, dereferencing to `bbbeb697c1ae840e084e962fac39db0c19ab7728`.
- GitHub Actions: [release run 39165353557](https://github.com/azargarov/speech-platform/actions/runs/39165353557); verification and publication jobs succeeded.
- Gateway: `ghcr.io/azargarov/voiceservice-gateway@sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30`.
- STT CUDA: `ghcr.io/azargarov/voiceservice-stt-cuda@sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8`.
- TTS health-only: `ghcr.io/azargarov/voiceservice-tts-health-only@sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6`.

## Remaining limitations

- CUDA inference on the published image was not tested. A successful CUDA image build and digest inspection do not establish GPU behavior.
- TTS remains health-only; Gateway inference routing/authentication is not implemented by M01C.
- Installation, update, rollback and operation on the target Ubuntu host are outside M01C.

M01D — Release Manifest and Model Artifact Management — is the next planned milestone. It has not been started by this closeout.
