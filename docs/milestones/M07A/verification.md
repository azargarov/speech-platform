# M07A verification

## Offline verification — OBSERVED

Correction-pass evidence recorded on 2026-10-25 in the repository checkout `/home/master/speech-platform`, using `.venv/bin/python`:

- `.venv/bin/python -m unittest scripts.test_qualify scripts.test_api_smoke -v` — PASS, 24 tests.
- Ruff check and format check for `scripts/qualify.py` and `scripts/test_qualify.py` — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS, exit 0: 293 script tests, 92 STT tests, 63 TTS tests, and 2 governance tests; all passed.
- M07A local-link checks and `git diff --check` — PASS.

Mocked tests are offline evidence only and are not counted as live qualification.

## Live Gateway qualification — OBSERVED

Executed on 2026-10-25 against the local deployed Gateway. No production configuration or service was changed.

### Preflight and configuration

- `make status PYTHON=.venv/bin/python` before and after requests: Gateway, STT and TTS all running and healthy. Source revision `9ef27aed39056c6c5eab693801a30c2aee1c6d78`; Gateway image `sha256:4dfae8feff1af02c91ba59f064952d8486f66643cfdaa44abcbe9f105905ee2f`, STT `sha256:90c2db7a74dc3d4dc8801ef6137a6162b586602fa663a074280cf431ae90c1ca`, TTS `sha256:51416bc0b656e855c64c058a5cdd1afa035141bc52cd3cf123b556b0920895fa`.
- Gateway `/healthz` and `/readyz`: HTTP 200 before and after testing.
- `.env` contained a token; its value was never displayed. `SPEECH_API_URL` was unset, so the CLI used its configured loopback default `http://127.0.0.1:8080`. The Gateway config was `private/m05b/stage2c/gateway.yaml`; internal STT/TTS URLs were `http://stt:8081` and `http://tts:8082`.
- Effective text transformation configuration had `enabled=true`, `selection.allow_cloud=false`, and enabled local alias `local-qwen` using provider `host-ollama`. Optional cloud model entries were present but globally prohibited. `groq_stt.enabled=false`. No cloud inference was attempted.
- Plain `make preflight PYTHON=.venv/bin/python` reported 31 PASS, 2 WARN, 2 FAIL and 2 SKIP because this shell did not have its supplementary `stt-model-reader` GID active. `getent` confirmed the operator’s group membership. Read-only `sg stt-model-reader -c 'make preflight PYTHON=.venv/bin/python'` then reported 33 PASS, 2 WARN, 0 FAIL and 2 SKIP. WARNs concerned fresh internal networking and uncommitted source; both are expected for this non-deployment validation. No model integrity check was bypassed.
- Initial GPU reading: 174 MiB used / 14,736 MiB free; utilization 0%. No other inference was active.

### Live requests

Requests were sequential. Every text-transform request explicitly selected `local-qwen` and used `local_only=true`. The three synthetic text outputs and the STT transcript are retained only under the private evidence directory listed below.

