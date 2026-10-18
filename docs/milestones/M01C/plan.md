# M01C plan — GHCR image publication

Status: **PASS; closed 2026-10-18** after the explicitly approved v0.1.2 publication, successful release workflow and user-reported independent XMG manifest inspection. The v0.1.0 and v0.1.1 failures remain recorded in [verification](verification.md); both tags were preserved. See [result](result.md) for acceptance evidence. M01D is next planned; this milestone did not include deployment or GPU inference validation.

## Scope

Publish Gateway, STT and explicitly health-only TTS images from the existing Make/Compose Dockerfile path to GHCR under versioned tags. Capture the registry manifest digest, source revision, platform/architecture and workflow identity in minimal release JSON. Add a version-tag workflow where publication depends on successful verification and image builds. Update roadmap and operating instructions.

No deployment, release-tag creation, remote-server changes, model/config/audio publication, `make install/update/rollback`, or Gateway inference routing.

## Design and boundaries

`make image` remains the sole build interface. The default `make image` and `make image SERVICE=stt` select CPU to preserve the established local behavior. `make image VARIANT=cuda` builds all services with the CUDA STT build override, while `make image SERVICE=stt VARIANT=cuda` builds only CUDA STT. Both variants reuse their existing Dockerfiles and locked dependencies. The build-only CUDA Compose override supplies the reviewed immutable Python base and SHA-256 of the CUDA lock; the runtime-only CUDA Compose overlay is unchanged. The publisher defaults STT publication to CUDA and stores CPU/CUDA STT in distinct repositories. `VARIANT=cpu` explicitly selects CPU. It invokes Make, resolves Compose-owned stable image references from rendered configuration, and uses `docker image inspect` without requiring containers. It validates every selected image for service/variant/source/lock labels and `linux/amd64` before creating registry tags or pushing; it then verifies the published manifest by digest and writes release metadata. See [ADR 0011](../../../docs/adr/0011-ghcr-publication.md).

The image repositories are `ghcr.io/azargarov/voiceservice-gateway`, `voiceservice-stt-cpu`, `voiceservice-stt-cuda`, and `voiceservice-tts-health-only`. TTS remains a health-only process.

## Acceptance

- `make verify PYTHON=.venv/bin/python`, CPU and CUDA STT image builds, and default `make image` pass using the current repository toolchain; CUDA build failure must fail closed without CPU fallback.
- `make publish` rejects missing/invalid versions; unknown services fail before build or push.
- Default publication uses CUDA STT; explicit `VARIANT=cpu` uses CPU STT. Both selected and default publication paths reuse `make image`; local auth is required and builds alone never publish.
- Ordinary read-only verification and the tag workflow both build the CPU default and explicit CUDA variant; publication depends on successful verification/builds and is scoped to the packages-write job.
- Image labels identify source revision and service role; registry inspection uses actual OCI manifest digest and verifies architecture/source labels.
- Per-image JSON contains Git source revision, version, repository, OCI digest, platform/architecture and build workflow identity.
- `releases/stt-cuda-baseline-001.yaml` remains byte-for-byte unchanged.
- A controlled first GHCR release is performed only after explicit user approval; images are inspected by digest and evidence recorded.

## Verification commands

```sh
make verify PYTHON=.venv/bin/python
make image
make image SERVICE=stt VARIANT=cpu
make image SERVICE=stt VARIANT=cuda
make publish
make publish VERSION=invalid
make publish SERVICE=unknown VERSION=v0.1.0
make publish SERVICE=stt VARIANT=unknown VERSION=v0.1.0
python3 -m unittest scripts.test_publish_images -v
git diff --check
```

The actual GHCR publication, workflow run and registry inspection require an approved version tag and package write permission and are outside local verification.

## Publisher image-resolution regression

The first `v0.1.1` release attempt failed in run 39162673061 after all builds, at publisher image lookup: `docker compose images -q` returned no image because no Compose containers had been created. This is a publisher defect; build success was not the problem. The correction adds explicit local image names to the existing Compose definitions and resolves them with `docker compose config --format json` followed by `docker image inspect`. No container is started as a workaround. Regression tests cover all three release images in a no-container mock, missing images, incorrect service/variant identity, registry tag preparation, and the rule that all local validation precedes any push.

The corrected pipeline passed local and GitHub CI checks. The approved v0.1.2 release was published and all three OCI digests were independently inspected from XMG and matched release metadata. See the final evidence in [verification](verification.md). Preserve the v0.1.0 and v0.1.1 release history; neither tag was moved or recreated.
