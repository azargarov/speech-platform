# M02 user validation — M02-A/B/C.2b/C.3/C.4 PASS for accepted scopes

User validation and explicit closeout approvals for M02-A and M02-B were received 2026-10-17. The user formally accepted M02-C.2b as PASS for the bounded CUDA smoke-test scope on 2026-10-17. Overall M02 remains incomplete.

## Validation evidence

OBSERVED: The user reported completing local validation and read-only host inspection. The reported host observations were existing Ollama and Dify containers; published ports 80, 443, 5003 and 11434; no listener observed on 8080; NVIDIA Quadro RTX 5000 visible with driver 580.178.04; NVIDIA Docker runtime registered; approximately 58 GiB RAM available and 105 GB root filesystem space available. The user reported no containers or services were modified.

OBSERVED: The user reported local verification passed, including governance, Go/Python tests, OpenAPI validation, Compose checks and configurable Gateway port tests. The user then approved M02-A validation and closeout following the final audit recommendation ACCEPT.

INTERPRETATION: These user-reported results support acceptance of M02-A's application foundation and static deployment configuration under the approved scope.

NOT ESTABLISHED: This M02-A implementation was not deployed to the inspected host. The host observations do not establish Speech Platform runtime behavior, GPU passthrough, actual CUDA memory availability for an inference model, GPU cleanup, model loading or transcription. No remote access or deployment occurred during this closeout.

## Review procedure

From the repository root:

1. Review `services/stt/domain.py`, `config.py`, `artifacts.py`, `devices.py`, `admission.py`, `lifecycle.py`, `supervisor.py`, `application.py`, `services/worker/server.py`, and the M02-A tests. Confirm the boundaries and fail-closed behavior match the accepted design.
2. Review the diff and confirm no public Gateway inference route, real inference backend, model download, TTS behavior change, or deployment was introduced.
3. Re-run the local checks:

   ```sh
   make governance-check PYTHON=.venv/bin/python
   make verify PYTHON=.venv/bin/python
   git diff --check
   ```

4. Confirm tests use fakes and review the audit corrections: failure messages are fixed by typed code; malformed/oversized/read-failed IPC faults are boundedly terminated; `cleanup_unconfirmed` blocks readiness and retains the active job's audio budget until exit confirmation; repeated cleanup cannot start a replacement; a declared CUDA memory estimate rejects unknown and insufficient free memory. Confirm these tests do not claim actual GPU-memory release or kernel behavior after SIGKILL.
5. Confirm limits are understood: there is no production inference adapter or internal HTTP transcription route in this phase; real engine loading, audio decoding, CUDA/GPU behavior, artifact immutability under concurrent mutation, and deployment remain unverified.
6. User validation and explicit M02-A acceptance were recorded 2026-10-17; no further validation is pending for phase A.

M02-A validation did not itself authorize deployment or M02-B; separate M02-B implementation authorization was later provided. M02-B does not authorize M02-C or deployment.

## M02-B CPU user-validation — PASS

The user authorized retrieval of the pinned public model and use of `private/audio/russian.m4a`, a recording created for STT testing, and accepted the CPU validation on 2026-10-17. This approval marks M02-B PASS; it does not authorize M02-C.

OBSERVED: the pinned Systran/faster-whisper-tiny revision, MIT model-card license, artifact hashes, dependency versions, CPU options, private HTTP result, language detection, timestamps, health/readiness, unknown-alias error, subprocess cleanup, timings and memory observation are recorded in [verification](verification.md). The CPU integration passed twice with Hugging Face/Transformers offline flags. Audio SHA-256 was identical before and after. Model files, configs, benchmark output and audio remain under ignored `private/`; no audio or transcript was uploaded, printed, or added to repository files.

Two blocking validation defects were found and corrected before successful inference: the adapter required a file absent from this upstream model, and the deployment example placed the manifest inside the artifact root. The CPU Make target also lacked a project-root import path; it now sets `PYTHONPATH=.`. A regression test covers the manifest placement and the adapter fixture matches the actual upstream file set.

At M02-B closeout, NOT ESTABLISHED: cold-cache startup, representative throughput/capacity, worker-isolated memory, real disconnect cancellation during inference, CUDA/GPU behavior, deployment and target-host coexistence. Later C.2b testing established only the bounded CUDA smoke result recorded below; broader M02-C work still requires its approval gates.

