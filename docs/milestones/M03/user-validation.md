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
- At this stage, fast mode remained unavailable; the 8-step setting had not
  yet been quality accepted. The later fast-mode acceptance is recorded below.
- Production licensing is not fully cleared. This milestone closeout does not
  claim unrestricted production readiness.
- Cold-model loading latency remains significant; measured cold and reload
  times are retained in verification.md.

The operator supplied this assessment and requested M03B closeout in the
current user message on 2026-10-22. No independent subjective judgment is
inferred from the WAV files.

## M03B fast-mode listening acceptance — 2026-10-22

**OBSERVED (operator-reported):** The operator listened to the four tested
VoxCPM2 samples generated with eight diffusion steps and confirmed that their
audio quality is acceptable. This accepts fast mode for the tested English,
Russian, Swedish and mixed-language samples. Quality remains the 10-step
default, and auto continues to select quality. This feedback was supplied in
the current user request; no independent listening judgment is inferred.

## M03B high-quality mode selection — 2026-10-22

**OBSERVED (operator-reported):** After listening to the blinded VoxCPM2
10-, 12- and 16-step comparison samples, the operator selected 16 diffusion
steps as an additional quality option. The selection applies to the tested
comparison set and is implemented as `mode=high_quality`; `quality` remains
the 10-step default and `auto` continues to select `quality`. The private
comparison and performance provenance is recorded in [verification.md](verification.md).

## Final M03B mode acceptance and closeout — 2026-10-22

**OBSERVED (operator-reported):** The operator listened to the final live
`high_quality` recording at
`private/m03b/high-quality-live-20261022/high_quality.wav` and reported:
**“Audio sounds good. Accepted.”** The operator explicitly accepted M03B
closeout for its agreed implementation and technical-validation scope.

The final accepted configuration set is:

- `fast`: 8 diffusion steps.
- `quality`: 10 diffusion steps; default mode.
- `high_quality`: 16 diffusion steps.
- `auto`: maps to `quality` (10 steps).

Acceptance applies to the agreed implementation and bounded technical
validation, including the operator's reviewed final live recording. It does
not establish unrestricted production readiness, production licensing,
sustained-load capacity, or improved cold-start latency. Those limitations
remain explicit in the result and verification records. The operator supplied
this assessment and closeout approval in the current user request on
2026-10-22; no independent subjective judgment is inferred from the WAV.
