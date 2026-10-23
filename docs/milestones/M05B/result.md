# M05B result

Status: **CLOSED with accepted limitations, operator-approved 2026-10-23.**

## Accepted outcome

- **M05B implementation and integration: PASS.** Stage 1 implementation and Stage 2B Gateway/provider integration qualification were accepted.
- **Production Gateway deployment: PASS.** The approved Gateway image was deployed and remained healthy.
- **Production local-Qwen transformation: technically PASS.** Exactly one authorized local-only request returned HTTP 200 with the expected public model/provider metadata, generated output and no fallback or reasoning leakage.
- **Semantic preservation: PARTIAL, accepted with limitations.** The date, budget and uncertainty were retained, but delivery timing may have been stated more definitively than the input. Generated transformations require user review. The generated text and detailed evidence remain private.
- **Cloud provider integration: qualified in isolation.** Cloud inference in production remains disabled.
- **Simultaneous local LLM inference and TTS cold-loading: NOT QUALIFIED.** No coexistence claim is made.

## Preserved qualification failures and limitations

Stage 2A completed nine synthetic cases at both 4K and 8K. Seven outputs at each context failed lexical quality invariants. The short Swedish output was in English and included an erroneous term; the short Russian output had awkward ordering and omitted required details. Other flags included exact date-format differences. These failures remain failures and were not converted to passes by operator acceptance. Local Qwen is retained only for user-reviewed transformations; no broad quality, multilingual or meaning-preservation guarantee is made.

The production smoke recorded a sampled GPU peak of 8,638 MiB used, natural model expiry about 5.84 seconds after the response, and return to the 2,216 MiB baseline. Passive samples do not establish an instantaneous peak. Broader transformation quality, simultaneous local inference/TTS cold-loading, and long-duration behavior remain NOT ESTABLISHED.

## Next milestone

M06 is the next planned milestone. Its planning documents and proposed ADR-0022 are preserved without substance changes. M06 is not activated or implemented by this closeout.

Detailed stage evidence is in [verification.md](verification.md), [Stage 2A qualification](stage-2a-qualification.md), [Stage 2B qualification](stage-2b-qualification.md), and [Stage 2C deployment readiness](stage-2c-deployment-readiness.md). Operator acceptance is recorded in [user-validation.md](user-validation.md).
