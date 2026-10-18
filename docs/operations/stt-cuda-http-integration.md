# M02-C.3 CUDA HTTP integration runbook

Status: M02-C.3 was accepted PASS for the bounded one-request CUDA HTTP integration scope on 2026-10-17. The third controlled attempt passed after explicit fixture media type handling. This runbook describes the validated procedure; any additional target execution requires separate authorization. Overall M02 remains incomplete.

## What the check exercises

`scripts/stt_cuda_http_smoke.py` starts the production `create_http_app()` in an aiohttp `TestServer`, waits for health/readiness, sends one multipart request by default through `/internal/v1/transcriptions`, validates the response and closes the test client. Its measurement mode can send a configured bounded sequence through that same worker instance. Each complete response is schema/timestamp validated before the next request starts. The route uses the existing application, admission controller, inference supervisor and faster-whisper adapter. The server binds only the test server's loopback socket; it is not a persistent worker or a public endpoint.

The harness reuses strict application/deployment loaders, the worker configuration loader, the CUDA profile validator, the installed-lock check, the artifact manifest verifier, the shared audio checksum verifier, and the existing atomic sanitized report runner. It validates each response text in memory but reports no transcript or segment text. Reports contain identity digests, selected config values, statuses, allowlisted public error codes, fixed failure categories, per-request duration, fixture audio duration, request-level real-time factor, response language/segment metadata, resource summaries and shutdown state. The process-cold model-load measurement is the interval from test-server startup until readiness; it includes harness/server setup and is not a model-loader-only timer. The first and subsequent request durations cover full HTTP round trips. The production worker contract does not expose inference-only timing, so that field is null with an explicit reason code. Legacy C.3 fields `model_load_seconds` and `transcription_seconds` remain as aliases; the latter is explicitly tagged as the first request's full HTTP duration. Error response bodies and messages are never persisted. A separate `shutdown-report.json` records whether TestClient shutdown completed with child exit and worker readiness confirmed, was attempted but remains unconfirmed, or failed/exceeded its configured deadline. Container removal alone does not establish child cleanup.

Optional resource sampling uses one bounded daemon thread and constant-space aggregation. NVML records device memory and, when available and visible in the container PID namespace, memory attributed to worker-descendant PIDs. `/proc` RSS sampling follows the harness process and its descendants. The sampler performs observations and cgroup v2 `memory.peak` or v1 high-water reads on that same thread. Shutdown waits only for the remaining experiment deadline; if the thread has not exited, the report says `stop_unconfirmed` and retains the samples already collected. It never performs a synchronous final NVML or RSS query after the wait. GPU and RSS maxima are labelled `sampled_peak`; periodic samples may miss short peaks. The cgroup high-water value is a cgroup measurement, not process RSS. Reports include interval, sample counts and fixed missing-data codes. Resource sampling is disabled unless its interval is configured; the default one-request C.3 behavior remains intact.

The overall deadline is established before diagnostic stages begin and is also enforced by the host launcher's timeout around the Docker command. Worker startup and sequential requests share one absolute deadline; each request is limited by both the configured per-request timeout and the remaining shared work budget. A portion of that budget is reserved for bounded worker/client shutdown and sampler termination. The launcher's outer timeout includes in-container shutdown and diagnostic report writes. A timed-out launcher process does not establish that Docker removed the daemon-side container.

## Configuration sources and precedence

There is no additional C.3 YAML schema. Values have one source each:

1. **Application config (schema v3)** owns model alias/identity, explicit `device_policy.mode: cuda`, CUDA compute type (`float16`), request and upload bounds, and model/request deadlines.
2. **Deployment config (schema v2)** owns artifact filesystem references, CUDA device index and minimum free-memory gate. The existing CUDA profile validator rejects a missing or below-approved gate; the value used by the host preflight and worker is read from this config.
3. **Worker config** supplies the already validated readiness poll interval. The in-process test server does not bind the configured service port.
4. **Approved artifact metadata** supplies the expected tiny-model revision/manifest, CUDA lock digest, image digest/platform and audio SHA-256. The model and lock identities are compared with strict config/source files; the audio path is only a local file reference, and host/container checks use the same checksum metadata.
5. **Experiment command settings** supply the approved identities, report root, attempt identity, shared group, overall deadline, termination grace and container CPU/RAM/PID limits. `STT_CUDA_HTTP_REQUEST_COUNT` selects the number of sequential requests (default `1`); `STT_CUDA_HTTP_MAX_REQUEST_COUNT` is the explicit bound (default `1`). Both are positive integers, the count cannot exceed the configured bound, and the report safety limit caps the bound at 1,000 requests. The independent overall deadline bounds execution time. `STT_CUDA_RESOURCE_SAMPLE_INTERVAL_SECONDS` enables sampling; values below 0.1 seconds or above the overall deadline are rejected. The deadline bounds sample count. Docker flags are parsed and validated by the maintained launcher. No environment variable can override application or deployment settings.

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

