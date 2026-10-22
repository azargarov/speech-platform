# M05A Groq semantic review

Status: **Technical semantic review recorded; operator acceptance pending.**
This is an offline review of the completed private runs. No additional Groq
requests were made. M05A remains IN PROGRESS; M05B is not started.

## Scope and method

Reviewed all 46 responses per model against the exact source case, requested
mode/format/target language and review constraints, using prompt v2 and the
existing M05A preservation standard. Original cases are the 39 rows in
`cases.jsonl`; unseen cases are the seven rows in `unseen-cases.jsonl`.
Authoritative outputs are the `*-requests-20261022/results.jsonl` files under
ignored `private/m05a/`. The earlier failed-transport directory was not used.

Critical means a material change to meaning, language requested, negation,
uncertainty, attribution/perspective, criticism, commitment, technical fact,
or an unsupported action/remediation. Minor means a non-material wording or
formatting issue. Ambiguous means a plausible concern needs operator judgment
before acceptance. Lexical invariant flags were treated only as screening
signals: legitimate number/date translation and Unicode typography can flag,
while semantic errors can pass.

Labels below describe this review, not an automated score. “No confirmed issue”
does not certify translation quality or establish production suitability.

## Case-by-case disposition

### Original 39 cases

| Case | Qwen3.8 27B | GPT-OSS 120B |
|---|---|---|
| en-01-complaint-polite | **Critical:** “disaster” reduced to “concern.” | **Critical:** “disaster” reduced to “problematic.” |
| en-02-spoken-written | No confirmed issue | No confirmed issue |
| en-03-diplomatic-criticism | **Critical:** removes “your team” responsibility (“warning was not addressed”). | **Critical:** removes team responsibility (“warning ... not addressed”). Identifier glyph concern: OPS-4821. |
| en-04-concise-numbers | No confirmed issue | No confirmed issue; numeric/date typography is equivalent. |
| en-05-structured-diagnostics | No confirmed issue | No confirmed issue; identifier glyph concern: edge-7. |
| en-06-translate-sv | No confirmed issue | No confirmed issue |
| en-07-translate-ru | No confirmed issue | No confirmed issue |
| en-08-uncertainty | No confirmed issue | No confirmed issue |
| en-09-commitment | **Critical:** “I can send” becomes “I will provide,” turning ability into a firm commitment. | **Critical:** same ability-to-commitment change. |
| en-10-tech-identifier | No confirmed issue | **Judgment:** formatting changes `CACHE_TTL=0/900` into spaced forms. Values/environments remain clear, but literal identifier preservation is uncertain. |
| en-11-structured-request | No confirmed issue | No meaning issue; identifier glyph concern: N-204. |
| en-12-translate-en-ru | **Ambiguous:** “no payment was taken” becomes “payment was not made,” which may differ from “was not accepted”; amount and transaction are retained. | **Ambiguous:** same distinction, rendered “payment was not accepted.” |
| sv-01-spoken-written | No confirmed issue | No confirmed issue |
| sv-02-complaint-polite | No confirmed issue | No confirmed issue |
| sv-03-diplomatic-criticism | No confirmed issue | No confirmed issue |
| sv-04-concise-date | No confirmed issue | No confirmed issue |
| sv-05-structured-technical | No confirmed issue | No meaning issue; identifier glyph concerns: speech-gw, api-02. |
| sv-06-translate-en | No confirmed issue | No confirmed issue |
| sv-07-translate-ru | No confirmed issue | No confirmed issue |
| sv-08-ambiguous | No confirmed issue | No confirmed issue |
| ru-01-spoken-written | No confirmed issue | No confirmed issue |
| ru-02-complaint-polite | No confirmed issue | No confirmed issue |
| ru-03-diplomatic-criticism | **Critical:** removes direct “you ignored” attribution by making it passive. | No clear meaning failure; passive wording weakens attribution. **Judgment:** retain the original direct responsibility? Identifier glyph concern: RFC-19. |
| ru-04-concise-uncertainty | No confirmed issue | No confirmed issue |
| ru-05-structured-tech | No confirmed issue | **Critical:** “backup not verified” becomes “backup did not pass verification,” asserting a failed check. Identifier glyph concern: PG-53300. |
| ru-06-translate-en | No confirmed issue | No confirmed issue |
| ru-07-translate-sv | **Judgment:** “by Friday” rendered as “before Friday”; may narrow the deadline. | **Judgment:** same possible deadline shift. |
| ru-08-raw-translate | No confirmed issue | No confirmed issue |
| mix-01-en-ru | No confirmed issue | No confirmed issue |
| mix-02-sv-en | No confirmed issue | No meaning issue; release written as “version 2.8,” dropping the literal `v` prefix. **Judgment:** identifier fidelity. |
| mix-03-ru-en | No confirmed issue | No meaning issue; identifier glyph concern: deploy-17. |
| mix-04-sv-ru | No confirmed issue | No meaning issue; identifier glyph concern: cert-qa-09. |
| en-13-politeness-complaint | No confirmed issue | No confirmed issue; explicit correction request is a mild inferred addition, but consistent with the requested polite rewrite. |
| sv-09-diplomatic-deadline | No confirmed issue | No confirmed issue |
| ru-09-translate-sv | No confirmed issue | No meaning issue; identifier glyph concerns: SR-208, node-5. |
| mix-05-en-sv-ru | No confirmed issue; retained “klart” rather than translating it. **Judgment:** incomplete translation, but the apparent contradiction remains. | **Ambiguous:** translates Swedish “klart” as “clear,” potentially changing “done/ready”; apparent open-ticket contradiction remains. Identifier glyph concern: T-88. |
| perf-short | No confirmed issue | No confirmed issue |
| perf-medium | No confirmed issue | No confirmed issue; identifier glyph concerns: cache-4, cache-9. |
| perf-long | No confirmed issue | **Critical:** changes the requested update about trace preservation into an update about trace data status and adds a plan to repeat the test on 6.3.2. It also adds closing thanks. Identifier glyph concerns: X-Region: north, sp-77, ledger-api. |

