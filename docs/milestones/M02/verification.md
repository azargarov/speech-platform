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
