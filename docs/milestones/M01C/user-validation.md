# M01C user validation

Status: pending user review.

## Review steps

1. Review the Make target, publisher, release workflow, image labels and metadata schema.
2. Confirm the package names `voiceservice-stt-cpu` and `voiceservice-stt-cuda`, and the explicit `voiceservice-tts-health-only` identity.
3. After local checks pass, approve one exact version tag and the controlled GHCR publication. No tag or image will be created/pushed before that approval.
4. Review the release workflow result and each emitted metadata JSON. Inspect each published image using its `repository@sha256:...` reference and confirm OCI revision/role labels and architecture.

## Expected result

Only the approved source revision and version are published. The release workflow verify/build job succeeds before the publish job runs and explicitly selects CUDA STT. Each image's registry digest, service, runtime variant, applicable lock digest, platform, source revision and role match the metadata. CPU publication requires `VARIANT=cpu`. No models, private configuration, credentials or local audio fixtures are present in the published images.

Reviewer, approval, commands, registry observations and feedback: pending.