There are no published ports. The image is the approved immutable image; the harness invokes the current read-only repository source and the approved local model/audio artifacts. Runtime model downloads are disabled. One HTTP request is sent by default; no warm-up or retry occurs. For a separately authorized measurement run, set both request-count variables, for example `STT_CUDA_HTTP_REQUEST_COUNT=3 STT_CUDA_HTTP_MAX_REQUEST_COUNT=3`, and optionally `STT_CUDA_RESOURCE_SAMPLE_INTERVAL_SECONDS=1`. Requests remain sequential in one worker process and model instance. `make verify` does not run this target or start containers.

## Evidence and cleanup

The host launcher report and captured-output classifications remain in the attempt directory. The container harness report is atomically written under that attempt's `/results` directory. Neither report stores audio, transcript text, raw stderr or private absolute paths. The launcher enforces bounded output capture and does not delete attempt evidence when the container exits. Docker `--rm` removes only the one test container.

Review stage outcomes for report-mount verification, dependency inventory, strict configuration parsing, CUDA profile validation, artifact verification, HTTP worker integration, output validation and shutdown. Confirm health is alive, readiness becomes ready, the request succeeds, the supervised child is confirmed stopped, and the worker is no longer ready after close. Review `shutdown-report.json` even when HTTP integration fails; it separately records close completion, child-exit confirmation, readiness state and a fixed failure category. Recheck GPU state and Ollama/Dify health after the run. A successful TestServer request validates the production HTTP path in-container, not a listening service on the host or a production Compose deployment.

If the launcher report indicates a timeout and `exact_container_postflight_required: true`, inspect and clean up only the recorded container ID. Read the 64-character ID from that attempt's `launcher-report.json`; do not use `docker ps -aq`, `docker rm -f` without an ID, or any prune command. The following bounded sequence uses that exact ID:

```sh
CID="$(python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))["container"]["id"]; print(v if isinstance(v,str) and len(v)==64 and all(c in "0123456789abcdef" for c in v) else "")' "$ATTEMPT_DIR/launcher-report.json")"
test -n "$CID" || { echo "no verified container ID; stop for operator investigation" >&2; exit 1; }
if docker container inspect "$CID" >/dev/null 2>&1; then
  RUNNING="$(docker container inspect --format '{{.State.Running}}' "$CID")"
  if [ "$RUNNING" = true ]; then
    timeout 10s docker stop --time 5 "$CID"
  fi
  if docker container inspect "$CID" >/dev/null 2>&1; then
    RUNNING="$(docker container inspect --format '{{.State.Running}}' "$CID")"
    if [ "$RUNNING" = true ]; then
      timeout 10s docker kill "$CID"
    fi
    RUNNING="$(docker container inspect --format '{{.State.Running}}' "$CID")"
    if [ "$RUNNING" = false ]; then
      docker container rm "$CID"
    else
      echo "container exit remains unconfirmed; stop for operator investigation" >&2
      exit 1
    fi
  fi
fi
```

If inspection shows the container is already absent, record that observed state. If stop/kill does not confirm exit, preserve the attempt evidence and stop; do not broaden cleanup. A `stop_unconfirmed` sampler report likewise means sampler-thread termination was not observed before its deadline. Container removal may end that daemon thread, but it is not evidence that the sampler stopped cleanly or that GPU memory was released before container exit.

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

## STT worker fault and recovery procedure

This section records the current application recovery contract and a conservative operator procedure. It is not a deployment recipe: persistent STT deployment and its exact Compose project/service identifiers are not established until the separately gated C.6 work. Do not run recovery commands against the C.3/C.4 diagnostic containers except during a separately authorized attempt.

### Observed recovery semantics

- **Unexpected inference-child exit or fatal backend failure:** the supervisor latches `faulted`, confirms/reaps the child when possible, and the application latches the model as `faulted`. `/healthz` can remain 200 while the worker process is serving; `/readyz` is 503 and transcription is rejected with the existing safe `not_ready` response. The child is not automatically restarted or reused.
- **Model-load failure or timeout:** startup readiness is not reached. A timed-out child is terminated/reaped within the configured bounds; if exit is confirmed, startup remains failed/not ready. If exit is unconfirmed, the application exposes `/readyz` as 503 `cleanup_unconfirmed` and rejects work. There is no automatic reload loop or CPU fallback.
- **Request deadline or client cancellation:** cancellation is first cooperative. When the child returns cooperatively, the worker can remain ready. If execution does not stop within the configured grace, the supervisor escalates termination and latches the worker/model fault. The active slot and retained audio stay owned until child exit is confirmed.
- **`cleanup_unconfirmed`:** `/readyz` returns 503 with the fixed `cleanup_unconfirmed` code. Admission remains fault-latched, readiness does not automatically recover, and no replacement child is started. A bounded background reaper may later observe exit, but it does not reset application lifecycle/admission state. Operator action and a controlled worker restart are required after process exit is independently confirmed.
- **Worker shutdown:** normal close requests cooperative shutdown then uses bounded termination escalation. The supervisor's child state and lifecycle determine whether close is confirmed, faulted, or cleanup-unconfirmed. Diagnostic `shutdown-report.json` reports `completed_and_confirmed`, `attempted_but_unconfirmed`, or a fixed failed/timed-out category. Container exit/removal alone does not prove child reaping or GPU-memory release.

