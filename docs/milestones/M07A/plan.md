# M07A — CLI Qualification Foundation

## Scope and design

Provide a standard-library CLI that exercises only the public Gateway routes for STT, text transformation (including translation), and TTS. Keep request construction and execution in one small module; preserve `scripts.api_smoke` and its Make targets unchanged. The CLI uses the existing `.env` loader and Gateway token, pins STT to local unless Groq and explicit audio consent are both selected, and defaults text transformation to `local_only=true`.

Reports contain request options and sizes, HTTP/error status, client elapsed time, returned provenance/metadata, deterministic technical checks and optional artifact metadata. Request text, transcript and audio are omitted by default. Explicit evidence and WAV outputs are exclusive-create files under `private/` with mode 0600. No semantic quality score is claimed.

## Included

- `python -m scripts.qualify {stt,transform,tts}`; `transform --target-language` covers translation.
- Optional JSON report and private evidence file; WAV inspection using `wave`.
- Offline mocked request, validation, privacy, error and CLI tests.
- Proportional usage and milestone records.

## Excluded

No Gateway/worker changes, API contract changes, live inference, cloud calls, deployment, commit, M07B/M07C implementation, semantic scoring or report framework.

## Acceptance and verification

- Public request schemas and auth match `api/openapi/public-v1.yaml`.
- No cloud selection without explicit authorization; default transformation is local-only.
- Sensitive content is absent from default report and console output.
- Existing smoke command tests continue to pass.
- Run focused tests, Ruff, module help/argument checks, `make verify PYTHON=.venv/bin/python`, governance/docs checks and `git diff --check`.

Status: implementation authorized; user validation and closeout pending.
