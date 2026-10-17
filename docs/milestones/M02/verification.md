# M02 verification

Status: M02-A remediation locally verified and user-accepted as PASS on 2026-10-17. Overall M02 remains incomplete.

## M02-A audit remediation verification

OBSERVED in the local repository workspace on 2026-10-17 (implementation verification):

- `PYTHON=.venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py' -v` — PASS; 40 deterministic STT tests passed.
- `make governance-check PYTHON=.venv/bin/python` — PASS. Governance structure validation passed; 2 governance tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS. Included Go vet, race-enabled Go tests and build; Ruff checks; configuration checks; rendered Compose and static topology checks; OpenAPI validation; 17 repository Python tests; and 40 STT tests.
- `git diff --check` — PASS.

The remediation tests cover fixed public error messages under private-path, credentials-like, transcript-like and native-library diagnostics; malformed, oversized, poll-failed and read-failed IPC; bounded terminate/kill phases with an injected process-control seam; unconfirmed cleanup readiness and deferred retained-byte release; no replacement before exit confirmation; cancellation/completion ordering; child crash during cancellation; repeated shutdown; and unknown/insufficient/sufficient CUDA free-memory observations.

One initial focused run after changing public errors exposed tests coupled to diagnostic strings and a test helper placed on a different test class. Those assertions were changed to verify stable error codes/diagnostic separation and the helper was corrected. The final focused suite and canonical verification above passed.

Tests use fake backends, injected IPC readers and fake process-control state. The process-control seam verifies bounded waits, ownership retention and recovery state; it does not prove kernel behavior after SIGKILL. The lifecycle HTTP test uses a local ephemeral loopback listener. No GPU, model artifact, external network, remote host, Docker service startup, or deployment was used. Canonical verification renders/checks Compose but does not start containers.

## Final closeout verification

OBSERVED in the local repository workspace on 2026-10-17 after user validation:

- Focused command `.venv/bin/python -m unittest discover -s services/stt/tests -v` — PASS; 40 tests passed.
- `make governance-check PYTHON=.venv/bin/python` — PASS; governance structure validation and 2 governance tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS; Go vet, race-enabled Go tests/build, Ruff checks, config checks, rendered Compose and topology validation, OpenAPI validation, 17 repository Python tests, 40 STT tests, governance validation and Python AST parsing passed.
- `git diff --check` — PASS.
- `git diff --cached --check` — run after staging; result recorded in the commit review below.

INTERPRETATION: local tests establish application behavior for the modeled process and admission paths, fixed safe error translation, strict configuration/artifact checks, and static deployment configuration.

NOT ESTABLISHED: actual inference engine behavior, real audio decoding/transcription, CUDA/GPU runtime or memory release, process behavior in uninterruptible kernel states, deployment network reachability, artifact immutability under concurrent mutation, production HTTP disconnect cancellation, performance/resource usage, or long-duration reliability.

Historical M01 and M02 design-closeout checks are not evidence of M02-A runtime behavior. See [plan](plan.md), [implementation](implementation.md) and [user validation](user-validation.md).

## M02-B CPU validation

OBSERVED in the local workspace on 2026-10-17:

