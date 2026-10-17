# M02-A user validation — PASS

User validation and explicit M02-A closeout approval received 2026-10-17. M02-A is PASS. Overall M02 remains incomplete. M02-B has not started and requires separate approval.

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

M02-A validation does not authorize deployment or M02-B. M02-B requires separate explicit approval.
