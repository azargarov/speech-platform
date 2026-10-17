# Offline-testable CUDA STT diagnostic harness

`scripts/stt_cuda_diagnostic.py` is a one-request diagnostic runner for a separately authorized CUDA validation container. It does not provision artifacts or launch containers. Before building operations, parsing configuration, importing worker modules, checking CUDA, or loading a model, it atomically creates and replaces an initial report in `/results`. It reads the report back and checks its owner, group, and mode. The first recorded stage repeats this write check. Failure returns a fixed `report_mount_validation` diagnostic and exits before inference work. The host launcher retains its own report if the container cannot write a harness report.

After that preflight, the harness uses the strict versioned STT configuration loaders, manifest verifier, runtime factory, device policy and `FasterWhisperBackend.load()` used by the worker. It makes the pinned faster-whisper public `WhisperModel.transcribe()` call directly so the call boundary and lazy segment iteration have separate timings and failure stages. The harness does not change production transcription behavior.

Before that model call, the harness decodes the validated audio through the bounded decoder used by the production faster-whisper adapter and passes its PCM array to `WhisperModel.transcribe()`. This avoids faster-whisper 1.2.1's path-based decoder, which calls `av.open(..., metadata_errors="ignore")`; the approved image's PyAV 19.0.1 removed that argument. The adapter's decoder calls `av.open()` without the removed keyword. The diagnostic's `transcribe_call` duration therefore includes audio decoding as well as the engine call; lazy segment consumption remains measured separately.

`scripts/launch_stt_cuda_diagnostic.py` is the separate host-side evidence layer. It creates an attempt directory before invoking Docker and atomically writes `launcher-report.json` before and after the command. Thus a missing container, Docker launch error, timeout, nonzero exit or missing Python report still has a host report. It captures stdout/stderr while draining the child pipes, but persists only byte counts, truncation state and fixed diagnostic classifications; raw process text is never written. This intentionally sacrifices arbitrary error detail to avoid persisting transcripts, secrets or paths. `container.id` is read only when it contains a valid Docker ID written via `--cidfile`. A container name is always recorded. The host report and harness JSON are independent.

The approved validation image metadata observed on 2026-10-17 reported `Config.Entrypoint=["python","/opt/validation/probe.py"]`, no `Cmd`, and user `65532:65532`. For a custom diagnostic command, explicitly override the entrypoint to `python` and pass the script path as its argument. Do not assume `python3` exists in this image based only on its entrypoint metadata. The failed startup attempt did not preserve enough stderr to establish whether that caused its exit.

The launcher records a conservative failure layer. Docker `run` exit codes 125, 126 and 127 receive distinct Docker/command classifications; other nonzero exits with a recorded container ID are labelled `container_start_or_process_failed` because OCI startup and the container process cannot always be separated from the exit code alone. Safe stderr classifications include common executable, mount, Python import, permission and runtime-start failures. Unmatched text remains redacted as `unclassified_output_redacted`.

Configuration parsing and CUDA profile validation are separate diagnostic stages. `--startup-only` parses both strict configuration files and reports the selected policy without requiring CUDA; it does not validate a CUDA profile, load a model, initialize CUDA or process audio. The CUDA diagnostic mode separately requires explicit `device_policy.mode: cuda`, faster-whisper schema version 3 configuration, CUDA device index 0 and a configured minimum-free-memory preflight of at least 12 GiB. The free-memory value is an advisory preflight threshold, not a reservation. The earlier temporary startup probe combined parsing with a CUDA-mode assertion. Its supplied app configuration selected CPU, making that assertion the best-supported explanation for the recorded `ValueError`; the retained report did not capture the exception message, so the exact failing statement is not established by the report.

## Report handling

The operator must provide an existing host directory mounted writable into the temporary container. The harness report path is explicit and controlled by the operator. The runner atomically replaces the JSON report after starting and completing each stage. It creates temporary files in the report directory, uses mode `0640`, fsyncs the file and directory, and removes a temporary file after successful replacement. The directory must grant access only to the operator and the container's configured non-root UID/group; group read allows the operator to inspect the report after the container exits. A host bind mount keeps the report after the container is stopped or removed. Do not use a container-only report path or a world-readable directory.

