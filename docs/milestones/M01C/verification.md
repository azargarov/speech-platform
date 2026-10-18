# M01C verification record

Status: implementation committed to GitHub `main`; local verification and GitHub CI pass. GHCR publication and M01C closeout remain pending.

## OBSERVED

### Previous pre-publication attempt (historical; superseded by corrected variant verification below)

- Environment: repository workstation at `/home/andrey/Documents/projects/speech-platform`, 2026-10-18; Docker Engine/Compose and `.venv/bin/python` were available.
- `make verify PYTHON=.venv/bin/python` — exit 0 on the final base-image-pinned tree. Go vet/tests/build, Ruff, config/Compose checks, 61 script tests, STT tests, governance and lock checks passed.
- `make image` — exit 0 for Gateway, STT and TTS using the existing Compose/Dockerfiles. BuildKit resolved the configured immutable base digests and built all three images for `linux/amd64`.
- Local `docker image inspect` showed `org.opencontainers.image.revision=8f6028dd6ad2e02ff1142f0bd79962a3fffb122c` and expected roles `gateway`, `stt-worker`, `tts-health-only` on the three local images. This inspects local image metadata, not registry manifests.
- `.venv/bin/python -m unittest discover -s scripts -p 'test_publish_images.py' -v` — 5 publisher input/auth/dirty-tree tests passed after the final test addition.
- Missing and invalid version checks (`make publish`, `make publish VERSION=invalid`) each exited 2 with the semantic-version error before Docker/build invocation.
- Unknown service (`make publish SERVICE=unknown VERSION=v0.1.0`) exited 2 during Makefile parsing before the publisher or Docker was invoked.
- `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/release.yaml .github/workflows/verify.yaml` — exit 0; syntax and expression checks passed for both workflows.
- Workflow YAML structural inspection confirmed tag-only trigger, publish dependency on `verify`, and publish-job permissions `contents: read` plus `packages: write`. Existing `.github/workflows/verify.yaml` remains `contents: read`.
- `git diff --check` — exit 0 on the final diff.
- SHA-256 of `releases/stt-cuda-baseline-001.yaml` and `git show HEAD:releases/stt-cuda-baseline-001.yaml` both observed as `0c585d62d7d4cf3cf7c74bcf2b9693909cf68ec4529036695c24e882268f0627`.
- Release pre-publication audit on 2026-10-18: local `HEAD` and `origin/main` both point to `8f6028dd6ad2e02ff1142f0bd79962a3fffb122c`, while the M01C implementation files remain modified or untracked. The implementation is therefore not committed or available on GitHub `main`.
- `git ls-remote --tags origin 'refs/tags/v0.1.0' 'refs/tags/v0.1.0^{}'` returned no refs. No release tag was created or pushed.
- `make -n image SERVICE=stt` selects `deployments/compose/compose.stt-cpu.yaml`, which builds the `stt` service with `deployments/compose/worker-stt-cpu.Dockerfile`. The publisher maps bare `SERVICE=stt` to the generic `ghcr.io/azargarov/voiceservice-stt` image and invokes `make image SERVICE=stt`; the release workflow supplies no CUDA variant. This is the CPU/foundation image, not the CUDA production image.
- `make verify` — exit 2 because system Python lacks Ruff. `make verify PYTHON=.venv/bin/python` — exit 0; all verification steps passed, including 61 script tests, Go tests/build, Compose checks and STT lock checks.
- `make image` — exit 0 for Gateway, CPU/foundation STT and health-only TTS. Build output explicitly used `worker-stt-cpu.Dockerfile` and `requirements-stt-cpu.lock`; it does not verify or build the CUDA production image.
- The previous release gate failed on both committed-main availability and CUDA image selection. No tag, GHCR publication, registry digest lookup or hosted workflow run was attempted.

## Corrected variant selection — local verification (2026-10-18)