| Operation | Command (token omitted; CLI loaded private `.env`) | Observed |
| --- | --- | --- |
| STT | `.venv/bin/python -m scripts.qualify stt --audio private/m03a/M03A-20261021-03/performance/audio/baseline_optimize_false/en-rep1.wav --provider local --source-language en --output-language auto --timeout 195 --report private/m07a/validation-20261025T135107Z/stt-report.json --evidence private/m07a/validation-20261025T135107Z/stt-evidence.json` | PASS, exit 0, HTTP 200, 5.197 s; provider `local`; detected/output language `en`, `translated=false`; transcript nonempty and provider check passed. Fixture was existing synthetic VoxCPM2 speech from the M03A performance set. |
| Written transformation | `.venv/bin/python -m scripts.qualify transform --text-file private/m07a/validation-20261025T135107Z/transformation-input.txt --mode written --format normal --target-language none --model local-qwen --report private/m07a/validation-20261025T135107Z/transform-written-report.json --evidence private/m07a/validation-20261025T135107Z/transform-written-evidence.json --timeout 240` | PASS, exit 0, HTTP 200, 10.510 s; `host-ollama` / `local-qwen`, `generated=true`, `fallback_occurred=false`; output nonempty and provenance checks passed. |
| Translation | `.venv/bin/python -m scripts.qualify transform --text-file private/m07a/validation-20261025T135107Z/transformation-input.txt --mode written --format normal --target-language sv --model local-qwen --report private/m07a/validation-20261025T135107Z/translation-report.json --evidence private/m07a/validation-20261025T135107Z/translation-evidence.json --timeout 240` | PASS, exit 0, HTTP 200, 9.466 s; `host-ollama` / `local-qwen`, `generated=true`, `fallback_occurred=false`; output nonempty and provenance checks passed. |
| TTS | `.venv/bin/python -m scripts.qualify tts --text-file private/m07a/validation-20261025T135107Z/tts-input.txt --output private/m07a/validation-20261025T135107Z/speech.wav --report private/m07a/validation-20261025T135107Z/tts-report.json --evidence private/m07a/validation-20261025T135107Z/tts-evidence.json --timeout 600` | PASS, exit 0, HTTP 200, 68.710 s. Valid PCM16 WAV, mono 48 kHz, 3.200 s, 307,244 bytes; file mode `0600`; WAV technical check passed. Default `quality` mode and `none` audio processing were used. |
| Diplomatic transformation | `.venv/bin/python -m scripts.qualify transform --text-file private/m07a/validation-20261025T135107Z/transformation-input.txt --mode diplomatic --format normal --target-language none --model local-qwen --report private/m07a/validation-20261025T135107Z/transform-diplomatic-report.json --evidence private/m07a/validation-20261025T135107Z/transform-diplomatic-evidence.json --timeout 240` | PASS, exit 0, HTTP 200, 9.456 s; `host-ollama` / `local-qwen`, `generated=true`, `fallback_occurred=false`; output nonempty and provenance checks passed. |

No semantic or linguistic judgment is asserted from these technical results. Human review of the private text evidence remains pending.

### Negative behavior and resource recovery

- Invalid `raw` + `concise` transformation: CLI exit 2, `local_validation`, no HTTP status; the report confirms local rejection before a request.
- Controlled invalid bearer token using an in-memory dummy value: HTTP 401, `authentication`, CLI exit 1. The token value was neither printed nor persisted; the Gateway rejected the request before provider inference.
- Existing output path collision: CLI exit 2, `local_validation`, no HTTP status; rejected before an API request.
- Sampled GPU use rose to 8,808 MiB after the Written transform (6,102 MiB free). No other inference was started. Ollama later listed no resident model and GPU returned to 174 MiB used / 14,736 MiB free before translation/TTS progression. After translation, Ollama showed the model with about one second remaining; after five seconds it was absent and GPU was back at baseline. No forced unload was used.
- After TTS, worker state was `loaded` with `inference_active=false`; GPU was 5,646 MiB used / 9,264 MiB free. The worker later reported `unloaded` naturally and GPU returned to 174 MiB used / 14,736 MiB free before the Diplomatic request. Final Ollama listing was empty and final GPU reading was at baseline.
- Final `make status`: all three services remained healthy with the same image IDs and source revision. Gateway health/readiness remained HTTP 200. No cloud request, retry, concurrent inference, restart, deployment, or Ollama lifecycle command occurred.

### Private evidence

Reports, transcript/text evidence, synthetic input files, and the TTS WAV are in `private/m07a/validation-20261025T135107Z/`. Created files were mode `0600`; the directory was private. Generated text and transcript contents are intentionally not reproduced here. The synthetic text source files may be removed after operator review; the report/evidence files and WAV are retained for review.

The execution order differed slightly from the proposed numbered order for GPU safety: after Written mode, observed free memory was below the 8,000 MiB TTS preflight headroom. Translation was run only after the local model naturally expired and VRAM returned to baseline. TTS was run after translation and was followed by natural TTS unload before the final Diplomatic request. All requests remained sequential.

## NOT ESTABLISHED

- Semantic preservation, translation correctness, stylistic quality, and TTS listening quality remain for human review.
- Cloud-provider behavior, sustained load, concurrent inference, and other input samples were not tested.
