# Speech Platform

Application-agnostic, self-hosted STT and TTS foundation. M01 is complete as a foundation and architecture milestone. Inference is unavailable. No `/v1` or internal inference handlers are installed. M02/M03 implement providers; M04 implements authentication enforcement and complete routing. Runtime deployment and GPU passthrough have not been validated.

## Development

Requires Go 1.27.2, Python 3.13, Docker with Compose, and Make. No GPU needed.

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
```

`make fmt` intentionally rewrites formatting. `make verify` checks formatting without rewriting files. Python dependencies are direct pins; transitive dependencies are not locked yet.

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

## Containers

```sh
docker compose -f deployments/compose/compose.yaml build
docker compose -f deployments/compose/compose.yaml up -d
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/readyz
docker compose -f deployments/compose/compose.yaml down
```

Expected: health 200, readiness 503. Workers publish no host ports. Only a loopback gateway port is published by default. Existing Ollama and Dify services are not referenced or modified. No GPU reservations or model downloads occur in M01.

See [architecture](docs/architecture/overview.md), [contracts](api/openapi/public-v1.yaml), [operations](docs/operations/runbook.md), [milestone plan](PLANS.md), and [user validation](docs/milestones/M01/user-validation.md).
