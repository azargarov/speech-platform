# M02 verification

Status: M02-A/B/C.2b/C.3 and bounded M02-C.4/C.5/C.6A/C.6B-R1/R2 evidence is PASS for accepted scopes. C.5A and C.5B are accepted for deterministic offline fault handling and operator-procedure scope. C.6B Phase A read-only preflight is complete with blockers. Production image build and C.6B-R3/C.6C are NOT STARTED. Overall M02 remains INCOMPLETE.

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

## M02-C.4A target-model provisioning and offline integrity — OBSERVED 2026-10-17

OBSERVED on the workstation, using the approved immutable source identity:

- Repository: `dropbox-dash/faster-whisper-large-v3-turbo`; revision: `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`. Hugging Face Hub metadata resolved the requested repository and exact revision before transfer and reported MIT licensing. No mutable `main` reference was used for provisioning.
- Private artifact root: `private/models/faster-whisper-large-v3-turbo/`. Manifest: `private/models/faster-whisper-large-v3-turbo-manifest.yaml`. Both paths are ignored by Git.
- Manifest SHA-256 (canonical project digest): `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
- Artifact format: `ctranslate2-whisper`. The manifest records the upstream repository, immutable revision, family, conversion format, source conversion metadata, normalized relative paths, byte sizes and SHA-256 for each required file. The upstream card does not state a converter version.
- `config.json`: 2,263 bytes; SHA-256 `b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e`.
- `model.bin`: 1,617,884,929 bytes; SHA-256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`, matching the approved published digest.
- `preprocessor_config.json`: 340 bytes; SHA-256 `7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711`.
- `tokenizer.json`: 2,710,337 bytes; SHA-256 `297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd`.
- `vocabulary.json`: 1,068,114 bytes; SHA-256 `c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1`.
- Total artifact size: 1,621,665,983 bytes. The production `services.stt.artifacts.verify_artifact` verifier passed against the generated manifest and exact five-file artifact set. `git check-ignore -v` confirmed both the model root and manifest are ignored.

INTERPRETATION: this establishes local provenance and byte integrity for the provisioned CTranslate2 artifact. It does not establish successful model loading, CUDA compatibility, inference, resource use, or target-host availability.

NOT ESTABLISHED at the time of C.4A provisioning: model load or transcription behavior, GPU memory requirements, performance, transcription quality, and deployment compatibility. No model was loaded; no GPU, Docker, target host, or shared service was accessed. The later C.4B harness work was then offline-only; C.4 had not yet passed. Later Phase B/C target evidence is recorded below.

## M02-C.4B offline measurement harness — OBSERVED 2026-10-17

OBSERVED in the workstation repository:

- `.venv/bin/python -m unittest scripts.test_stt_cuda_http_smoke scripts.test_stt_resource_sampling -v` — PASS; 25 tests passed. Coverage includes the one-request default, validated sequential requests and ordering, count/deadline/sample-interval bounds, request timing and RTF, audio-duration metadata, sanitized partial reports, sampled peak aggregation, cgroup/RSS separation, unavailable measurement sources, and one bounded sampler thread.
- `make governance-check PYTHON=.venv/bin/python` — PASS; governance structure validation and 2 tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS; Go vet/race tests/build, Ruff, configuration validation, Compose static checks, 97 repository script tests, 56 STT tests, governance checks, dependency-lock checks and Python AST parsing passed.
- `git diff --check` — PASS.
- `make -n stt-cuda-http-integration` with synthetic experiment variables — PASS as a dry-run inspection. It confirmed the request count, explicit maximum, overall deadline and optional sample interval reach the maintained in-container harness. The target was not executed.
- No target host, Docker container, model load, audio decode, CUDA initialization, inference, or Ollama/Dify service was accessed.

INTERPRETATION: offline tests establish deterministic harness logic and allowlisted report behavior. The C.3 one-request default and existing production HTTP route remain in use. The verifier does not establish that NVML, `/proc` process attribution, or cgroup memory files will be available in a future target container; those sources are reported as missing when unavailable.

NOT ESTABLISHED at the time of the C.4B offline verification: large-v3-turbo loading/transcription, CUDA HTTP operation for that model, cold/warm performance, request RTF, memory use, instrumented peak GPU memory, sustained behavior, resource thresholds, or capacity. Later target experiments are recorded below.

