# M07A user validation

## Status

**Accepted; M07A complete.** On 2026-10-25, the operator explicitly accepted M07A following successful offline verification and controlled live Gateway qualification, including the limitations recorded below and in the [result](result.md).

## Observed technical results

- Local STT: PASS; HTTP 200; provider `local`; nonempty transcript and language metadata recorded.
- Written and Diplomatic local text transformation: PASS technically; both HTTP 200 through `host-ollama` / `local-qwen`, generated with no fallback.
- Swedish text translation: PASS technically through the same local provider and configured model.
- Local TTS: PASS; HTTP 200; valid mono PCM16 48 kHz WAV, 3.2 seconds, mode `0600`.
- Negative checks: invalid transformation options rejected locally with exit 2; controlled invalid bearer token received HTTP 401 with exit 1; existing output collision rejected locally with exit 2. No request was made for the two local validation failures.
- Gateway, STT and TTS remained healthy with unchanged image IDs/source revision. GPU/model residency returned naturally to baseline between operations; no concurrent inference, cloud call, deployment, or restart occurred.

These outcomes establish technical operation only. Semantic equivalence, translation quality, style and TTS audio quality were not independently established by the checks. The operator accepted M07A with these limitations; generated content should receive appropriate human review before consequential use.

## Private evidence

Evidence directory: `private/m07a/validation-20261025T135107Z/`. It contains per-operation content-free JSON reports, private request/output evidence, the supplied synthetic text inputs, and `speech.wav`. Generated text and transcript are intentionally not copied into this document. Evidence files were created with mode `0600`; no token is included.

## Operator acceptance

- **Decision:** M07A accepted and closed on 2026-10-25.
- **Accepted scope:** offline implementation verification and the bounded live technical results recorded above.
- **Accepted limitations:** semantic preservation, translation correctness, stylistic quality and subjective TTS quality are not established as PASS by technical testing. This acceptance does not authorize M07B.
- **Implementation commit:** `0b213aa` — `feat(cli): add public API qualification toolkit foundation`.