The launcher attempt root and each attempt directory are mode `0700`. The container receives only the attempt's `harness/` subdirectory as `/results`, so it cannot unlink or replace host launcher evidence. For container UID/GID `65532:65532`, pass a host supplemental group with `--shared-gid`; the launcher sets the `harness/` subdirectory to that group and mode `2770`, and requires the exact `--group-add` to match. The host operator must belong to the group. Before invoking Docker, the launcher checks directory owner, group, exact mode, POSIX ACL absence, parent traversal, container identity and the writable bind-mount arguments. These checks describe host metadata; they do not claim effective container access. The harness then proves effective access as the actual container user by atomically creating/replacing and reading the initial report before application imports or configuration checks. If that check fails, it emits only a fixed safe classification; the launcher preserves the host report and classifies the failure. Launcher report and sanitized stdout/stderr files are mode `0600`; the container cannot access them. The harness report uses `0640`, so the operator can read it through the shared group after exit. Do not make the attempt root world-readable or writable. No host-side impersonation with `setpriv` or `sudo` is required.

Every attempt directory is retained. The launcher accepts at most 20 attempt directories and refuses another attempt at that bound; it does not automatically delete old evidence. Output capture is capped at 64 KiB per stream before classification, and arbitrary output is redacted. After reviewing and preserving any evidence required for operations, an operator may explicitly delete a selected attempt directory by exact path. Do not use broad cleanup or Docker prune commands. Keep only the required retention period under the organization's private-data policy; the launcher does not silently expire reports.

The report contains stage names, durations, outcomes, exception type, a conservatively allowlisted message, safe traceback frame metadata (basename, line and function), model alias/revision and manifest digest, audio SHA-256, language, segment count, timestamp validation, device/compute type, and pinned dependency versions. It does not include audio bytes, segment text, transcript, source lines, or configured absolute paths. Unknown exception messages are suppressed; paths and credential-like values cause the entire message to be replaced with `<message-redacted>`. Frame filenames are reduced to basenames.

## Future separately authorized invocation

The application config must be schema v3 with `device_policy.mode: cuda`; the deployment config must define CUDA device index and the minimum-free-memory preflight. The model directory, manifest, audio, configs, lock and writable report directory must be mounted read-only except the report directory. Disable network, publish no ports, use the approved immutable image and explicit GPU device exposure. Dependency lock validation and artifact/audio checks occur before model loading. The runner rejects CPU or auto mode, checks the selected and loaded engine device, and never retries or falls back.

Example command inside that authorized validation container (paths are container mount points, not host defaults):

```sh
python scripts/stt_cuda_diagnostic.py \
  --application-config /input/stt-application.yaml \
  --deployment-config /input/stt-deployment.yaml \
  --audio /input/smoke-audio \
  --lock services/requirements-stt-cuda.lock \
  --report /results/stt-cuda-diagnostic.json
```

For an offline startup-only configuration check, use the same script with `--startup-only`, `--application-config`, `--deployment-config` and `--report`. Omit `--audio` and `--lock`; this mode runs only the generic configuration parsing stage and never applies CUDA-specific profile policy.

Before execution, separately verify the image digest, lock hash, model manifest and audio digest, host service health, active GPU processes and the approved free-VRAM threshold. The report itself establishes only what the harness observed; successful model construction or device inspection is not proof of inference execution. A `pass` report means the one transcription call completed, its segment iterator was consumed, and metadata/timestamp checks passed. It is not a production deployment or capacity guarantee.

### Host launcher command for a separately authorized retry