## M02-C.4 Phase A — target artifact staging — PASS for integrity scope

OBSERVED: the approved model identity was `dropbox-dash/faster-whisper-large-v3-turbo`, immutable revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, CTranslate2 faster-whisper format. Canonical manifest SHA-256 was `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`; `model.bin` SHA-256 matched the approved value `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`. The five-file artifact inventory totaled 1,621,665,983 bytes. The production artifact verifier passed on the staged release. No model was loaded and no inference was performed during Phase A.

INTERPRETATION: Phase A establishes verified artifact staging for this immutable release. It does not establish CUDA compatibility, model behavior, performance or resource use.

## M02-C.4 Phase B — one-request large-model CUDA HTTP validation — PASS for bounded scope

OBSERVED: approved image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540` (`linux/amd64`) and CUDA lock digest `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14` were used. The successful attempt used the approved model revision and manifest, explicit CUDA device 0 / float16 and no CPU fallback. The HTTP response was 200, language `ru`, six segments with valid timestamp bounds; reported model load was 9.163265 s and request duration was 1.262039 s. Shutdown and child exit were confirmed; launcher exit was 0 and the container was removed. Evidence is preserved outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.4/attempts/large-v3-turbo-http-20261018-03/`.

Historical Phase B failure: attempt `large-v3-turbo-http-20261018-01` passed startup/configuration checks but failed artifact validation before model load because the non-root process lacked group read/execute permission to enumerate the artifact directory. The separate non-GPU diagnostic `c4-artifact-permission-20261018-01` passed the production verifier after the minimal temporary directory permission adjustment. The successful retry used temporary mounted model-root/artifact modes `2710`/`2750`, then restored original `2700`/`2700`. No inference occurred in the failed attempt.

## M02-C.4 Phase C — three sequential large-model CUDA HTTP measurements — PASS for bounded scope

OBSERVED on 2026-10-18: one container ran exactly three sequential requests through the production STT HTTP application and the same loaded worker. Image, lock, model revision, canonical manifest and audio checksum validation passed. Effective limits were 4 CPUs, 12 GiB memory, 128 PIDs, a 180-second overall deadline, one-second sampling and a 14,336 MiB pre-launch free-VRAM gate. Preflight measured GPU 0 at 14,909 MiB free of 15,360 MiB with no compute process, and host available RAM at 61,996,523,520 bytes. Ollama HTTP returned 200 and Dify proxy/core health checks passed before the run.

- Model/runtime: `dropbox-dash/faster-whisper-large-v3-turbo`, revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`; manifest `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`; faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 19.0.1, CUDA libraries per the approved lock (cuBLAS 12.9.2.10, cuDNN 9.27.0.42, NVRTC 12.9.86). Explicit `cuda`, device 0, `float16`; `cpu_fallback: false`.
- Worker readiness took 8.663653 s from process startup. This process-cold measure is start-to-readiness, not an isolated model-loader timer. All three requests returned HTTP 200, detected `ru`, produced six segments, and passed timestamp-bound checks for the 21.205333 s fixture.
- Request 1: 1.180356 s, RTF 0.055663. Request 2: 0.701624 s, RTF 0.033087. Request 3: 0.783993 s, RTF 0.036972. The worker contract does not expose inference-only duration; reported values are full HTTP request durations.
- Resource sampling: 12 samples at one-second interval. Sampled maximum device-wide used GPU memory was 2,795,962,368 bytes; sampled device-free memory is not a reservation. cgroup memory high-water was 1,775,648,768 bytes from one observation. Sampled process-tree/harness RSS maximum was 104,189,952 bytes. NVML process memory was unavailable (`process_not_visible`) and descendant RSS aggregated to zero; child-specific memory attribution is therefore NOT ESTABLISHED. No instrumented peak VRAM measurement was taken.
- Shutdown report: `completed_and_confirmed`, child exit confirmed, worker no longer ready; sampler stopped. Launcher exit 0 and exact-container inspection confirmed removal. Temporary directory modes were restored exactly to the original `2700`/`2700`. Postflight GPU free memory was 14,909 MiB with no compute process. Ollama returned HTTP 200; Dify proxy returned 307 and core API/database/Redis/sandbox health remained satisfactory.
- Evidence remains outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.4/attempts/large-v3-turbo-http-phase-c-20261018-01/`: `launcher-report.json`, `harness/harness-report.json`, `harness/shutdown-report.json`, `operator-postflight.json`, and sanitized stdout/stderr classifications.

