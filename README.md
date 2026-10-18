# Speech Platform

Application-agnostic, self-hosted speech services. The product name is VoiceService; the repository remains `speech-platform`. The repository contains a production STT worker and a CUDA STT runtime smoke baseline. The target-local STT baseline in [releases/stt-cuda-baseline-001.yaml](releases/stt-cuda-baseline-001.yaml) records a healthy container and two successful HTTP transcriptions. This is a working experimental runtime, not a reproducible platform installation or capacity guarantee. The Gateway's public inference routes/authentication and TTS inference remain unimplemented; see [PLANS.md](PLANS.md) and the [architecture redesign plan](docs/architecture/platform-redesign.md).

## Development

Requires Go 1.27.2, Python 3.13.9, Docker Engine with Compose, and Make. No GPU is needed for verification or image builds. The GitHub Actions workflow uses the same Make targets on Ubuntu 24.04.

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
make image SERVICE=stt
```

`make fmt` intentionally rewrites formatting. `make verify` checks formatting without rewriting files. Python dependencies are direct pins; transitive dependencies are not locked yet.

`make image` builds all current Compose service images locally; `make image SERVICE=gateway|stt|tts` selects one. It never publishes images. STT uses the existing CPU image definition for ordinary builds, so no GPU or private model artifacts are required. The TTS image is currently health-only and does not provide TTS inference.

`.github/workflows/verify.yaml` runs `make bootstrap`, `make verify`, and `make image` for pushes to `main` and pull requests targeting `main`. It has read-only repository permissions and does not publish images or deploy. GHCR publication is deferred to a separately authorized next step.

## Local process

```sh
go run ./cmd/gateway --config configs/gateway.yaml
# separate shells
.venv/bin/python -m services.stt.main --config configs/stt.yaml
.venv/bin/python -m services.tts.main --config configs/tts.yaml
```

Sample configuration binds all interfaces for containers. For direct host runs, change listen_host to loopback. Do not run on an untrusted host network.

## Private data and local benchmarks

Keep private audio, credentials, local fixtures and other sensitive test data under the root `private/` directory. That directory is ignored by Git and excluded from Docker build contexts; do not force-add its contents. The local benchmark sample is `private/audio/russian.m4a`. Benchmark code should read `SPEECH_BENCHMARK_AUDIO`; use `scripts/with-benchmark-audio.sh` to set the default or override the path for a command. See [M00 benchmark notes](benchmarks/README.md) for local archive instructions.

## Container and deployment status

The CUDA STT smoke deployment is already running on the target recorded by the baseline. Do not use the generic foundation Compose commands below as instructions to recreate or replace that service. The tracked Compose files include CPU/foundation defaults and a separate validated CUDA overlay; the successful smoke used ignored, target-specific configuration. A supported `make install`/`update`/`rollback` interface is proposed but is not implemented yet. Preserve the running service until a separately reviewed migration and rollback path is approved.

See [architecture](docs/architecture/overview.md), the [redesign and migration plan](docs/architecture/platform-redesign.md), [contracts](api/openapi/public-v1.yaml), [operations](docs/operations/runbook.md), [milestone plan](PLANS.md), and [baseline record](releases/stt-cuda-baseline-001.yaml).
