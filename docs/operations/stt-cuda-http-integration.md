# M02-C.3 CUDA HTTP integration runbook

Status: M02-C.3 was accepted PASS for the bounded one-request CUDA HTTP integration scope on 2026-10-17. The third controlled attempt passed after explicit fixture media type handling. This runbook describes the validated procedure; any additional target execution requires separate authorization. Overall M02 remains incomplete.

## What the check exercises

`scripts/stt_cuda_http_smoke.py` starts the production `create_http_app()` in an aiohttp `TestServer`, waits for health/readiness, sends exactly one multipart request through `/internal/v1/transcriptions`, validates the response and closes the test client. The route uses the existing application, admission controller, inference supervisor and faster-whisper adapter. The server binds only the test server's loopback socket; it is not a persistent worker or a public endpoint.

The harness reuses strict application/deployment loaders, the worker configuration loader, the CUDA profile validator, the installed-lock check, the artifact manifest verifier, the shared audio checksum verifier, and the existing atomic sanitized report runner. It validates the response text in memory but reports no transcript or segment text. Reports contain identity digests, selected config values, status codes, allowlisted public error codes, fixed failure categories and request stages, timings, language, segment count, timestamp validation and shutdown state. Error response bodies and messages are never persisted. A separate `shutdown-report.json` records whether TestClient shutdown completed with child exit and worker readiness confirmed, was attempted but remains unconfirmed, or failed/exceeded its configured deadline. Container removal alone does not establish child cleanup.

## Configuration sources and precedence

There is no additional C.3 YAML schema. Values have one source each:

1. **Application config (schema v3)** owns model alias/identity, explicit `device_policy.mode: cuda`, CUDA compute type (`float16`), request and upload bounds, and model/request deadlines.
2. **Deployment config (schema v2)** owns artifact filesystem references, CUDA device index and minimum free-memory gate. The existing CUDA profile validator rejects a missing or below-approved gate; the value used by the host preflight and worker is read from this config.
3. **Worker config** supplies the already validated readiness poll interval. The in-process test server does not bind the configured service port.
4. **Approved artifact metadata** supplies the expected tiny-model revision/manifest, CUDA lock digest, image digest/platform and audio SHA-256. The model and lock identities are compared with strict config/source files; the audio path is only a local file reference, and host/container checks use the same checksum metadata.
5. **Experiment command settings** supply the approved identities, report root, attempt identity, shared group, overall deadline, termination grace and container CPU/RAM/PID limits. Docker flags are parsed and validated by the maintained launcher. No environment variable can override application or deployment settings.

The launcher compares the Docker GPU selector with the validated deployment GPU index. The CUDA HTTP profile also checks that deployment artifact/manifest paths are under the read-only `/models` mount and that the app config names the approved model revision and manifest. It requires an immutable image ID, matching platform, `--pull=never`, `--network=none`, no published ports, read-only root and input mounts, a non-root identity, and exactly one writable `/results` bind mount. It also requires explicit CPU, memory and PID limits. The profile rejects CPU/auto mode, a non-faster-whisper backend, a non-float16 CUDA setting, an unapproved device index, a changed model/lock identity or an insufficient configured memory gate. Missing or malformed settings fail before Docker starts.

## Proposed container resource envelope

Use these values for the first C.3 experiment only:

| Limit | Proposed value | Basis and limitation |
|---|---:|---|
| CPU | 4 CPUs | Same bounded envelope used for the accepted C.2b tiny-model run. It allows CPU-side audio decode and the Python worker/child. It is a cap, not a measured requirement. |
| RAM | 8 GiB (`8589934592` bytes) | Same C.2b container cap. The model artifact is tiny and audio decoding is bounded by application config, but process RSS was not measured in C.2b. This is a ceiling, not a memory estimate or guarantee against OOM. |
| PIDs | 128 | Same C.2b cap, intended to bound Python/native thread and child-process growth. Native library thread counts were not measured. |
| Overall deadline | 180 seconds | Explicitly supplied to the host launcher; no launcher default is used. This is a hard total bound for the container command. |
| Launcher termination grace | 5 seconds | Explicitly supplied to the host launcher. The existing launcher escalates termination and records whether process exit was confirmed. |
| Free VRAM before launch | At least the configured deployment gate, which must be at least 12,288 MiB | The gate comes from validated deployment config and is checked with `nvidia-smi` immediately before launch. It is advisory and reserves no memory. |

The 4 CPU / 8 GiB / 128 PID values are reused bounded experiment settings, not production defaults. Before execution, inspect available host RAM and competing processes. If the host cannot accommodate the full 8 GiB cap plus operator-selected headroom, stop. No peak VRAM, peak RSS, CUDA concurrency or HTTP-worker memory measurement is established yet.

## Preflight and execution

The operator prepares `STT_CUDA_INPUT_DIR` with `stt-application.yaml`, `stt-deployment.yaml`, and existing empty `smoke-audio` and `smoke-audio.sha256` mount points. The model remains in its already provisioned location. The input directory, audio, checksum, model root, repository code and configs are mounted read-only; only the attempt's report directory is writable.

Before the command, record repository HEAD and changes, verify the approved image is already local and reports the expected digest/platform, inspect model/audio provenance, check Ollama and Dify health using their established operator checks, inspect active GPU processes, and review available RAM/disk. The host launcher additionally checks the local immutable image identity/platform, CUDA profile, audio digest, lock-file digest and current free VRAM. It never pulls an image (`--pull=never`). Any failed preflight stops before container launch.

Set the following values from operator configuration. Keep paths outside tracked files and do not place model/audio data in Git:

```sh
export STT_C3_ROOT="<operator-configured target-host staging root>"
export STT_CUDA_INPUT_DIR="$STT_C3_ROOT/input"
export STT_SMOKE_AUDIO="<approved audio file>"
export STT_CUDA_AUDIO_MEDIA_TYPE="audio/mp4" # M4A fixture; match approved fixture metadata
export STT_AUDIO_CHECKSUM_FILE="<approved checksum metadata file>"
export STT_MODEL_HOST_ROOT="<read-only model artifact root>"
export STT_CUDA_ATTEMPT_ROOT="$STT_C3_ROOT/attempts"
export STT_CUDA_ATTEMPT_ID="<fresh safe attempt identifier>"
export STT_CUDA_IMAGE_ID="sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540"
export STT_CUDA_LOCK_SHA256="68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14"
export STT_CUDA_MODEL_REVISION="d90ca5fe260221311c53c58e660288d3deb8d356"
export STT_CUDA_MODEL_MANIFEST_SHA256="1c955577f5ecc29540ddece161769cc69bae4e86fd8059f0862cff765b447e44"
export STT_CUDA_SHARED_GID="<operator-managed supplemental group ID>"
export STT_CUDA_PLATFORM="linux/amd64"
export STT_CUDA_HTTP_CPU_LIMIT="4"
export STT_CUDA_HTTP_MEMORY_BYTES="8589934592"
export STT_CUDA_HTTP_PIDS_LIMIT="128"
export STT_CUDA_HTTP_DEADLINE_SECONDS="180"
export STT_CUDA_HTTP_GRACE_SECONDS="5"
make -C "$STT_C3_ROOT" stt-cuda-http-integration PYTHON=/usr/bin/python3
```

`STT_CUDA_AUDIO_MEDIA_TYPE` is an explicit experiment setting sourced from the approved fixture metadata/configuration. The harness accepts only supported audio media types and checks a filename extension against the selected type when one is present. For an extensionless mount path, it generates a multipart filename with the matching canonical suffix; the current M4A fixture uses `audio/mp4` and `.m4a`. The MIME type is not inferred from the container mount path.

Stage the required current launcher, smoke harness, STT source, worker configuration, strict application/deployment configuration and approved checksum metadata under the target-host staging root. Verify staged file hashes against the workstation source before running the command. The operator-provided root is the Make working directory, so its relative `scripts`, `services` and `configs` mounts resolve on the target host; the target Git checkout is not used or modified. Keep the approved audio and model in their existing locations and bind-mount them read-only.

The host-side launcher uses Python's standard library plus the existing PyYAML configuration loader. It does not import aiohttp, faster-whisper, PyAV or CUDA modules. Use a target-host interpreter with PyYAML available; the approved image supplies the HTTP application runtime. The image, lock, model revision and manifest digest above are the approved C.2b identities. The host launcher compares the target-local image and staged lock with these values and compares model settings with the strict app configuration; the in-container harness repeats the lock, model manifest and audio integrity checks. The audio digest remains sourced from the supplied approved checksum file.

The Make target invokes the maintained host launcher, which validates the Docker argument vector before execution. The relevant container options are:

```text
docker run --rm --network none --platform linux/amd64 --pull never --read-only
  --user 65532:65532 --group-add <configured-group> --entrypoint python
  --gpus device=<deployment-config-index>
  --memory 8589934592 --cpus 4 --pids-limit 128
```

There are no published ports. The image is the approved immutable image; the harness invokes the current read-only repository source and the approved local model/audio artifacts. Runtime model downloads are disabled. A single HTTP request is sent; no warm-up or retry occurs. `make verify` does not run this target or start containers.

## Evidence and cleanup

The host launcher report and captured-output classifications remain in the attempt directory. The container harness report is atomically written under that attempt's `/results` directory. Neither report stores audio, transcript text, raw stderr or private absolute paths. The launcher enforces bounded output capture and does not delete attempt evidence when the container exits. Docker `--rm` removes only the one test container.

Review stage outcomes for report-mount verification, dependency inventory, strict configuration parsing, CUDA profile validation, artifact verification, HTTP worker integration, output validation and shutdown. Confirm health is alive, readiness becomes ready, the request succeeds, the supervised child is confirmed stopped, and the worker is no longer ready after close. Review `shutdown-report.json` even when HTTP integration fails; it separately records close completion, child-exit confirmation, readiness state and a fixed failure category. Recheck GPU state and Ollama/Dify health after the run. A successful TestServer request validates the production HTTP path in-container, not a listening service on the host or a production Compose deployment.

## Accepted run evidence

OBSERVED on 2026-10-17: HTTP 200; detected language `ru`; five nonempty segments with valid timestamp bounds; explicit CUDA device 0 / float16 with no CPU fallback. Model load was 2.549 s, transcription 0.959 s and HTTP integration 3.828 s. Shutdown was confirmed through worker lifecycle and supervisor child state; the container exited 0 and was removed. Ollama and Dify checks remained satisfactory. Sanitized reports are retained outside Git in the attempt directory referenced by the M02 milestone records.

NOT ESTABLISHED: instrumented peak VRAM, concurrency, sustained-load behavior, production latency/throughput, persistent deployment, or shared-service coexistence under active inference load. These observations are not production performance guarantees.

## Offline validation

```sh
.venv/bin/python -m unittest services.stt.tests.test_http scripts.test_stt_cuda_http_smoke scripts.test_stt_cuda_launcher scripts.test_stt_cuda_preflight -v
make governance-check PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
git diff --check
```

These tests use fake applications and configuration objects. They do not load a model, access a GPU, start Docker or establish runtime CUDA behavior.