Historical Phase C preflight-only failures: one wrapper began Python imports before changing to the staged source root (`ModuleNotFoundError`); a later dry-run check omitted the configured environment from its subprocess and falsely rejected the effective command. Neither changed permissions or launched a container. The wrapper was corrected and preflight rerun before the single successful Phase C experiment.

INTERPRETATION: C.4 PASS covers artifact integrity, one bounded CUDA HTTP request, three sequential requests against one worker, response metadata validation, sampled resource observations and confirmed normal cleanup under the recorded configuration. The three requests are too few to establish capacity or stable performance thresholds.

NOT ESTABLISHED: concurrency capacity, sustained-load performance, exact peak VRAM, child-specific GPU/RSS, transcription-only latency, active GPU workload coexistence with Ollama/Dify, forced CUDA-child cleanup, production latency/throughput and persistent deployment. Shared-service health before/after does not establish behavior under simultaneous active GPU workloads. Overall M02 remains incomplete.

## M02-C.5A offline fault-injection verification — OBSERVED

- Focused command `.venv/bin/python -m unittest services.stt.tests.test_faster_whisper services.stt.tests.test_runtime services.stt.tests.test_http -v` — PASS; 40 tests passed after the C.5A changes.
- `make governance-check PYTHON=.venv/bin/python` — PASS; governance structural validation and 2 tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS; Ruff, formatting check, Go vet/race tests/build, configuration validation, rendered Compose and static topology checks, 105 repository script tests, 60 STT tests, governance and dependency-lock checks passed. Compose was rendered only; no containers were started.
- `git diff --check` — PASS.
- No target host, Docker daemon, model artifact, CUDA runtime, GPU, inference, or shared Ollama/Dify service was accessed.

The new tests directly cover explicit CUDA construction failure without CPU fallback; bounded decoded-audio allocation failure as `resource_exhausted`; safe HTTP 503 mapping; admission release and readiness after a recoverable resource failure followed by a successful request; and exact `model_load_failed` classification for an unresponsive load timeout. Existing named tests continue to cover overload, disconnect/cancellation, request deadlines, child crash, bounded forced termination, no replacement under unconfirmed cleanup, readiness fault latching, resource ownership, and shutdown diagnostic classifications.

INTERPRETATION: deterministic fault injection verifies these software contracts and application-visible outcomes. It does not establish native CUDA driver behavior, actual cgroup OOM handling, GPU memory release after forced termination, or shared-GPU behavior under simultaneous active load.

NOT ESTABLISHED: real CUDA failure cleanup or OOM behavior, persistent deployment, and active GPU workload coexistence. No target experiment was justified by the offline gaps. C.5A was accepted for its deterministic offline scope; overall C.5 PASS was recorded after the separate C.5B user acceptance below.

## M02-C.5B offline recovery-procedure review — OBSERVED

- Reviewed supervisor, application, lifecycle, HTTP readiness, diagnostic shutdown-report and launcher exact-container behavior. The documentation-only update records those current semantics and points out which deployment procedures cannot yet be exact because persistent C.6 deployment is not established.
- Focused suites and fakes verify the observable application states: `test_child_crash_and_load_failure_are_latched`, `test_unresponsive_child_is_terminated_reaped_and_fault_latched`, `test_cleanup_unconfirmed_is_bounded_and_blocks_replacement`, `test_unconfirmed_cleanup_keeps_admission_bytes_and_readiness_latched`, `test_shutdown_during_fault_is_repeatable_and_keeps_accounting_nonnegative`, `test_http_health_readiness_and_metrics_follow_lifecycle`, `test_health_and_readiness_are_distinct`, `test_shutdown_report_distinguishes_unconfirmed_and_failed_or_timed_out`, and launcher exact-container timeout tests. The review found one gap: an unconfirmed child exit during model-load timeout was surfaced as generic `not_ready`; startup now preserves `cleanup_unconfirmed`. Added a deterministic process-control regression test and HTTP readiness assertion for the exact code.
- No Docker, target host, CUDA, inference, process killing, or shared-service access occurred for this review.
- Focused command `.venv/bin/python -m unittest services.stt.tests.test_runtime services.stt.tests.test_http scripts.test_stt_cuda_http_smoke scripts.test_stt_cuda_launcher -v` — PASS; 73 tests passed, including the added startup-timeout cleanup-state and readiness-code regressions.
- `make verify PYTHON=.venv/bin/python` — PASS; included Go vet/race tests/build, Ruff/format checks, configuration and Compose checks, 105 repository script tests, 61 STT tests, governance validation and dependency-lock checks.
- `make governance-check PYTHON=.venv/bin/python` — PASS; structural validation and 2 tests passed. `git diff --check` — PASS.