This is a template, not authorization to run it. Set the variables only after the required preflight and mount-permission checks. `SP_CUDA_IMAGE_ID` must contain the separately approved immutable image ID. `SP_AUDIO_CHECKSUM_FILE` must reference the approved sha256sum-format record for the permitted audio; the host launcher and container harness read this same file, and the same file is mounted read-only into the container. `SP_ATTEMPT_ID` must be a fresh safe token; the launcher refuses reused IDs and refuses more than 20 retained attempts. `SP_SHARED_GID` must identify an operator-managed group that the host operator belongs to and that is added to the non-root container. The model, audio, checksum metadata, config, code and lock mounts are read-only; `/results` is the new retained attempt directory.

```sh
umask 077
python3 scripts/launch_stt_cuda_diagnostic.py \
  --attempt-root "$SP_ATTEMPT_ROOT" \
  --shared-gid "$SP_SHARED_GID" \
  --attempt-id "$SP_ATTEMPT_ID" \
  --container-name "$SP_ATTEMPT_ID" \
  --image-id "$SP_CUDA_IMAGE_ID" \
  --audio-file "$SP_AUDIO_FILE" \
  --audio-checksum-file "$SP_AUDIO_CHECKSUM_FILE" \
  --platform linux/amd64 \
  --lock-sha256 "$SP_CUDA_LOCK_SHA256" \
  --timeout-seconds 180 --grace-seconds 5 \
  -- docker run --rm --network none --read-only \
    --name "$SP_ATTEMPT_ID" --cidfile '{attempt_dir}/container.id' \
    --user 65532:65532 --group-add "$SP_SHARED_GID" \
    --entrypoint python \
    --gpus device=0 --memory 8g --cpus 4 --pids-limit 128 \
    --mount "type=bind,src={harness_dir},dst=/results" \
    --mount "type=bind,src=$SP_MODEL_DIR,dst=/models,readonly" \
    --mount "type=bind,src=$SP_AUDIO_FILE,dst=/input/smoke-audio,readonly" \
    --mount "type=bind,src=$SP_AUDIO_CHECKSUM_FILE,dst=/input/smoke-audio.sha256,readonly" \
    --mount "type=bind,src=$SP_CONFIG_DIR,dst=/input,readonly" \
    --mount "type=bind,src=$SP_REPOSITORY_DIR/scripts,dst=/opt/validation/scripts,readonly" \
    --mount "type=bind,src=$SP_REPOSITORY_DIR/services,dst=/opt/validation/services,readonly" \
    --workdir /opt/validation \
    --env HF_HUB_OFFLINE=1 --env TRANSFORMERS_OFFLINE=1 \
    --env PYTHONPATH=/opt/validation \
    "$SP_CUDA_IMAGE_ID" \
    scripts/stt_cuda_diagnostic.py \
      --application-config /input/stt-application.yaml \
      --deployment-config /input/stt-deployment.yaml \
      --audio /input/smoke-audio \
      --audio-checksum-file /input/smoke-audio.sha256 \
      --lock /opt/validation/services/requirements-stt-cuda.lock \
      --report /results/harness-report.json
```

The launcher substitutes `{attempt_dir}` and `{harness_dir}` only in command arguments and does not log the argument vector or environment. It enforces `docker run`, `--network none`, no published ports and an explicit non-root `--user`. Review the command's read-only mounts, resource limits, GPU selection and image before a separately authorized run. The report directory must be writable by the Docker CLI on the host and by UID 65532 through the added group. The attempt directory, including reports, survives Docker's `--rm`; cleanup of a container does not remove host evidence. `container.id` is durable if Docker created it. The launcher command exits nonzero for any outcome other than a successful process with a harness report.

When a bind mount is nested beneath another read-only bind mount, the nested destination must already exist inside the parent mount source. Docker cannot create a missing nested mountpoint inside a read-only parent. The launcher checks this condition before starting Docker; for example, keep an empty `smoke-audio` placeholder in the staged input directory when the approved audio file is mounted over `/input/smoke-audio`.

Offline harness tests use fake model and generator objects. Run them with:

```sh
.venv/bin/python -m unittest scripts.test_stt_cuda_diagnostic -v
```
