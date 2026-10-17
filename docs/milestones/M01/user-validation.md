# M01 user validation — PASS

OBSERVED (user-reported): local validation passed, and the user completed the read-only host inspection. No containers or services were modified. M01 acceptance passed within the approved scope; this did not include deployment or GPU passthrough testing.

## Local validation

From the repository root, run:

```sh
make governance-check PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
SPEECH_LISTEN_PORT=8765 SPEECH_BIND_IP=127.0.0.2 make compose-check PYTHON=.venv/bin/python
SPEECH_LISTEN_PORT=8765 go run ./cmd/gateway --config configs/gateway.yaml --check-config
git check-ignore -v private/audio/russian.m4a
git diff --check
```

Expected: all commands exit zero; the override checker accepts the same 8765 target and process port; the private audio ignore rule resolves to `/private/`. These checks do not validate a running deployment.

## Target-host read-only inspection

The user completed the procedure in [host-inspection.md](host-inspection.md). Codex did not connect to the host. User-reported observations:

- Existing Ollama and Dify containers were running. Published ports included 80, 443, 5003 and 11434.
- No listener was observed on host port 8080 at inspection time.
- NVIDIA Quadro RTX 5000 was visible; driver version 580.178.04 was reported. NVIDIA Docker runtime was registered.
- Approximately 58 GiB RAM was available and approximately 105 GB was available on the root filesystem.
- No containers or services were modified.

These are user-reported host observations, not independently collected by Codex. The host details supported a read-only preflight; they do not prove future port availability or Speech Platform runtime behavior. Runtime GPU passthrough and available VRAM at inspection time were not established.

## M00 benchmark-source scope decision

OBSERVED: the user approved deferring recovery of the original M00 scripts/configuration. Existing measurements and provenance remain recorded; benchmark reproduction is not claimed. Source preservation is **NOT ESTABLISHED**, and this is not a passed preservation test. Recovery is deferred and does not block M01 closure.

## Validation record

Acceptance decision: **M01 PASS** within the approved scope. User validation accepts the local foundation and static Compose isolation/configuration checks plus the read-only host observations. It does not claim deployed runtime validation, GPU passthrough, inference, or recovered/reproduced M00 benchmark sources. M02 remains not started and requires separate authorization.
