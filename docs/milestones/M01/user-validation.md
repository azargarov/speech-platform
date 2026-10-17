# User validation — PENDING

From the repository root:

```sh
python3 -m venv .venv
make bootstrap PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
docker compose -f deployments/compose/compose.yaml build
docker compose -f deployments/compose/compose.yaml up -d
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/readyz
curl -i -X POST http://127.0.0.1:8080/v1/stt/transcriptions
curl -i -X POST http://127.0.0.1:8080/v1/tts/speech
docker compose -f deployments/compose/compose.yaml ps
docker compose -f deployments/compose/compose.yaml down
```

Expected HTTP statuses in order: 200, 503, 404, 404. Only gateway publishes a host port. STT/TTS should be running, but unavailable for inference. Review contracts, ADRs and the M00 reported observations. Confirm no existing stack changes.

If the original benchmark source becomes available in a local directory, archive code and documentation without overwriting:

```sh
M00_BENCHMARK_SOURCE=/path/to/local/benchmark bash scripts/archive-m00.sh /tmp/speech-m00-source.tar
```

Review archive privately for secrets before adding selected scripts/configuration. Never add recordings.

Record actual command outputs, environment, date, reviewer and explicit acceptance here. Do not mark complete based on local automated checks alone. No user validation has occurred.
