# M07A user validation

## Status

**Live validation executed; operator review and acceptance pending.** The 2026-10-25 run was authorized by the user. Execution does not itself accept or close M07A.

## Observed technical results

- Local STT: PASS; HTTP 200; provider `local`; nonempty transcript and language metadata recorded.
- Written and Diplomatic local text transformation: PASS technically; both HTTP 200 through `host-ollama` / `local-qwen`, generated with no fallback.
- Swedish text translation: PASS technically through the same local provider and configured model.
- Local TTS: PASS; HTTP 200; valid mono PCM16 48 kHz WAV, 3.2 seconds, mode `0600`.
- Negative checks: invalid transformation options rejected locally with exit 2; controlled invalid bearer token received HTTP 401 with exit 1; existing output collision rejected locally with exit 2. No request was made for the two local validation failures.
- Gateway, STT and TTS remained healthy with unchanged image IDs/source revision. GPU/model residency returned naturally to baseline between operations; no concurrent inference, cloud call, deployment, or restart occurred.

These outcomes establish technical operation only. Semantic equivalence, translation quality, style and TTS audio quality have not been assessed. Review the private generated text/audio before accepting M07A.

## Private evidence

Evidence directory: `private/m07a/validation-20261025T135107Z/`. It contains per-operation content-free JSON reports, private request/output evidence, the supplied synthetic text inputs, and `speech.wav`. Generated text and transcript are intentionally not copied into this document. Evidence files were created with mode `0600`; no token is included.

## Pending operator review

- [ ] Review the Written and Diplomatic output and decide whether they meet the intended technical/semantic use.
- [ ] Review the Swedish translation for linguistic correctness.
- [ ] Listen to the private TTS WAV and assess quality.
- [ ] Confirm whether these bounded results satisfy M07A acceptance criteria.

No completion, acceptance, commit, or M07B authorization is recorded.
