# M01C user validation

Status: **PASS — user validation and explicit closeout approval received (2026-10-18).**

## Validation evidence

The user independently inspected the three published v0.1.2 images from the XMG workstation using authenticated GHCR access and `docker buildx imagetools inspect`. All registry manifest digests matched release metadata:

- Gateway `ghcr.io/azargarov/voiceservice-gateway`: `sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30`.
- STT CUDA `ghcr.io/azargarov/voiceservice-stt-cuda`: `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8`.
- TTS health-only `ghcr.io/azargarov/voiceservice-tts-health-only`: `sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6`.

The v0.1.2 release workflow [39165353557](https://github.com/azargarov/speech-platform/actions/runs/39165353557) succeeded. Full source revision, image metadata and verification evidence are recorded in [verification](verification.md); acceptance is summarized in [result](result.md).

Reviewer: user, reporting independent inspection from XMG. Feedback: all three registry digests match release metadata; M01C closeout approved. No server deployment or GPU inference acceptance was requested or performed.