## M02-C.2b bounded CUDA smoke — PASS for approved scope

The user authorized one CUDA diagnostic attempt on 2026-10-17. OBSERVED: the approved tiny model completed one transcription with explicit CUDA device 0 and float16. Five segments passed structural timestamp checks; language detection returned `ru`. The production bounded audio decoder was used. The attempt container exited successfully and was removed, and Ollama/Dify health checks were healthy before and after. Full provenance, stage timings and limitations are recorded in [verification](verification.md).

The acceptance applies only to the bounded smoke test. NOT ESTABLISHED: peak VRAM, concurrency, sustained performance, CUDA HTTP worker integration, large-v3-turbo inference, persistent deployment, or shared-service coexistence under active load. No transcript text or private diagnostic reports are stored in Git. Overall M02 remains incomplete.

## M02-C.3 CUDA HTTP integration — PASS for accepted scope

The user accepted M02-C.3 on 2026-10-17 after the third controlled target attempt succeeded. The two prior attempts and their harness defects remain documented above and in [implementation](implementation.md); they were not retried during the successful run.

OBSERVED from the accepted target evidence:

- One production HTTP multipart request succeeded (HTTP 200) using explicit CUDA device 0 and float16 with no CPU fallback.
- The response detected `ru` and contained five nonempty segments with valid timestamp bounds.
- Model load took 2.549 s, transcription 0.959 s, and HTTP integration 3.828 s.
- Shutdown was independently recorded as `completed_and_confirmed`; supervisor child exit and worker-not-ready state were confirmed. Container exit was 0 and the container was removed.
- Ollama and Dify health remained satisfactory according to the available checks. GPU free memory was sampled at 14,909 MiB before and after; no instrumented peak was captured.
- Reports are preserved outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.3/attempts/cuda-http-20261017-03/`. No private audio, model artifacts, or transcript content were copied into the repository.

OBSERVED: Attempt `cuda-http-20261017-01` failed in the HTTP integration stage but did not persist status/code. Attempt `cuda-http-20261017-02` recorded HTTP 415 / `unsupported_media_type`; the extensionless mounted path resulted in an `application/octet-stream` part, which the production handler rejected before inference. Neither attempt established CUDA inference through HTTP. Evidence remains in operator-private staging outside Git.

LIMITATIONS / NOT ESTABLISHED: no instrumented peak VRAM, concurrency or sustained-load validation, production latency/throughput claim, persistent deployment, or Ollama/Dify coexistence under active inference load. The acceptance is limited to the approved one-request C.3 scope. No shared service was modified. Overall M02 remains incomplete.

## M02-C.4 target-model experiment acceptance — PASS for bounded scope

The user accepted Phase B as PASS for one bounded `large-v3-turbo` CUDA HTTP request and authorized Phase C for exactly three sequential requests through one production worker. The user then authorized C.4 closeout and C.5 readiness planning on 2026-10-18. C.4 is recorded PASS only for artifact integrity, the bounded Phase B/C HTTP executions, sampled observations, and confirmed cleanup.

OBSERVED in the retained target evidence:

- Approved model `dropbox-dash/faster-whisper-large-v3-turbo`, immutable revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`; canonical manifest `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
- Approved image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540`, CUDA dependency lock SHA-256 `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`, explicit CUDA device 0 / float16, no CPU fallback.
- Three sequential requests each returned HTTP 200, language `ru`, six segments and valid timestamp bounds. Readiness was 8.664 s; full HTTP request durations were 1.180 s, 0.702 s and 0.784 s for 21.205333 s audio, with RTF 0.055663, 0.033087 and 0.036972.
- Twelve one-second resource samples reported a device-wide sampled maximum of 2,795,962,368 bytes used GPU memory. cgroup memory high-water was 1,775,648,768 bytes. Child NVML memory was not visible and descendant RSS aggregated to zero, so child-specific memory attribution is not established.
- Shutdown and child exit/reaping were confirmed; sampler stopped; container exited 0 and exact inspection confirmed it was removed. Original model directory modes `2700`/`2700` were restored after temporary `2710`/`2750`. Ollama and Dify checks were satisfactory before and after.
- Sanitized evidence is preserved outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.4/attempts/large-v3-turbo-http-phase-c-20261018-01/`. Phase B evidence is preserved under the same C.4 staging root at `attempts/large-v3-turbo-http-20261018-03/`; the first artifact-permission failure and separate permission diagnostic remain under `attempts/large-v3-turbo-http-20261018-01/` and `attempts/c4-artifact-permission-20261018-01/`.

Historical failure records remain preserved. Phase B's first attempt failed before model loading because the non-root container could not enumerate the artifact directory with its original permissions; the separate non-GPU diagnostic confirmed that cause, and the successful run used a bounded temporary permission change with exact restoration. Phase C had two host-wrapper preflight failures before container launch (staged import path ordering, then omitted environment in dry-run subprocess); neither changed model permissions or started a container. The corrected wrapper performed one successful Phase C attempt.

NOT ESTABLISHED: concurrency capacity, sustained-load performance, exact peak VRAM, child-specific GPU/RSS, active Ollama/Dify GPU workload coexistence, forced CUDA-child cleanup under real GPU failure, and persistent deployment. Shared-service pre/post health does not prove behavior under simultaneous active GPU load. Overall M02 remains INCOMPLETE.

## M02-C.5A offline fault-injection validation — PASS

The user accepted C.5A as PASS for deterministic offline fault-injection coverage. The accepted evidence includes 40 focused tests, 105 repository script tests, 60 STT tests, passing governance checks, the decoded-buffer `MemoryError` mapping correction, and proof that CUDA construction failure does not fall back to CPU. This acceptance does not establish real CUDA fault cleanup or GPU OOM recovery. Overall M02 remains INCOMPLETE; overall C.5 became PASS after C.5B acceptance below.

## M02-C.5B recovery/operator procedure — PASS for accepted offline scope

The user accepted C.5B on 2026-10-18 as PASS for the documented deterministic offline recovery-procedure scope. Evidence is recorded in [implementation](implementation.md) and [verification](verification.md). This does not establish target-host recovery, real CUDA fault cleanup, GPU OOM recovery, active workload coexistence or deployment. C.5 and overall M02 remain bounded/incomplete respectively.

## M02-C.6A static deployment profile — PASS for accepted scope

The user accepted C.6A on 2026-10-18 as PASS for static deployment-profile implementation and offline verification. Acceptance includes the regression correction that rendered-Compose validators reject `gpus: all`. The accepted scope excluded target access, Docker container execution/build/pull, CUDA, inference, deployment, and changes to Ollama/Dify.

Unresolved inputs remain fail-closed: immutable image/base provenance, host GPU UUID, target artifact access and operator resource review. C.6B Phase A read-only target preflight has since completed with blockers; C.6B runtime validation and C.6C are not accepted or started.

## M02-C.6B-R1 production image specification — PASS for accepted offline scope

The user accepted C.6B-R1 on 2026-10-18 for the production image specification and offline verification only. Acceptance includes the production-entrypoint and CUDA library-path corrections, the lock-consistent runtime specification, immutable identity requirements, and clean-commit/source-context safeguards. No image was built, pulled, run or inspected; no target host was accessed. C.6B Phase A remains complete with blockers. Production image build is NOT STARTED; C.6B-R2/R3 and C.6C are NOT STARTED. Overall M02 remains INCOMPLETE. Runtime library loading, CUDA execution, target artifact access, readiness, resource enforcement, shutdown and coexistence remain NOT ESTABLISHED.

## M02-C.6B-R2 model access and private configuration — PASS for accepted offline scope

The user accepted R2 on 2026-10-18 for static model-permission policy and private-configuration tooling only. Acceptance includes complete configuration-set digest coverage, restricted private environment-file placement, fail-closed POSIX permission checks, and explicit separation of operator attestations from independently verified evidence. Worker identity remains UID/GID 65532 with one configured supplementary numeric reader GID. No target host was accessed and no permissions, private deployment files, or services were changed. Production image build/provenance remains a distinct blocker; C.6B-R3 and C.6C are NOT STARTED, and overall M02 remains INCOMPLETE.
