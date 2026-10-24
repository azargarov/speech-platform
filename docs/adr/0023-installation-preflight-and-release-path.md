# ADR 0023: One product installer and a read-only prerequisite report

- Status: proposed; implementation authorized, operator acceptance pending
- Scope: initial full SpeechPlatform release qualification
- Extends: [ADR 0018](0018-git-compose-product-operations.md)

## Context

The root Compose stack runs real STT and VoxCPM2 workers, but the product CLI
accepted only Gateway selection. The historical release-pinned installer uses
VoiceService v0.1.2, whose TTS image is health-only. Missing private profiles and
stale documentation made these paths appear interchangeable. The current public
API functionality remains unchanged.

## Decision

Use root `compose.yaml` and extend `scripts/product_deployment.py` for full-stack
and single Gateway/STT/TTS installs. Keep the historical installer/descriptor
available for historical evidence; they are not the current product path.
Only a local Unix Docker endpoint is supported; context precedence is validated.
Deployment values omitted from `.env` do not inherit shell overrides.
Configuration is `.env` plus checked-out service YAML, with an optional private
Gateway override and optional private cloud credential file. No lifecycle database,
new deployment service, profile hierarchy or release descriptor with invented
registry digests is introduced.

`make preflight` and `make plan` are read-only prerequisite reports. Group checks
into Host, GPU, Models, Networking, External Providers and Deployment. Each result
is PASS/WARN/FAIL/SKIP; WARN/FAIL includes remediation, FAIL blocks install, and
optional disabled features SKIP. Finish with counts and READY TO INSTALL or NOT
READY TO INSTALL. Hardware metadata alone does not establish container CUDA.
An explicit bounded disposable `gpu-check` runs after build and before install;
it initializes the CUDA driver API, never a model. Model provisioning stays explicit.

STT and TTS own model admission and lifecycle. Preflight reports low VRAM as a
warning because operational unloaded workers do not need residency to start;
workers continue enforcing their own bounded loading safeguards. Gateway-only
installation needs healthy existing workers. A selected worker is built and
recreated with `--no-deps`, preserving other services. Normal status/log inspection
does not depend on model loading or external-provider availability.

Ollama is externally owned. Inspect its existing private network/alias and query
only version/tags; fail when configured local transformation cannot work. Never
attach/recreate/upgrade shared Ollama in the product installer. Probe DNS from an
existing Gateway when available; otherwise report the gap and verify after install.
Cloud-disabled installations require no credentials. Enabled cloud providers use
HTTPS plus a private mode-0600 env file, validated without paid API calls. Provider
routing and cloud authorization are unchanged.

Build from clean committed source; validate image platform, source revision and
role before applying Compose. Preserve the special immutable Gateway no-build
mode. Upgrade uses the same install command. Stop/remove only the selected owned
Compose resources; preserve models, volumes, images and external networks.

## Alternatives and consequences

Extending the old release-pinned profile system was rejected: it would replace
working inference images with foundation images and require unrelated private
host state. Adding a third installer was rejected as unnecessary. Existing image
publication is corrected to publish the actual CUDA TTS definition and dependency
lock identity. CI builds images independently so CUDA wheels do not compete with
all other build layers on one runner. CI does not require a GPU or model weights.

A future tag must refer to the accepted committed installer, and its registry
metadata must supply real immutable digests. Historical v0.1.0–v0.1.2 tags remain
unchanged; v0.2.0 is the recommended first full SpeechPlatform product tag.