- `make image SERVICE=stt VARIANT=cpu` — exit 0; Compose selected `worker-stt-cpu.Dockerfile` and `requirements-stt-cpu.lock`, verified the lock SHA-256, and built the local CPU image.
- `make image SERVICE=stt VARIANT=cuda` — exit 0; Compose selected `worker-stt-cuda.Dockerfile`, pinned base `python:3.13.9-slim@sha256:326df678c20c78d465db501563f3492d17c42a4afe33a1f2bf5406a1d56b0e86`, and the CUDA lock with SHA-256 `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`. The complete build succeeded. BuildKit warned that the Dockerfile's required `ARG STT_CUDA_BASE_IMAGE` has no standalone default; Compose supplies the reviewed pinned value explicitly.
- `make image` — exit 0 for Gateway, CPU STT and health-only TTS; this preserves CPU as the default build variant. `make image VARIANT=cuda` — exit 0 for Gateway, CUDA STT and health-only TTS, matching the release workflow's build selection.
- Local `docker image inspect` showed `linux/amd64` and expected service/runtime-variant/role/lock labels for CPU STT, CUDA STT, Gateway and TTS. CUDA labels included the base digest, exact CUDA lock SHA-256 and source-revision label. The initial pre-commit image labels were not treated as release-source evidence.
- `docker run --rm --network none --read-only --entrypoint python speech-platform-stt-cuda:local ...` loaded `libcublas.so.12`, `libcudnn.so.9` and `libnvrtc.so.12` successfully. This confirms packaged CUDA user-space libraries load; it is not GPU inference or acceptance of the operational baseline.
- `.venv/bin/python -m unittest discover -s scripts -p 'test_publish_images.py' -v` — 10 tests passed, covering version/service/variant validation, repository and label mapping, CUDA Compose/Dockerfile/lock selection, default policy and dirty-worktree rejection.
- Invalid Make selections exited 2 before build/publication: `make image SERVICE=invalid`, `make image SERVICE=stt VARIANT=gpu`, `make publish SERVICE=unknown VERSION=v0.1.0`, and `make publish SERVICE=stt VARIANT=gpu VERSION=v0.1.0`. Missing and invalid versions (`make publish`, `make publish VERSION=invalid`) exited 2 before authentication/build/push.
- `make verify PYTHON=.venv/bin/python` — exit 0, including config/Compose checks for both STT build variants, all script and STT tests, Go checks, governance and lock checks.
- `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/release.yaml .github/workflows/verify.yaml` — exit 0.
- `git diff --check` — exit 0. The historical CUDA baseline remains unchanged at SHA-256 `0c585d62d7d4cf3cf7c74bcf2b9693909cf68ec4529036695c24e882268f0627`.
- No tag, GHCR publication, registry digest lookup, server access or running-service operation occurred.
- Clean-tree image build on commit `0098849da6da3f0ca1ff0363c6db45aea87c44cf`: `make image` passed, and `make image SERVICE=stt VARIANT=cuda` passed. `docker image inspect speech-platform-stt-cuda:local` reported `linux/amd64`, `service=stt`, `runtime-variant=cuda`, the `stt-worker` role, CUDA lock SHA-256 `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`, the pinned Python base digest, and source revision `0098849da6da3f0ca1ff0363c6db45aea87c44cf`. This confirms a clean committed-source CUDA build and provenance labels; it does not establish GPU inference.
- GitHub Actions verification on `a4f59b006811b0830aa3c9a1c618c78bd024d40` succeeded: [run 39160390567](https://github.com/azargarov/speech-platform/actions/runs/39160390567). The run executed `make verify`, the default `make image`, and `make image VARIANT=cuda`; all passed on a standard hosted runner without GPU access. The verification workflow has `contents: read`; it requires no package-write permission.
- The corrected implementation and CI changes are committed and available on GitHub `main`: implementation `0098849da6da3f0ca1ff0363c6db45aea87c44cf`; latest implementation/CI commit at this verification point `a4f59b006811b0830aa3c9a1c618c78bd024d40`. No tag or GHCR publication was performed.

An initial system-Python Ruff check could not run because Ruff is not installed there; the repository virtualenv was used. An initial unittest module invocation used the wrong import path and an early test draft mistakenly accepted Docker-invalid SemVer build metadata; these were corrected, and the discover-based tests passed.

## NOT ESTABLISHED

- GHCR package write access, publication, registry digest and digest-pull inspection.
- CUDA GPU inference; the local image build and library-load check do not establish inference behavior.

Buildx registry digest resolution and digest-pull inspection were not executed. The local image IDs observed during image builds are not OCI manifest digests. The historical M01B results remain separate evidence.

## Release readiness

The CPU-selection defect is corrected: publication defaults to the distinct CUDA STT repository, CPU publication requires `VARIANT=cpu`, and the release workflow explicitly builds and publishes CUDA. GitHub Actions run 39161408151 passed verification and both image builds, but failed before the publish job could start because the artifact upload pin resolved to deprecated v3.1.2. The action pin was corrected and committed as `69098d0bf06f63d2b6a084981a2b0a0218ae9a5e`; ordinary CI passed in [run 39161979320](https://github.com/azargarov/speech-platform/actions/runs/39161979320). Release run 39162673061 then failed after image builds because publisher resolution used `docker compose images -q`, which returns no image without created Compose containers. The Compose-reference/direct-inspect fix and its local checks are recorded below; hosted CI is pending. Preserve both `v0.1.0` and `v0.1.1`. Do not recommend a new tag until the corrected commit passes GitHub CI; M01C remains incomplete until a controlled publication and independent OCI digest inspection succeed.

## Release recovery — 2026-10-18

- Failed release run: [39161408151](https://github.com/azargarov/speech-platform/actions/runs/39161408151). The `verify` job passed `make verify`, `make image`, and `make image VARIANT=cuda`. The `publish` job failed at runner setup, before any step ran; the log says GitHub rejected `actions/upload-artifact@0b7f8abb1508181956e8e162db84b466c27e18ce` as deprecated. The run produced no Actions artifacts.
- Upstream tag resolution (`git ls-remote --tags https://github.com/actions/upload-artifact.git`) shows the pinned SHA is exactly `v3.1.2`, not the YAML comment's `v4.6.2`. This is the root cause.
- Replaced it with upstream [`actions/upload-artifact` v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2), pinned to `cf430e030ddbb5b0abf93d22962f4752f3646cd9`. The SHA matches the official tag and its [`action.yml`](https://github.com/actions/upload-artifact/blob/cf430e030ddbb5b0abf93d22962f4752f3646cd9/action.yml) declares Node 24.
- Audited the other release workflow pins against upstream tags: checkout `3d3c42e5aac5ba805825da76410c181273ba90b1` is `v7.0.1`; setup-go `b7ad1dad31e06c5925ef5d2fc7ad053ef454303e` is `v7.0.0`; setup-python `5fda3b95a4ea91299a34e894583c3862153e4b97` is `v7.0.0`. Their comments and tag targets match; the official latest-release endpoints at audit time also reported those versions. No deprecated pin was found among them.
- The annotated `v0.1.0` tag exists locally and remotely and dereferences to `418297b1170fefce004639bc044444a4c80737ed`. It will remain unchanged. No `v0.1.1` tag exists remotely at this check.
- The failed run did not execute Docker login or `make publish`, so it published no images. Anonymous Buildx inspection of the three `:v0.1.0` GHCR references returned 403, and no authenticated GitHub CLI was available; therefore the existence of unrelated or pre-existing GHCR package versions could not be independently established from this environment. No metadata artifact or image digest was produced by the failed run.
- Recovery plan: after user approval, create the proposed `v0.1.1` tag on the corrected main commit; do not move/recreate `v0.1.0`. Then verify all published packages and metadata by registry digest. No server or running service was touched, and the historical CUDA baseline remains unchanged.


## Compose image-resolution correction — local evidence (2026-10-18)

- `docker ps -a --filter label=com.docker.compose.project=speech-platform` returned no containers before the build/resolution exercise and again after it. No Compose service was started.
- `make image` — exit 0. Built Gateway, default CPU STT and health-only TTS through the existing Compose build definitions, now using explicit local references `speech-platform-gateway:local`, `speech-platform-stt-cpu:local` and `speech-platform-tts-health-only:local`.
- `make image SERVICE=stt VARIANT=cuda` — exit 0 using `compose.stt-cuda-build.yaml`, `worker-stt-cuda.Dockerfile`, pinned Python base digest and CUDA dependency lock. The CUDA build took approximately six minutes to download/install the locked CUDA wheels; it completed successfully. This is build evidence only, not GPU inference.
- `compose_image_reference()` rendered the tracked Compose configuration and returned `speech-platform-gateway:local`, `speech-platform-stt-cuda:local` and `speech-platform-tts-health-only:local`. `prepare_image()` then inspected those local refs directly. All three passed source revision `a60055848e8c3bfda26da33bebfb0c92f2d5b311`, service/role/runtime variant and `linux/amd64` checks. CUDA STT had lock SHA-256 `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`. Prepared tags resolved to `ghcr.io/azargarov/voiceservice-gateway:v0.1.2`, `ghcr.io/azargarov/voiceservice-stt-cuda:v0.1.2` and `ghcr.io/azargarov/voiceservice-tts-health-only:v0.1.2`; these were only prepared values, not created/pushed registry tags.
- `.venv/bin/python -m unittest discover -s scripts -p 'test_publish_images.py' -v` — 14 tests passed. New mocks reproduce a fresh daemon with no Compose containers, exercise all three images and tags, and verify missing image, wrong service identity and wrong variant abort before any tag/push. The test asserts all local inspections precede the first registry write and no `compose images -q`, `compose ps` or `compose up` is used.
- `make verify PYTHON=.venv/bin/python` — exit 0, including lint, config, Compose, Go and Python tests, governance and STT lock checks.
- `actionlint .github/workflows/release.yaml .github/workflows/verify.yaml` — exit 0. `git diff --check` — exit 0. Missing/invalid `VERSION` and unknown `SERVICE` each exited 2 before any build or publication.
- CI for the correction has not yet run. No GHCR image was tagged or pushed, no release tag was created, no server or running container was changed, and `releases/stt-cuda-baseline-001.yaml` is unchanged.