These statements describe current code/tests: `services/stt/supervisor.py`, `services/stt/application.py`, `services/stt/lifecycle.py`, and `services/stt/http_server.py`. The injected process-control tests do not prove kernel behavior for uninterruptible tasks or native CUDA context cleanup.

### Operator steps for an authorized persistent deployment

1. **Preserve evidence first.** Copy the exact attempt's `launcher-report.json`, harness report, `shutdown-report.json` when present, bounded stdout/stderr classifications, and postflight observations to the approved private evidence location. Preserve timestamps and hashes. Do not copy audio or transcript data into reports or Git.
2. **Identify one worker.** Use the approved deployment's configured Compose project and STT service labels to list candidates. Match the image digest, project/service labels, creation time, and the recorded container ID. Require exactly one intended worker. If the identity is ambiguous, stop. Do not use global process selection, `docker ps -aq`, wildcard removal, or pruning.
3. **Check lifecycle.** Query `/healthz` and `/readyz` through the existing private route. Health 200 means the HTTP worker process is live; it does not mean the model is usable. Readiness 200 is required before sending work. Readiness 503 `not_ready` means the model is unavailable; `cleanup_unconfirmed` means child exit has not been established. Inspect the sanitized attempt/shutdown report and exact container state.
4. **Distinguish a live child from a stale PID.** Do not trust a PID value alone; PIDs can be reused and container PIDs differ from host PIDs. Inspect the exact container's process list (`docker top <exact-container-id>`) and state (`docker inspect <exact-container-id>`), correlate the process with the container namespace and current start time, and compare with supervisor evidence. The platform does not maintain a PID file as recovery authority. If process identity or exit cannot be established, stop and escalate; do not signal a host PID.
5. **Handle uncertain cleanup conservatively.** While `cleanup_unconfirmed` is reported, do not submit more requests, start a replacement inference child, or restart the worker. Allow only the configured bounded process-control/reaper interval to report exit. If still uncertain, preserve evidence and escalate to the host operator. Do not kill unrelated processes, reset the GPU, or infer memory release from a termination request.
6. **Stop only the exact worker if authorized.** For a recorded exact container ID, request a bounded stop using the deployment's configured grace and inspect that same ID. If it remains running after the bound, a bounded kill may target only that ID under the deployment's approved procedure. Remove it only after Docker reports it stopped. Never use `docker compose down`, broad `docker kill`, or Docker prune for recovery. If exact exit/removal cannot be confirmed, stop and escalate.
7. **Check GPU visibility without disturbing workloads.** Use the host's approved NVIDIA process and memory inventory before and after the exact worker cleanup. A visible Speech Platform process disappearing is supporting evidence only; NVML process visibility may be incomplete, and free VRAM does not prove a context was released or reserve capacity. Do not terminate other GPU processes or perform a GPU reset. If a Speech Platform process remains, attribution is unclear, or Ollama/Dify health degrades, stop and escalate.
8. **Recover only after cleanup is confirmed.** Start/recreate only the named STT service using the reviewed deployment mechanism once C.6 defines it; do not restart Ollama, Dify, Docker, or the whole Compose project. Check `/healthz`, then wait for `/readyz` 200 and verify the configured model identity/readiness report before permitting requests. A 200 health response by itself is insufficient. If readiness does not return within the configured startup deadline, preserve evidence and leave the worker unavailable for operator review.
9. **Verify shared services and close the incident.** Repeat the established Ollama and Dify health checks and compare GPU process/resource observations with pre-recovery evidence. Record only sanitized statuses, exact worker identity, lifecycle result and cleanup evidence. Any unexplained GPU allocation, child/container uncertainty, repeated model-load failure, OOM indication, or shared-service degradation requires operator escalation; do not retry automatically.

For a diagnostic attempt, the launcher timeout procedure above remains exact-container scoped. Do not adapt this section into persistent deployment commands until C.6 approval establishes the project, service, restart policy, and rollback procedure.