- Model source: [Systran/faster-whisper-tiny at pinned revision](https://huggingface.co/Systran/faster-whisper-tiny/tree/d90ca5fe260221311c53c58e660288d3deb8d356). The pinned model card declares MIT and states the conversion is CTranslate2 format usable by faster-whisper. The model card describes conversion from OpenAI Whisper tiny, stored as FP16. The converter version is not stated upstream.
- Canonical manifest SHA-256: `1c955577f5ecc29540ddece161769cc69bae4e86fd8059f0862cff765b447e44`.
- Model artifact file SHA-256 values:

  | File | Size | SHA-256 |
  |---|---:|---|
  | `config.json` | 2,249 B | `a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8` |
  | `model.bin` | 75,538,270 B | `dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1` |
  | `tokenizer.json` | 2,203,239 B | `fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab` |
  | `vocabulary.txt` | 459,861 B | `34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913` |

- Hugging Face pinned repository metadata reports the same SHA-256 for `model.bin`; the downloaded file matched. Other files were integrity-recorded by the generated manifest after HTTPS retrieval at the immutable revision.
- Runtime versions observed in `.venv`: faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 19.0.1, NumPy 2.5.4, aiohttp 3.14.5, PyYAML 6.0.3. CPU configuration: `device_policy.mode=cpu`, 4 CPU threads, `int8`, beam size 1, 16 kHz mono decode, maximum 120 seconds / 64 MiB decoded audio.
- `make stt-cpu-integration PYTHON=.venv/bin/python` — PASS with explicit private config/audio variables and `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. Real response schema, Russian language (`ru`), five ordered in-range timestamp segments, health 200, initial readiness 503 followed by readiness 200, unknown alias 404, metrics privacy, and child exit after cleanup were checked. No transcript text was emitted. Audio SHA-256 before and after was identical: `ed017cfbfe4db867170f2bd7684dc2601aea560c33b25c9b61d3210769c1c7b0`.
- Two offline CPU runs observed readiness/load intervals of 0.466 s and 0.514 s, and transcription request durations of 0.526 s and 0.515 s. GNU `time` observed 300,708 KiB maximum RSS, 1.30 s elapsed and exit status 0 for the complete smoke command and child; this is not a worker-isolated RSS measurement.
- `.venv/bin/python -m unittest services.stt.tests.test_faster_whisper services.stt.tests.test_config_artifacts -v` — PASS; 15 focused tests passed, including upstream file-layout compatibility and manifest placement regression.
- `make governance-check PYTHON=.venv/bin/python` — PASS; governance structural validation and 2 governance tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS after the latest harness and configuration changes: Go vet/race tests/build; Ruff; all config checks; base plus CPU/CUDA Compose rendering/topology checks; 17 repository Python tests; 52 STT tests; governance and lock checks; Python AST validation. Compose was rendered only; no containers were started.
- `make governance-check PYTHON=.venv/bin/python` — PASS after final milestone documentation updates; 2 governance tests passed.
- `git diff --check` — PASS after final documentation updates.

INTERPRETATION: local offline CPU operation through the actual private HTTP transport and persistent inference child is demonstrated for this tiny model and permitted recording. The measured readiness/load interval includes HTTP server and test-harness setup through `/readyz` success; it is not an isolated CTranslate2 initialization benchmark.

NOT ESTABLISHED: broader transcription quality, cold-cache startup, representative CPU capacity, worker-only RSS, sustained load, CUDA execution, GPU passthrough, driver compatibility, GPU memory behavior, remote deployment reachability, coexistence under active Ollama/Dify load, and real HTTP client-disconnect behavior during inference. External network was used only to retrieve pinned public model files/metadata; inference passed with offline flags. No audio was uploaded, and runtime model loading uses the local artifact.

See [implementation](implementation.md) and [user validation](user-validation.md).

## M02-C.2a CUDA dependency-policy checks

OBSERVED in the local repository workspace:

- The CUDA dependency input now explicitly pins CTranslate2 4.8.3. The regenerated lock retains the resolved runtime versions and package artifact hashes for faster-whisper 1.2.1, CTranslate2 4.8.3, cuBLAS 12.9.2.10, cuDNN 9.27.0.42 and CUDA NVRTC 12.9.86; see the tracked lock diff for the CTranslate2 dependency annotation change.
- The lock checker enforces the approved CTranslate2/cuBLAS/cuDNN versions and rejects `nvidia-cuda-runtime-cu12`. The CPU dependency input and lock are unchanged.
- No maintained CUDA runtime probe exists in the repository. The earlier direct `libcudart.so.12` check belonged to a temporary probe and was not retained.
- Upstream policy references: [CTranslate2 4.8.3 changelog](https://github.com/OpenNMT/CTranslate2/blob/v4.8.3/CHANGELOG.md) records cuDNN 9 support beginning in 4.5.0 and removal of cuDNN 8 support; [faster-whisper 1.2.1 requirements](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/README.md) specifies CUDA 12/cuDNN 9 for the current CTranslate2 stack. The conflicting cuDNN 8 note in [CTranslate2 4.8.3 CONTRIBUTING.md](https://github.com/OpenNMT/CTranslate2/blob/v4.8.3/CONTRIBUTING.md#cuda-support-in-python-wheels) is treated as stale. The wheel note's static CUDA Runtime linkage means separate `libcudart.so.12` discovery is not a valid dependency gate.

INTERPRETATION: the static dependency policy is internally pinned and matches the selected upstream compatibility guidance. The policy check does not establish that a loaded model can execute on the target GPU.

NOT ESTABLISHED: no image was built, container run, model loaded or inference executed for this closeout. CUDA STT inference, GPU memory use, deployment, GPU passthrough in the production image, and coexistence under active Ollama/Dify load remain unverified. No M02-C phase status is advanced by these static checks.

## M02-C.2b bounded CUDA smoke evidence

OBSERVED on 2026-10-17 during the one user-authorized diagnostic attempt:

- Image: approved `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540`, linux/amd64. CUDA lock SHA-256: `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`. Runtime versions: faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 19.0.1, cuBLAS 12.9.2.10, cuDNN 9.27.0.42, NVRTC 12.9.86.
- Model: `Systran/faster-whisper-tiny`, upstream revision `d90ca5fe260221311c53c58e660288d3deb8d356`; manifest digest `1c955577f5ecc29540ddece161769cc69bae4e86fd8059f0862cff765b447e44`. Audio integrity was checked against the approved private checksum metadata; the digest is intentionally not repeated in tracked milestone records.
- Explicit CUDA device 0 and float16 were selected. The bounded production decoder completed, model load succeeded, the one transcription call returned, lazy segment iteration completed, and output validation passed: language `ru`, five segments and valid timestamp bounds. No transcript text was retained.
- Stage durations: model load 1.206437 s; `transcribe_call` 0.693926 s including audio decoding; segment iteration 0.248505 s; output validation 0.000465 s. This was one measurement on one short recording.
- Reported GPU was Quadro RTX 5000. Preflight free memory was 14,909 MiB. The available post-run observation returned to the same reported state. No instrumented peak VRAM measurement was made, and these observations are not a peak measurement.
- Ollama HTTP health was 200 before and after. Dify component checks were healthy before and after. Container exit was 0 and the attempt container was confirmed removed; the retained launcher and harness reports are in the operator's private staging area, outside Git.
- The run was isolated: network disabled, no published ports, non-root container, read-only root and input/artifact mounts, one writable results mount, one request, and a 180-second maximum. No model download, image rebuild or persistent deployment occurred.

INTERPRETATION: the approved faster-whisper/CTranslate2 CUDA path completed one tiny-model transcription with the production bounded audio decoder on the inspected host. The diagnostic used the same decoder path as the production adapter, avoiding faster-whisper 1.2.1's path-based PyAV call that passes the removed `metadata_errors` argument in PyAV 19.0.1. The production adapter was not changed by that diagnostic correction.

NOT ESTABLISHED: true peak VRAM/GPU utilization, concurrent or sustained performance, CUDA execution through the HTTP worker, CUDA cancellation behavior, large-v3-turbo behavior, capacity, persistent deployment and coexistence while Ollama/Dify are under active load. Structural segment validation and language detection do not establish transcription quality. User accepted the bounded C.2b smoke scope as PASS on 2026-10-17; overall M02 remains incomplete.

## M02-C.3 pre-run local implementation verification (historical)

OBSERVED in the local repository workspace:

- `.venv/bin/python -m unittest services.stt.tests.test_http scripts.test_stt_cuda_http_smoke scripts.test_stt_cuda_launcher scripts.test_stt_cuda_preflight -v` — PASS; 41 focused tests passed. Coverage includes fake HTTP decode errors with private diagnostics, admission capacity, request deadline cancellation, health/readiness separation, CUDA config/model/lock identity and override rejection, free-memory boundary parsing, Docker GPU/image/platform/resource/mount policy, and evidence-safe responses.
- Ruff formatting/checks for changed Python modules — PASS.
- No GPU, Docker container, model load, audio decode or inference was run. The canonical full verification result for this implementation is recorded after execution below.

INTERPRETATION: the focused suite validates local policy and test behavior with fakes. It does not establish that the target image starts the new harness, that the private model/audio mounts are correct on the target host, or that the worker performs CUDA inference over HTTP.

NOT ESTABLISHED: target-host image inspection, free VRAM at launch, CUDA HTTP inference, measured C.3 CPU/RAM/PID use, peak VRAM/RSS, application shutdown on the host, service coexistence during the request, or persistent deployment. M02-C.3 is not PASS.

OBSERVED in the local repository workspace after implementation:

- `make governance-check PYTHON=.venv/bin/python` — PASS; governance structure validation and 2 tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS; Go vet, race-enabled Go tests/build, Ruff checks, configuration checks, rendered Compose/static topology checks, 80 repository Python tests, 56 STT tests, governance validation, lock policy and Python AST parsing passed.
- `git diff --check` — PASS.
- `make -n stt-cuda-http-integration` with synthetic operator variables — PASS as a dry-run inspection. It only printed the launch recipe; it did not run Docker or contact a GPU.

INTERPRETATION: the canonical suite verifies the command validation, fake HTTP flow, config identity checks and static Compose configuration. Compose `config` rendering does not start services. No launch recipe was executed.

## M02-C.3 HTTP smoke harness correction — pre-run offline verification (historical)

OBSERVED in the local repository workspace:

- `STT_CUDA_AUDIO_MEDIA_TYPE` is passed explicitly from the experiment command configuration. The harness allowlists supported values, checks any filename suffix against the declared format, and adds the canonical suffix to an extensionless multipart filename. The M4A request therefore uses filename `.m4a` and `Content-Type: audio/mp4`, independent of the mounted path suffix. Artifact validation rejects unsupported or mismatched declarations before starting the test worker.
- The smoke harness writes a separate atomic `shutdown-report.json` from its `finally` path for successful and non-200 HTTP outcomes. It reports `completed_and_confirmed`, `attempted_but_unconfirmed`, or `failed_or_timed_out`, using existing TestClient, worker lifecycle and supervisor child state. Container removal is not used as child-exit evidence.
- `.venv/bin/python -m unittest scripts.test_stt_cuda_http_smoke -v` — PASS; 14 tests passed, including extensionless multipart metadata, unsupported/mismatched media types, successful and non-200 request shutdown evidence, unconfirmed cleanup and close failure/deadline classifications.
- `make governance-check PYTHON=.venv/bin/python` — PASS; governance validation and 2 tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS; Go vet/race tests/build, Ruff, configuration validation, Compose static checks, 86 script tests, 56 STT tests, governance and lock checks passed.
- `git diff --check` — PASS.
- No Docker, target-host access, CUDA initialization, model loading, audio decoding or inference was performed for this correction.

INTERPRETATION: offline tests establish the generated multipart metadata and safe shutdown-report behavior with deterministic fakes. They do not validate that the corrected harness has been staged on the target or that CUDA HTTP transcription succeeds there.

NOT ESTABLISHED at that point: the corrected multipart request on the target, real HTTP CUDA inference, target-side child cleanup, GPU/resource behavior and Ollama/Dify coexistence during a successful request. The later accepted target run is recorded below.

## M02-C.3 accepted target integration — OBSERVED 2026-10-17

- Target: operator-designated host reached as `wisper`; the target Git checkout was not used or modified. Two changed staged files (`Makefile`, `scripts/stt_cuda_http_smoke.py`) were synchronized. SHA-256 comparison confirmed all 26 staged runtime/source/config files matched current workstation source. Private app/deployment config and approved artifact metadata were validated against the accepted identities without copying them into Git.
- Provenance: immutable image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540` (`linux/amd64`); CUDA lock SHA-256 `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`; model revision `d90ca5fe260221311c53c58e660288d3deb8d356`; model manifest SHA-256 `1c955577f5ecc29540ddece161769cc69bae4e86fd8059f0862cff765b447e44`. Model artifact verification and approved audio digest validation passed. The request used an extensionless mount with generated multipart filename `smoke-audio.m4a` and configured media type `audio/mp4`.
- Preflight: Quadro RTX 5000, device 0, 14,909 MiB free of 15,360 MiB, 0% reported utilization and no compute process. The configured gate was 12,288 MiB. The command used 4 CPUs, 8 GiB memory, 128 PIDs, 180 seconds, network disabled, no published ports, non-root UID/GID 65532:65532 plus GID 1000, read-only code/config/artifact mounts, and the dedicated writable report mount.
- Harness outcome: all stages passed (report mount, dependency check, configuration parse, CUDA profile, artifact validation, HTTP integration, output validation and shutdown validation). The integration stage passed; per harness control flow, any response other than HTTP 200 fails that stage. The response schema and timestamp checks passed; language was `ru`, with five segments and valid timestamp bounds. The safe report recorded device `cuda`, compute type `float16`, and `cpu_fallback: false`. Dependency inventory matched the approved lock, including faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 19.0.1, cuBLAS 12.9.2.10, cuDNN 9.27.0.42 and NVRTC 12.9.86.
- Timings: model load 2.548835 s; transcription 0.958716 s; HTTP integration 3.827919 s.
- Shutdown: separate `shutdown-report.json` recorded `completed_and_confirmed`, `close_completed: true`, `child_exit_confirmed: true`, and `worker_not_ready: true`. Launcher process exit was 0 and confirmed; the created container was absent after cleanup.
- Shared services: Ollama HTTP health passed before and after. Dify API, database, Redis and sandbox health checks passed; web and proxy containers remained running, and the proxy returned HTTP 307 before and after. No shared service was modified.
- GPU postflight: 14,909 MiB free and 0% utilization sampled after cleanup, with no compute process. The equal before/after samples do not establish peak VRAM.
- Sanitized evidence is preserved outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.3/attempts/cuda-http-20261017-03/`: `launcher-report.json`, `harness/harness-report.json`, `harness/shutdown-report.json`, `stdout.json`, `stderr.json`, and `container.id`. Reports contain no audio or transcript fields. No private media, model weights, or diagnostic reports were copied into the repository.

INTERPRETATION: this is user-accepted evidence for one isolated CUDA transcription through the production aiohttp application and adapter. It does not establish general performance, capacity, persistent deployment, or active-load coexistence.

NOT ESTABLISHED: instrumented peak VRAM, concurrency, sustained-load behavior, production latency/throughput, persistent deployment, and coexistence under active Ollama/Dify inference load. Overall M02 remains incomplete.