INTERPRETATION: deterministic tests now cover the application’s fault latch, readiness, no-replacement and shutdown-report contracts, including the corrected startup cleanup state. Documentation requires exact identity and evidence before operator actions and defers actual persistent restart/rollback commands to C.6.

NOT ESTABLISHED: target-host recovery, Docker behavior for a persistent worker, real GPU process visibility/context release, real CUDA fault cleanup, GPU OOM recovery, or active Ollama/Dify workload coexistence. These are not required for C.5 closure; intentional OOM or shared GPU exhaustion is excluded. User accepted C.5A and C.5B as PASS on 2026-10-18 for the documented offline scope.

## M02-C.6A static deployment profile — verification

OBSERVED:

- `.venv/bin/python -m unittest scripts.test_stt_deployment_profile scripts.test_compose -v` — PASS; 19 tests passed, covering CUDA profile/artifact/config validation, parent traversal, rendered Compose security/GPU/network/health/restart policy, explicit rejection of broad `gpus` allocation, and invalid identities and limits.
- `make verify PYTHON=.venv/bin/python` — PASS. It included formatting/static checks, Go tests/build, config validation, Compose static rendering and topology checks, 115 repository script tests, 61 STT tests, governance and lock checks. No container was built or started; Compose was rendered only.
- `make governance-check PYTHON=.venv/bin/python` — PASS; governance structural validation and 2 tests passed.
- `git diff --check` — PASS.
- No target host, model artifact, Docker container, CUDA runtime, GPU, inference, or Ollama/Dify service was accessed. No deployment action occurred.

Initial static review findings (broad GPU selection, absent liveness wiring, mutable base image, and no persistent deployment identity) are historical pre-change observations; current changes address their static configuration portions. Final offline acceptance review found that the rendered-Compose validators did not explicitly reject an added `gpus: all` field. Both validation paths now reject any `gpus` allocation alongside explicit device reservation, with regression tests.

INTERPRETATION: offline profile and render tests establish fail-closed configuration consistency, not Compose runtime GPU selection, host ACLs, runtime image provenance or persistent service behavior. C.6B must separately validate target startup, artifact/device access, readiness and bounded shutdown. C.6C must separately validate a private-path request and exact project-scoped rollback.

NOT ESTABLISHED: GPU/runtime behavior, artifact access as the deployed user, health transitions under persistent service, limits enforcement, recovery, cleanup and rollback. No target, Docker container, GPU or inference work was performed during C.6A. The user accepted C.6A on 2026-10-18 for this static/offline scope only.

## M02-C.6B-R1 — production image specification and offline validation

Status: PASS for accepted production-image specification and offline verification scope. User acceptance is recorded in `user-validation.md`. No image build or target action was performed.

OBSERVED:

- Focused deployment profile tests: `.venv/bin/python -m unittest scripts.test_stt_deployment_profile -v` — 15 tests passed. Coverage includes production image role/entrypoint requirements, rejection of the known validation image ID and validation repository references, immutable base/source/lock evidence gates, Compose profile label consistency and the existing GPU/security/artifact constraints.
- CUDA lock SHA-256 remains `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`; package pins and hashes were not changed.
- The production Dockerfile statically specifies Python module execution, non-root UID/GID, hash-verified dependency installation and provenance labels. The profile and Compose validator continue to enforce immutable image references, explicit GPU allocation, CUDA-only configuration, `/healthz` liveness, a separate `/readyz` gate, no automatic restart, private networks and read-only artifact/config mounts.
- Final offline review confirmed the locked CUDA package versions, found that the production Dockerfile's loader path omitted the installed NVRTC library directory, and corrected it. Focused regression coverage now rejects removal of that path. Review also verified that `services.stt.main` delegates to the production worker server and corrected its stale M01-only docstring.
- The C.4 reports establish successful CUDA inference with the same package tuple but do not record its exact `LD_LIBRARY_PATH`; equivalence of the C.4 and proposed production loader environments is therefore NOT ESTABLISHED.

