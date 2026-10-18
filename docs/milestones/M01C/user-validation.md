# M01C user validation

Status: pending user review.

## Review steps

1. Review the Make target, publisher, release workflow, image labels and metadata schema.
2. Confirm the package names `voiceservice-stt-cpu` and `voiceservice-stt-cuda`, and the explicit `voiceservice-tts-health-only` identity.
3. The earlier `v0.1.0` and `v0.1.1` tags remain unchanged. The corrected implementation passed GitHub CI in run 39164164869. Review the proposed `v0.1.2` release request separately. No new tag or image will be created/pushed before explicit approval.
4. Review the release workflow result and each emitted metadata JSON. Inspect each published image using its `repository@sha256:...` reference and confirm OCI revision/role labels and architecture.

## Expected result

Only the approved source revision and version are published. The release workflow verify/build job succeeds before the publish job runs and explicitly selects CUDA STT. Each image's registry digest, service, runtime variant, applicable lock digest, platform, source revision and role match the metadata. CPU publication requires `VARIANT=cpu`. No models, private configuration, credentials or local audio fixtures are present in the published images.

Reviewer, approval, commands, registry observations and feedback: pending.