### Seven unseen cases

| Case | Qwen3.8 27B | GPT-OSS 120B |
|---|---|---|
| u-sv-negation | No confirmed issue | No confirmed issue |
| u-ru-complaint | No confirmed issue | **Critical:** adds a request to reconsider the closure, an unrequested remediation/action. |
| u-sv-fault | No confirmed issue | No meaning issue; identifier glyph concern: srv-12. |
| u-ru-uncertain | No confirmed issue | No confirmed issue |
| u-en-criticism | No confirmed issue | No confirmed issue; “ignored” becomes “not acted upon,” retaining the non-action and causal outcome. |
| u-sv-conditions | No confirmed issue | No confirmed issue |
| u-translate-identifiers | No confirmed issue | No meaning issue; exact parameter and identifiers retained. |

## Findings by model and corpus

### Minor issues

- **GPT-OSS, original `en-13-politeness-complaint`:** adds an explicit polite
  request to correct the incorrect VAT number, which the input did not phrase
  as a direct request. It is a small pragmatic inference consistent with the
  polite complaint transformation; the wrong number and repeated inquiries
  remain clear.
- Otherwise, observed number/date spelling and Markdown/bullet formatting
  differences did not change reviewed case meaning. They are not counted as
  semantic failures. The exact-identifier typography questions remain in the
  operator-judgment category because the output uses look-alike Unicode
  characters in code-like strings.

### Qwen3.8 27B

- **Original 39:** Confirmed critical cases: `en-01-complaint-polite`,
  `en-03-diplomatic-criticism`, `en-09-commitment`,
  `ru-03-diplomatic-criticism`. Judgment cases: `en-12-translate-en-ru`,
  `ru-07-translate-sv`, `mix-05-en-sv-ru`.
- **Unseen 7:** No confirmed critical failure. The Russian complaint,
  negations, conditional restriction and technical identifiers were retained.
- The sample shows source-language retention across the Swedish, Russian and
  mixed-language no-target cases, unlike the local Qwen v2 findings. The four
  confirmed cases still affect criticism severity/attribution and commitments.

### GPT-OSS 120B

