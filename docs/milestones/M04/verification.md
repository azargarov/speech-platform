# M04 verification record

Status: **Local and bounded live technical verification PASS; operator listening acceptance recorded PASS (2026-10-22).**

## Planned risk-to-check mapping

| Risk / criterion | Check |
|---|---|
| Plain-text compatibility and Gateway forwarding | Existing TTS worker/Gateway regression tests plus explicit `input_format=text` case |
| XML safety and strict subset | Parser unit tests for malformed XML, DTD/entity declarations, namespaces, version, allowlists and attributes |
| Segment order, nested language and pauses | Pure parser tests for order/inheritance and PCM composition tests for exact frames |
| Resource exhaustion / oversized response | Boundary tests for every configured limit and actual output cap |
| WAV format and all-or-nothing output | WAV metadata tests and injected segment failure test |
| Contract/config drift | OpenAPI, worker-config and Compose checks in `make verify PYTHON=.venv/bin/python` |
| Live service isolation | Pre/post target identity, health, restart and rollback evidence; single bounded loopback Gateway request |

## Local implementation verification — 2026-10-22

- **OBSERVED:** `make verify PYTHON=.venv/bin/python` exited 0. It included
  Go vet/race tests, Ruff lint/format, Gateway/STT/TTS configuration checks,
  rendered Compose checks, release checks, all scripts and STT unit tests,
  OpenAPI validation, Go build, Python syntax and governance/lock checks.
- **OBSERVED:**
  `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest
  services.tts.tests.test_tts -v` exited 0 with 22 tests passing. Coverage
  includes plain text, explicit input format, malformed/unsafe/unsupported
  XML, namespace/version/language rules, nested context, all three language
  mappings, breaks including consecutive breaks, exact silence frames, WAV
  format/composition, limits, segment failure and disconnect draining.
- **OBSERVED:** `go test ./internal/gateway` exited 0; the full verification
  also ran `go test -race ./...` successfully. `git diff --check` exited 0.
- **OBSERVED:** Final rerun after updating the M04 result and validation
  records: `make verify PYTHON=.venv/bin/python` exited 0; its script suite
  passed 438 tests, and its STT suite passed 64 tests. Earlier focused M04
  verification passed 22 TTS tests and `go test ./internal/gateway`.
- **OBSERVED (check refinement):** The repository's source policy rejected
  the fixed W3C SSML/XML namespace URI as if it were a deployment address.
  The policy test now allows only those two protocol namespace identifiers;
  its checks for other hardcoded endpoints and worker coupling remain active.
  The focused test and full verification then passed.
- **OBSERVED:** Built M04 Gateway and TTS images locally and deployed only those
  two services using `--no-deps --no-build`. One bounded loopback request to
  `/v1/tts/speech` with `input_format=ssml`, `mode=fast`, and an English–Swedish
  request returned HTTP 200 `audio/wav`; readiness returned 200 before and
  after. The private sample is
  `private/m04/live-20261022/english-swedish-fast.wav` (247,724 bytes;
  mono PCM16, 48 kHz, 123,840 frames, 2.58 seconds; SHA-256
  `493ca62e405120b6ad39158aa3eeeb74edf5c6db4515ed9e4c6b89e43e00f9e8`). The
  request and measured metadata are in ignored
  `private/m04/live-20261022/request-metadata.json`.
- **OBSERVED commands:** Gateway build used
  `SOURCE_REVISION=m04-ssml-20261022 docker compose --env-file .env -f compose.yaml build gateway`.
  TTS source overlay used
  `docker build --pull=false -f private/m04/live-20261022/tts.Dockerfile -t speech-platform-tts:m04-ssml-20261022 .`.
  Deployment used the canonical Compose file plus the M03B and private M04
  overlays, selecting only `gateway tts` with `--no-build --no-deps --wait`.
  The loopback runner is private at
  `private/m04/live-20261022/request.py`; it did not print or persist the
  optional bearer token.
- **OBSERVED:** Restored Gateway and TTS to their pre-test M03B images. Final
  inspected image IDs match the pre-test IDs; both are running, healthy,
  with zero restarts and `OOMKilled=false`. STT remained on its original image
  and container throughout (same ID and start time, zero restarts,
  `OOMKilled=false`). `docker compose ls --all` showed Ollama, Dify, M01E
  fresh/experiment and the existing STT smoke project still present.
- **OBSERVED (rollback correction):** The first TTS rollback start could not
  read the private bind-mounted config because its file mode was 0600 for the
  container's non-root UID. Changed only the private rollback copy to mode
  0644 (parent directory remains private, mode 0700), restarted TTS, then
  confirmed Gateway/TTS healthy on the original M03B image IDs. No repository
  file or unrelated service was involved in this correction.
- **INTERPRETATION:** The bounded target request establishes that the deployed
  path generated and returned a composed WAV for the supported English–Swedish
  example. One request does not establish production licensing, cold-start
  latency, sustained-load behavior, accent selection or native language
  detection.
- **NOT ESTABLISHED:** Operator listening acceptance remains pending. The
  technical evidence does not substitute for listening review.

The M03B baseline is restored. No M00, Ollama, Dify, M01E or STT smoke
service was targeted. Operator review and closeout are recorded in
[user-validation.md](user-validation.md) and [result.md](result.md).

- **OBSERVED (closeout rerun, 2026-10-22):** `make verify PYTHON=.venv/bin/python` exited 0, including Go vet/race tests, Ruff checks, configuration and Compose validation, release checks, repository script tests, STT unit tests (64 passed), Go build, Python syntax, governance checks and dependency-lock validation. `git diff --check` exited 0.
