# M03 operator validation

## Prior M03A listening packs — historical evidence

M03A generated multiple blind sample sets before the final decision below.
Private audio and mapping keys remain in the ignored attempt directories:

- Round 1: `private/m03a/M03A-20261021-01/listening/manifest.csv` with 18 WAV
  files under `listening/audio/`; the separate `answer-key.csv` maps IDs to
  candidate. Operator Round 1 ratings are grouped in
  `private/m03a/M03A-20261021-02/results/round1-rating-summary.csv`. The
  unrated `sample-69378afb` remains explicitly unrated.
- Round 2: `private/m03a/M03A-20261021-02/listening/manifest.csv` with 12 WAV
  files under `listening/audio/`; `answer-key.csv` separately maps candidate
  and configuration. No additional Round 2 subjective ratings were recorded.
- Focused performance comparison: 10-step baseline versus 8-step candidate
  under `private/m03a/M03A-20261021-03/performance/audio/`. Match language and
  repeat indices when comparing; reports and per-sample measurements are in
  the same attempt's `results/` directory.
- Focused language samples: `private/m03a/M03A-20261021-03/language/audio/`
  with exact text and output rows in `results/language-cases.csv`. Before the
  final assessment, observed spoken language and word correctness were marked
  pending listening.

These paths and previous ratings are retained for provenance. The final
operator assessment is recorded below and is the M03A closeout decision.

## M03A candidate decision and listening assessment — 2026-10-21

**OBSERVED (operator-reported):** The operator listened to the M03A VoxCPM2
and MOSS-TTS-Nano samples and reported:

- VoxCPM2 produces good results across English, Russian, Swedish and
  mixed-language inputs.
- MOSS-TTS-Nano produces acceptable pure English, but unsatisfactory Russian,
  Swedish and mixed-language speech.
- VoxCPM2 is selected as the primary candidate for initial M03B integration.
- MOSS-TTS-Nano is not selected for initial integration.
- The 10-step configuration remains the quality baseline. The 8-step setting
  is a candidate for faster inference, subject to separate quality acceptance.
- Neither pinned model exposes a native detected-language-code API. VoxCPM2
  successfully synthesizes multilingual text without explicit language
  metadata.

This is M03A listening validation and candidate selection. It does not establish
production acceptance, resolve production licensing, validate M03B behavior,
or accept deployment. Operator and date are recorded from this user message;
no audio was independently auditioned in this environment during closeout.

## M03B live validation and operator listening acceptance — 2026-10-22

**PASS for the tested quality-mode baseline.** The operator reports having
listened to all four M03B quality-mode recordings (English, Russian, Swedish
and mixed-language) and confirms: **all sound good**. This is operator-reported
acceptance of these four samples, not a broad or sustained-load quality claim.

Live validation was performed on host llm through the canonical Gateway and
Compose project using the pinned TTS image and staged VoxCPM2 model. The
recorded evidence, response behavior, lifecycle checks, STT coexistence,
latency, RTF and GPU observations are in [verification.md](verification.md).

The private operator listening pack is at
`private/m03b/listening/index.html`; exact input strings, configuration,
model/image identities, audio format, hashes and measurements are in
`private/m03b/listening/metadata.json`. The pack contains English, Russian,
Swedish and mixed-language quality-mode samples. No subjective ratings were
assigned.

### Acceptance scope and remaining limitations

- Accepted: the four named quality-mode recordings sound good to the operator.
- The live technical observations and their scope remain as recorded in
  [verification.md](verification.md), including one short simultaneous STT/TTS
  request pair. That observation does not establish sustained concurrent-load
  behavior.
- Fast mode remains unavailable; the 8-step setting has not been quality
  accepted.
- Production licensing is not fully cleared. This milestone closeout does not
  claim unrestricted production readiness.
- Cold-model loading latency remains significant; measured cold and reload
  times are retained in verification.md.

The operator supplied this assessment and requested M03B closeout in the
current user message on 2026-10-22. No independent subjective judgment is
inferred from the WAV files.