- **Original 39:** Confirmed critical cases: `en-01-complaint-polite`,
  `en-03-diplomatic-criticism`, `en-09-commitment`, `ru-05-structured-tech`,
  `perf-long`. Judgment cases: `en-10-tech-identifier`,
  `en-12-translate-en-ru`, `ru-03-diplomatic-criticism`, `ru-07-translate-sv`,
  `mix-02-sv-en`, `mix-05-en-sv-ru`.
- **Unseen 7:** Confirmed critical case: `u-ru-complaint`, where a request to
  reconsider the closure was added. No confirmed negation or condition reversal.
- Several outputs represent technical identifiers with typographic hyphens or
  spacing that differs from the ASCII source. They remain visually legible;
  whether strict byte-for-byte preservation is required for acceptance is an
  operator decision. No inference is made that these visual substitutions
  changed the addressed resource.

## Representative input/output pairs

These excerpts illustrate the judgments; full private outputs remain the
source record.

**Criticism softened (both models, `en-01`):** Input: “This update is a
disaster.” Qwen: “I am writing to express my concern ...”; GPT-OSS: “This
update has been problematic.” Both preserve three crashes and no support
response, while reducing the stated severity.

**Commitment strengthened (both models, `en-09`):** Input: “I can send another
update after the 11:00 review.” Both: “I will provide ... an additional/another
update following/after the 11:00 review.” The source gives permission/ability;
the output commits the speaker to do it.

**Verification status changed (GPT-OSS, `ru-05`):** Input: “Резервная копия ...
не проверена” (backup has not been verified). Output: “Резервная копия ... не
прошла проверку” (backup did not pass verification). Unknown status becomes a
negative result.

**Unsupported action added (GPT-OSS, `u-ru-complaint`):** Input says the
complaint was closed again while the fault recurs. Output adds “Просим
пересмотреть решение” (“We ask that the decision be reconsidered”).

**Supported preservation example (Qwen, `en-10`):** Input prohibits changing
production `CACHE_TTL=900` while setting staging to zero. Output explicitly
retains both environments, values and prohibition.

**Judgment on payment meaning (`en-12`, both):** Input: “No payment was taken.”
Qwen: “Оплата не была произведена.” GPT-OSS: “Платеж не был принят.” Both
retain TX-77, the displayed €42.80 and timeout. The Russian wording may mean
payment was not made/accepted rather than that no funds were captured; operator
judgment is needed for this distinction.

## Comparison with local Qwen3.5 9B v2

The local baseline review identified 17 distinct critical-failure cases in the
original 39, with recurring no-target language switches, a negation reversal,
attribution/commitment issues and identifier/translation failures. Its seven
unseen outputs had three critical findings. Groq outputs were reviewed against
the same case set and v2 semantics, but settings, provider, runtime and
inference boundary differ.

| Corpus | Local Qwen3.5 9B v2 | Groq Qwen3.8 27B | Groq GPT-OSS 120B |
|---|---|---|---|
| Original 39 | 17 previously reviewed critical cases | 4 confirmed critical cases; 3 judgment cases | 5 confirmed critical cases; 6 judgment cases |
| Unseen 7 | 3 previously reviewed critical cases | 0 confirmed critical cases | 1 confirmed critical case |

Counts are case IDs, not severity-weighted scores; multiple issue types may
overlap within a case. “Judgment” is not a pass. The Groq review shows fewer
confirmed critical case IDs than the local review for this corpus, but the
sample is synthetic and small, reviewers are not blinded, and the models were
not evaluated with identical providers/settings. This is not a winner
declaration, production readiness finding or statistical comparison.

## Direct observations and interpretations

**OBSERVED:** Both authoritative Groq runs contain 46 successful result rows,
one for each source case, with prompt version v2 and the expected model name.
The review compared the stored response text to the tracked source/options.
The complete raw result files remain private.

**INTERPRETATION:** The listed critical cases materially violate the
preservation criteria; listed judgment cases warrant operator review before
acceptance. Results support neither unconditional model acceptance nor a
numerical winner. Local baseline case counts are attributed to the existing
`prompt-refinement.md` semantic review.

**NOT ESTABLISHED:** Independent second-reviewer agreement, professional
linguistic validation of every translation, account cost/billing, generalization
beyond these synthetic cases, and production suitability.
