# M02 user validation — M02-A/B/C.2b bounded smoke PASS

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