INTERPRETATION: These tests and source checks verify specification consistency only; they do not execute the Dockerfile or prove the resulting image's contents, library compatibility, entrypoint behavior or labels.

NOT ESTABLISHED: platform-specific base digest and source/build provenance; built image ID and repository digest; installed package inventory and actual shared-library resolution from the production image; target model accessibility as UID/GID 65532; host-to-container GPU UUID mapping; CUDA/model startup, readiness, enforced resource limits, shutdown and Ollama/Dify coexistence.

OBSERVED verification commands:

- `make verify PYTHON=.venv/bin/python` — PASS. This included Go vet/tests/build, Ruff checks, config validation, Compose rendering/static checks, all 121 repository script tests, all 61 STT tests, AST parsing and STT lock validation. Compose commands were configuration rendering only; no services or containers were started.
- `make governance-check PYTHON=.venv/bin/python` — PASS. Seven skill structures/frontmatter and local governance references validated; two governance tests passed.
- `git diff --check` — PASS.

User acceptance on 2026-10-18 applies to R1's bounded specification/offline scope only. The future build procedure requires a clean checkout at the expected commit, verifies no staged/unstaged/untracked files, and streams a Git archive of that exact commit as the build context; a SHA build argument alone is not treated as source provenance. Production image build remains NOT STARTED. C.6B-R2/R3, C.6C and overall M02 remain incomplete.

No Docker build/pull/run, host access, CUDA operation, inference, dependency change, model operation, or deployment occurred. M02-C.6B-R1 is accepted only for its offline specification scope; C.6B runtime work and overall M02 remain incomplete.

## M02-C.6B-R2 — model access policy and private configuration tooling

OBSERVED offline checks:

- `.venv/bin/python -m unittest scripts.test_stt_deployment_profile -v` — **34 tests passed** after final review corrections. Coverage includes group-reader ownership/modes and ACL rejection, release immutability/isolation and rollback selection, private config and output paths, deterministic content/path identity across all deployment inputs, and fail-closed resource/GPU/worker identity checks.
- Focused Ruff checks and formatting for the changed Python files — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS. This included Go vet/race tests/build, Ruff lint/format checks, application configuration checks, base and CPU/CUDA Compose rendering/static checks, 140 repository script tests, 61 STT tests, AST parsing, and CUDA dependency-lock validation. Compose commands rendered configuration only; no container was created or started.
- `make governance-check PYTHON=.venv/bin/python` — PASS. Seven skill structures/frontmatter/references validated and two governance tests passed.
- `git diff --check` — PASS.

INTERPRETATION: these tests establish static policy and configuration wiring only. They do not establish effective target DAC/ACL state or container access. The configuration-set digest detects changed input bytes but is not a signature or authenticity proof.

NOT ESTABLISHED: target UID/GID ownership, model-reader group availability, parent traversal, ACL state, Docker supplementary-group/user namespace behavior, read-only mount access, production image identity, host resource review, or runtime rollback. No target/Docker/GPU operation occurred. C.6B-R2 is accepted only for the static/offline scope; this evidence does not pass C.6B or M02.

## M02-C.6B Phase A — read-only target preflight; BLOCKED before runtime validation

OBSERVED: Read-only SSH inspection through the approved `wisper` alias resolved to host `llm`. Host inventory: Ubuntu 24.04.5, kernel 6.8.0-147-generic x86_64, 32 logical CPUs, 61 GiB RAM (57 GiB available), 95 GiB available on `/`, Docker Engine 29.1.3 and Compose v5.6.0. NVIDIA driver 580.178.04 and Container Toolkit 1.20.1 were present; Docker reports the NVIDIA runtime registered (default runtime remains `runc`).

