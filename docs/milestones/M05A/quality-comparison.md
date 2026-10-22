# M05A quality comparison

Status: **Baseline and prompt v2 technical triage complete; operator review pending.** All examples
below are synthetic. Complete inputs, prompts, responses, lexical flags and
timing are in ignored `private/m05a/qwen-full-20261022/` and
`private/m05a/gemma-full-20261022/`.

## Corpus run summary

| Candidate | Completed | Lexical-flagged cases | No-target language failures | Assessment |
|---|---:|---:|---:|---|
| Qwen3.5 9B Q4_K_M v1 | 39/39 | 28/39 | 10/12 Swedish/Russian cases | Reject for now |
| Qwen3.5 9B Q4_K_M v2 | 39/39 | 26/39 | 9/12 Swedish/Russian cases | Reject for now |
| Gemma 3 12B IT Q4_K_M | 39/39 | 26/39 | 6/12 Swedish/Russian cases | Reject for now |

The v1 and v2 language-failure counts are case-by-case reviews of non-English inputs with
no requested target: Swedish cases `sv-01`–`sv-05`, `sv-08`, `sv-09`; Russian
cases `ru-01`–`ru-05`. Outputs that switched to English fail the requested
behavior even when their meaning was otherwise mostly retained.

Lexical flags report missing exact invariant strings after case-folding and
whitespace normalization. They include legitimate translations and number/date
format changes, so 28/39 and 26/39 are not semantic failure rates. Conversely,
passing those checks does not establish meaning preservation. The critical
examples below came from direct review of all 78 full-run responses and are
INTERPRETATION, not operator acceptance.

## Critical preservation findings

### Qwen3.5 9B

- `sv-03-diplomatic-criticism` reverses the negation. The source says the
  warning was removed; the output says it **was not removed**. This is a
  direct factual contradiction.
- `en-09-commitment` drops “today” from the statement that a fix cannot be
  promised today. “At this time” weakens the explicit time boundary.
- `sv-05-structured-technical` translates source “värden api-02” (host
  `api-02`) as “Value API-02” and emits English although no translation was
  requested.
- `mix-02-sv-en` changes release identifier `v2.8` to `2,8` and translates
  technical endpoint `healthz` to a generic health check.
- `sv-09-diplomatic-deadline` changes Swedish input to English and invents
  “immediate and decisive remediation,” which was not requested or committed.
- Six of seven Swedish no-target cases and four of five Russian no-target
  cases were returned in English.

### Gemma 3 12B IT

- `en-10-tech-identifier` adds “We've determined” and an unsupported reason
  about stability and consistency, and turns a direct staging instruction into
  a reported decision.
- `ru-05-structured-tech` changes “the backup has not been verified” into
  “the backup did not pass verification,” turning unknown status into a
  negative test result.
- `ru-02-complaint-polite` omits the criticism “this is simply a failure” and
  adds an apology from the speaker.
- `en-03-diplomatic-criticism` changes the categorical claim that the team
  ignored the warning into a possible oversight, changing certainty and
  responsibility.
- `mix-02-sv-en` replaces endpoint identifier `healthz` with a generic health
  check; `ru-09-translate-sv` alters identifier `node-5` to `nod-5`.
- `en-11-structured-request` changes the speaker's uncertainty about archived
  records into an assertion that no confirmation has yet been provided.
- Five of seven Swedish no-target cases and one of five Russian no-target
  cases were returned in English.

These failures concern explicit preservation requirements. Fluency, low
latency and lexical-check presence do not offset them.

## Representative outputs for operator review

### English: complaint, polite mode

Input (`en-01-complaint-polite`):

> This update is a disaster. The server crashed three times and nobody from
> support bothered answering.

Qwen3.5:

> This update has proven to be deeply disappointing, as the server experienced
> three separate crashes, and unfortunately, no one from the support team
> responded to our inquiries.

Gemma 3:

> I am very concerned about this update, as it appears to have caused
> significant issues. The server experienced three crashes, and unfortunately,
> I haven't been able to reach anyone from support for assistance.

Both retain the number of crashes and missing support response. Both soften
“a disaster”; Gemma also changes the complaint into the speaker's inability to
reach support. Operator review should decide whether either retains the
complaint's severity and emotional intent.

### Swedish: written mode without translation

Input (`sv-04-concise-date`):

> Vi väntar fortfarande på svar från Erik. Han sa den 21 augusti att testet
> skulle vara klart, men det är inte klart.

Qwen3.5:

> We still await Erik's response. He stated on August 21 that the test would be
> complete, but it remains unfinished.

Gemma 3:

> We are still waiting for Erik's response. He said the test would be finished
> by August 21st, but it isn't.

Both outputs are English despite no target language. Gemma also makes the
source's forecast sound more like a deadline commitment.

### Russian: structured diagnostics

Input (`ru-05-structured-tech`):

> На узле db-03 в 02:11 UTC сработал код PG-53300; запрос 7f2a отклонён.
> Резервная копия от 6 марта не проверена.

Qwen3.5 returns an English incident report, failing language retention. Gemma
returns Russian but says the backup “не прошла проверку” (did not pass
verification), changing the source's “не проверена” (not verified) into a
negative result.

## Overall quality judgement

- **Meaning preservation/completeness:** both have critical failures; neither
  is suitable for acceptance under this task's fundamental requirement.
- **Grammar/naturalness:** outputs are generally fluent, but occasional
  awkward phrasing and excessive diplomatic expansion occurred. Fluency is not
  evidence of correctness.
- **Politeness/diplomacy:** both sometimes replace criticism or certainty with
  softer claims; Qwen also invented immediate remediation.
- **Translation accuracy:** both translate common language adequately in many
  cases, but no-target language switching and changes to technical identifiers
  are disqualifying issues.
- **Formatting:** structured cases generally used headings or lists; the
  formatting result still needs operator review. Concise cases often changed
  number/date notation, which is legitimate only when the value remains exact.
- **Hallucinations/omissions:** Qwen invented remediation and omitted an
  explicit time boundary. Gemma invented a rationale and apology, omitted a
  criticism and changed uncertainty/status in several cases.

**Recommendation:** do not select either candidate for future M05B work yet.
Local inference is technically feasible on this host at 4K context, but model
selection remains unresolved because both candidates violate required
meaning/language-preservation behavior. The next decision belongs to operator
review of the private outputs and these representative cases; no additional
model is proposed or evaluated here.

## Prompt v2 retest — 2026-10-22

Prompt v1 and all original raw evidence remain unchanged. The controlled prompt
refinement, baseline failure review, targeted and unseen cases, full v2 corpus
comparison, performance table and recommendation are recorded in
[prompt-refinement.md](prompt-refinement.md). In brief, v2 fixed the `sv-03`
negation reversal and removed `sv-09`'s invented remediation, but it still
failed Swedish/Russian language retention and introduced/retained critical
semantic errors. The v2 full run had 17 distinct critical-failure cases after
manual review. Neither Qwen nor v2 is ready for operator acceptance; operator
review is still pending.

Correction: a stale final paragraph in the detailed v2 report previously said
15/39. The listed case IDs total 17; `mix-03` and `perf-long` had been omitted
from that sentence. The corrected count is 17 distinct cases, with original
raw model outputs preserved; see the case-level tally in
[`prompt-refinement.md`](prompt-refinement.md).
