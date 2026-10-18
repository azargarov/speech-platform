# M01C verification record

Status: implementation locally verified; commit, GitHub CI, GHCR publication and M01C closeout remain pending.

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
- Local `docker image inspect` showed `linux/amd64` and expected service/runtime-variant/role/lock labels for CPU STT, CUDA STT, Gateway and TTS. CUDA labels included the base digest, exact CUDA lock SHA-256 and source-revision label. At this pre-commit point the labels reflected the current Git `HEAD`, not the uncommitted worktree; they are not release-source evidence. Images will be rebuilt from the clean committed revision before source-label verification.
- `docker run --rm --network none --read-only --entrypoint python speech-platform-stt-cuda:local ...` loaded `libcublas.so.12`, `libcudnn.so.9` and `libnvrtc.so.12` successfully. This confirms packaged CUDA user-space libraries load; it is not GPU inference or acceptance of the operational baseline.
- `.venv/bin/python -m unittest discover -s scripts -p 'test_publish_images.py' -v` — 10 tests passed, covering version/service/variant validation, repository and label mapping, CUDA Compose/Dockerfile/lock selection, default policy and dirty-worktree rejection.
- Invalid Make selections exited 2 before build/publication: `make image SERVICE=invalid`, `make image SERVICE=stt VARIANT=gpu`, `make publish SERVICE=unknown VERSION=v0.1.0`, and `make publish SERVICE=stt VARIANT=gpu VERSION=v0.1.0`. Missing and invalid versions (`make publish`, `make publish VERSION=invalid`) exited 2 before authentication/build/push.
- `make verify PYTHON=.venv/bin/python` — exit 0, including config/Compose checks for both STT build variants, all script and STT tests, Go checks, governance and lock checks.
- `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.7 .github/workflows/release.yaml .github/workflows/verify.yaml` — exit 0.
- `git diff --check` — exit 0. The historical CUDA baseline remains unchanged at SHA-256 `0c585d62d7d4cf3cf7c74bcf2b9693909cf68ec4529036695c24e882268f0627`.
- No tag, GHCR publication, registry digest lookup, server access or running-service operation occurred.

An initial system-Python Ruff check could not run because Ruff is not installed there; the repository virtualenv was used. An initial unittest module invocation used the wrong import path and an early test draft mistakenly accepted Docker-invalid SemVer build metadata; these were corrected, and the discover-based tests passed.

## NOT ESTABLISHED

- GitHub CI on the commit, GHCR package write access, publication, registry digest and digest-pull inspection.
- CUDA GPU inference; the local image build and library-load check do not establish inference behavior.

Buildx registry digest resolution and digest-pull inspection were not executed. The local image IDs observed during image builds are not OCI manifest digests. The historical M01B results remain separate evidence.

## Release readiness

The previous CPU-selection defect is corrected locally: publication defaults to the distinct CUDA STT repository, CPU publication requires `VARIANT=cpu`, and the release workflow explicitly builds and publishes CUDA. Commit/push and a passing GitHub CI run are still required before the implementation is ready for the separately approved `v0.1.0` publication. M01C remains incomplete until the actual GHCR images are inspected by OCI digest.