OBSERVED: GPU 0 is a Quadro RTX 5000 at PCI bus `00000000:06:10.0`, UUID `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`; 15,360 MiB total, 14,909 MiB free, 1 MiB used and 0% utilization at sampling. No compute process was reported. Static host index and container CUDA index are both configured as 0 in examples, but no private profile supplies the expected UUID, and host-to-container mapping remains NOT ESTABLISHED.

OBSERVED: Ollama container `72d0ee33e0e6` was running and its version endpoint returned HTTP 200. Dify project `docker` had 12 running components and one exited one-shot permission-init container (exit 0); API, PostgreSQL, Redis and sandbox health checks reported healthy, and the Dify system-features endpoint returned HTTP 200. Other Dify components were running without Docker health checks. No Speech Platform project/container/network/volume collision was found. No services or Docker resources were modified.

OBSERVED: The exact approved image ID exists and reports linux/amd64 and user `65532:65532`. Docker reports tag `speech-platform-cuda-validation:m02-c2a-20261017`, repository digest `speech-platform-cuda-validation@sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540`, no labels, and entrypoint `python /opt/validation/probe.py`. Preserved successful C.2b evidence records 35 installed package versions; all 35 match the staged CUDA lock and lock digest `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`. The image entrypoint is a validation probe, not the production STT worker. Base-image digest/build provenance is unavailable; the image cannot satisfy the production worker contract as-is. Image ID and repository digest are distinct identity types even though Docker reports the same digest string here.

OBSERVED: The production artifact verifier passed for `dropbox-dash/faster-whisper-large-v3-turbo`, revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, canonical manifest digest `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`, five files and total size 1,621,665,983 bytes. `model.bin` matched SHA-256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`. However, parent/release/artifact directories are mode 2700, manifest mode 0600, and artifact files mode 0644; no POSIX access ACL was present on inspected path components. The non-root worker cannot traverse the owner-only release directories or read the manifest. Permissions were not changed.

OBSERVED: The target checkout remained clean at `e8027a7`; no target C.6A private deployment profile, app/deployment/worker configs or generated Compose environment file exists. The local static sentinel Compose render/check passed as part of `make verify`, but target-specific rendering could not run without those inputs. The proposed C.4 reference limits (4 CPUs/12 GiB/128 PIDs) are below observed host totals but are not reviewed production capacity. The observed 14,909 MiB free VRAM is not reserved capacity.

INTERPRETATION: C.6B Phase A is complete as a read-only preflight, but Phase B must not proceed. Blockers are the validation-only image entrypoint and missing production image/base provenance; missing private deployment identity/configuration and resource review; and model directory/manifest permissions incompatible with the non-root worker. The Dify Compose summary's `exited(1)` denotes one exited component; inspection confirmed the one-shot init container exited 0, while all 12 long-running components were running.

NOT ESTABLISHED: a production worker image tied to an immutable linux/amd64 base digest; deployment image provenance; expected GPU UUID match and container device mapping; effective worker artifact access; target-rendered Compose policy; runtime device visibility/readiness/limits/shutdown; deployment rollback; or coexistence under active GPU load.

Sanitized evidence is preserved on the target at `/home/master/speech-platform-staging/M02/M02-C/M02-C.6/attempts/c6b-phase-a-20261018-01/preflight-report.json` (mode 0600). No inference, model load, CUDA operation, container lifecycle action, permission change, image operation or service modification occurred.

## M02-C.5 closeout verification — OBSERVED

- User acceptance on 2026-10-18 closed C.5A and C.5B as PASS for their deterministic offline scope.
- `make governance-check PYTHON=.venv/bin/python` — PASS; seven skill structures/references validated and 2 governance tests passed.
- `make verify PYTHON=.venv/bin/python` — PASS; Go vet, race tests and build; Ruff checks and formatting; configuration checks; rendered Compose/static checks; 105 repository script tests; 61 STT tests; governance and lock checks passed. Compose was rendered only; no containers were started.
- `git diff --check` — PASS.
- C.6 was a static configuration/documentation review only; no Docker, target host, GPU, inference or service was accessed.

INTERPRETATION: C.5 is closed only for accepted offline fault handling and operator-procedure scope. C.6A evidence is static/offline only, not deployment validation.

NOT ESTABLISHED: real CUDA fault cleanup, GPU OOM recovery, active GPU workload coexistence, persistent deployment, production resource envelope, rollback, or deployed GPU selection/readiness.
