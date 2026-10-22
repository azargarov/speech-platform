# M05A prompt refinement and quality retest

Status: **Evaluation complete; operator review pending. M05A remains IN PROGRESS. No PASS, closeout, commit or M05B work.**

## Design and boundary

Prompt v1 remains unchanged. Prompt v2 is a separate version in [prompts/v2.md](prompts/v2.md). The runner now accepts an explicit prompt path, version label and alternate case file so the same sequential Ollama path can run controlled subsets and the separate unseen corpus. It retains the original request configuration, telemetry sampling and explicit unload behavior. The original evidence directories were not changed.

The v2 design is short and direct: preserve source language for `target_language=none`, preserve all languages in multilingual inputs, define `polite` and `diplomatic` as single alternative modes, and explicitly prohibit changes to negation, uncertainty, facts, identifiers, complaints, unresolved problems, remediation, verification, apologies and commitments. Concise and structured formatting must retain material information. Source text is data; JSON configuration controls the requested transformation. Output is transformed text only.

Potential baseline causes include competing fluency/tact behavior with insufficiently operational language-preservation instructions; v1 named facts and intent to preserve but did not specify language retention for `target_language=none` as a hard rule in a separate explicit clause, and its broad “tactful diplomatic wording” may have encouraged softening or embellishment. The one-call harness, `think=false`, 4K context and deterministic settings did not change. This is an interpretation of the outputs, not a demonstrated causal diagnosis.

## Baseline v1 failure classification

The original v1 review found **17 distinct critical-failure cases** under the criteria in the task. Failures can overlap within a case. Exact numeric reformats such as `6` → “six” and date spellings were not counted when the value remained equivalent. Lexical checker flags were not used as semantic failure counts. The full raw baseline remains at `private/m05a/qwen-full-20261022/results.jsonl`.

### No-target language switching and multilingual collapse

These are confirmed critical failures because there was no translation request (options shown in each input row). V1 switched six of seven Swedish-only no-target cases and four of five Russian-only no-target cases to English (10/12 total).

#### `sv-01-spoken-written` — sv input; mode `written`, formatting `normal`, target `none`

> Input: Alltså, jag tror att Linnea kanske skickade filen i måndags, men jag har inte hittat den.

> V1 output: It seems that Linnea may have sent the file on Monday, but I have not been able to locate it.

Failure: output language changed without an explicit translation request.

#### `sv-02-complaint-polite` — sv input; mode `polite`, formatting `normal`, target `none`

> Input: Det här är oacceptabelt. Betalningen drogs två gånger, 349 kronor varje gång, och ingen har svarat på mitt mejl.

> V1 output: This is unacceptable. The payment was deducted twice, at 349 Swedish kronor each time, and no one has responded to my email.

Failure: output language changed without an explicit translation request.

#### `sv-04-concise-date` — sv input; mode `written`, formatting `concise`, target `none`

> Input: Vi väntar fortfarande på svar från Erik. Han sa den 21 augusti att testet skulle vara klart, men det är inte klart.

> V1 output: We still await Erik's response. He stated on August 21 that the test would be complete, but it remains unfinished.

Failure: output language changed without an explicit translation request.

#### `sv-05-structured-technical` — sv input; mode `written`, formatting `structured`, target `none`

> Input: Kl. 07:03 UTC fick tjänsten speech-gw felkod E_CONN_RESET på värden api-02. Försök 4 misslyckades också; DNS har inte kontrollerats.

> V1 output: **Incident Report: Speech-GW Service Failure**

*   **Time of Occurrence:** 07:03 UTC
*   **Service Affected:** Speech-GW
*   **Error Code Encountered:** E_CONN_RESET
*   **Affected Component:** Value API-02
*   **Retry Status:** Attempt 4 failed.
*   **DNS Verification Status:** Not performed.

Failure: output language changed without an explicit translation request.

#### `sv-08-ambiguous` — sv input; mode `diplomatic`, formatting `normal`, target `none`

> Input: När Oskar sa att ändringen inte var liten menade han kanske kostnaden, inte tiden.

> V1 output: When Oskar stated that the change was not minor, he may have been referring to the cost rather than the duration.

Failure: output language changed without an explicit translation request.

#### `sv-09-diplomatic-deadline` — sv input; mode `diplomatic`, formatting `normal`, target `none`

> Input: Det är tredje gången på 2 veckor som exporten missar kolumnen customer_ref. Jag accepterar inte att detta kallas löst.

> V1 output: This marks the third instance within a two-week period wherein the export function has failed to populate the 'customer_ref' column. We do not accept that this recurring deficiency be characterized as merely "loose" or incidental; it constitutes a substantive operational failure requiring immediate and decisive remediation.

Failure: output language changed without an explicit translation request.

#### `ru-01-spoken-written` — ru input; mode `written`, formatting `normal`, target `none`

> Input: Ну, я, наверное, отправил отчёт Ирине вчера вечером, но письма в отправленных нет.

> V1 output: Well, I probably sent the report to Irina last evening, but it does not appear in my Sent folder.

Failure: output language changed without an explicit translation request.

#### `ru-02-complaint-polite` — ru input; mode `polite`, formatting `normal`, target `none`

> Input: Это просто провал: заказ 58102 отменили без предупреждения, а поддержка молчит уже 4 дня.

> V1 output: This is simply a failure: Order 58102 was cancelled without prior notice, and support has remained silent for four days.

Failure: output language changed without an explicit translation request.

#### `ru-03-diplomatic-criticism` — ru input; mode `diplomatic`, formatting `normal`, target `none`

> Input: Вы проигнорировали мой комментарий к RFC-19, и из-за этого 12 клиентов получили неверную цену. Прошу исправить отчёт до вторника.

> V1 output: We note that the comment regarding RFC-19 was not addressed, which resulted in twelve clients being charged an incorrect amount. We respectfully request that the report be corrected by next Tuesday.

Failure: output language changed without an explicit translation request.

#### `ru-05-structured-tech` — ru input; mode `written`, formatting `structured`, target `none`

> Input: На узле db-03 в 02:11 UTC сработал код PG-53300; запрос 7f2a отклонён. Резервная копия от 6 марта не проверена.

> V1 output: **Incident Report: Node db-03**<br>*Timestamp:* 02:11 UTC<br>*Event:* Execution of code PG-53300 triggered an error; request identifier 7f2a was rejected.<br>*Status:* The backup dated March 6 has not been verified.

Failure: output language changed without an explicit translation request.

#### `mix-04-sv-ru` — sv+ru input; mode `written`, formatting `concise`, target `none`

> Input: Jag är inte säker, но сертификат cert-qa-09 går ut 30 september och ingen har bokat förnyelse.

> V1 output: Jag är osäker. Certifikatet cert-qa-09 löper ut den 30 september och ingen har bokats för förlängning.

Failure: output collapsed the multilingual source into Swedish without a translation request.

### Other confirmed baseline semantic failures

#### `sv-03-diplomatic-criticism` — mode `diplomatic`, formatting `normal`, target `none

> Input: Ni tog bort varningen i version 5.2 trots min kommentar. Det ledde till 6 felaktiga aviseringar; jag vill att beslutet granskas.

> V1 output: Det har konstaterats att varningen inte togs bort i version 5.2, trots den framförda kommentaren. Detta beslut har lett till sex felaktiga aviseringar och föranleder en begäran om att frågan ska granskas.

Critical: source says the warning was removed; output says it was not removed, reversing the negation. Digit `6` → “six” is equivalent and is not a failure.

#### `en-03-diplomatic-criticism` — mode `diplomatic`, formatting `normal`, target `none

> Input: Your team ignored the warning on ticket OPS-4821, so we lost 17 minutes of logs. I still need an explanation by Friday.

> V1 output: Regarding ticket OPS-4821, it appears that the warning was not addressed by your team, resulting in a loss of 17 minutes of log data. We would appreciate receiving an explanation regarding this matter by Friday.

Critical: “your team ignored” became hedged “it appears that the warning was not addressed,” weakening certainty and responsibility.

#### `en-09-commitment` — mode `polite`, formatting `normal`, target `none

> Input: We cannot promise a fix today. I can send another update after the 11:00 review.

> V1 output: We are unable to guarantee a resolution at this time; however, I will provide another update following the 11:00 review.

Critical: “cannot promise a fix today” became “unable to guarantee a resolution at this time,” weakening the explicit today boundary.

#### `en-11-structured-request` — mode `written`, formatting `structured`, target `none

> Input: Please check account N-204 by 5 pm on 7 November. I have not confirmed whether the export includes archived records.

> V1 output: **Subject: Account Verification and Export Status**

*   **Action Required:** Verify account **N-204**.
    *   **Deadline:** 5:00 PM, 7 November.
*   **Status Update:** Confirmation regarding the inclusion of archived records in the export has not yet been provided.

Critical: first-person “I have not confirmed whether” became “confirmation ... has not yet been provided,” changing whose verification status is represented.

#### `mix-02-sv-en` — mode `polite`, formatting `normal`, target `sv

> Input: Vi rullade tillbaka release v2.8 because healthz stayed red for 9 minuter; orsaken är fortfarande okänd.

> V1 output: Vi återskaffade version 2,8 av släppet eftersom hälsokontrollen visade sig röd i nio minuter; orsaken är fortfarande okänd.

Critical: release identifier `v2.8` became `2,8`; endpoint identifier `healthz` was translated to generic wording despite a requested Swedish target.

#### `mix-03-ru-en` — mode `diplomatic`, formatting `structured`, target `en`

> Input: После deploy-17 очередь выросла до 240, но latency не измеряли и rollback не запускали.

> V1 output: Following the deployment of version 17, the queue increased to 240. Latency was not measured, and a rollback was not initiated.

Critical: technical identifier `deploy-17` was replaced with generic wording despite explicit translation.

Cases can have multiple failures. The counts above are distinct case IDs: language failures overlap with `sv-05`/`sv-09` and other semantic findings; `sv-03` negation reversal is separate from its v2 language-switch failure. The `en-09` and `en-11` findings are source meaning issues, not lexical-flag conclusions.

## Targeted v1/v2 regression comparison

Ten original cases were rerun with unchanged inputs. The results below are direct output comparisons; interpretation reflects semantic review, not lexical checker totals.

| Case | V1 result | V2 result | Assessment |
|---|---|---|---|
| `en-09-commitment` | We are unable to guarantee a resolution at this time; however, I will provide another update following the 11:00 review. | We are unable to guarantee a resolution by today; however, I will provide an additional update following the 11:00 review. | V2 retains “today” more directly; no critical change observed. |
| `en-11-structured-request` | **Subject: Account Verification and Export Status**

*   **Action Required:** Verify account **N-204**.
    *   **Deadline:** 5:00 PM, 7 November.
*   **Status Update:** Confirmation regarding the inclusion of archived records in the export has not yet been provided. | **Account Verification Request**

*   **Action Required**: Verify account N-204.
*   **Deadline**: 5:00 PM, 7 November.
*   **Status Note**: Confirmation regarding the inclusion of archived records in the export has not yet been received. | V2 repeats the perspective shift: “confirmation ... has not yet been received.” Critical status attribution issue remains. |
| `sv-01-spoken-written` | It seems that Linnea may have sent the file on Monday, but I have not been able to locate it. | I believe that Linnea may have sent the file on Monday, but I have not been able to locate it. | Both versions switch Swedish to English; critical failure persists. |
| `sv-02-complaint-polite` | This is unacceptable. The payment was deducted twice, at 349 Swedish kronor each time, and no one has responded to my email. | This is unacceptable. The payment was deducted twice, at 349 Swedish kronor each time, and no one has responded to my email. | Both versions switch Swedish to English; critical language failure persists. |
| `sv-03-diplomatic-criticism` | Det har konstaterats att varningen inte togs bort i version 5.2, trots den framförda kommentaren. Detta beslut har lett till sex felaktiga aviseringar och föranleder en begäran om att frågan ska granskas. | Despite my comment, the warning was removed in version 5.2, which resulted in six incorrect notifications; I respectfully request that this decision be reviewed. | V1 reverses “warning removed”; v2 correctly says it was removed, but switches Swedish to English. One critical meaning failure fixed; a language failure remains. |
| `sv-05-structured-technical` | **Incident Report: Speech-GW Service Failure**

*   **Time of Occurrence:** 07:03 UTC
*   **Service Affected:** Speech-GW
*   **Error Code Encountered:** E_CONN_RESET
*   **Affected Component:** Value API-02
*   **Retry Status:** Attempt 4 failed.
*   **DNS Verification Status:** Not performed. | **Incident Report: Speech-GW Service Failure**

*   **Timestamp:** 07:03 UTC, Day 14 (Kl. 07:03)
*   **Affected System:** Speech-GW Service
*   **Error Code:** E_CONN_RESET
*   **Location:** Value API-02
*   **Retry Status:** Attempt 4 failed.
*   **DNS Verification:** Not performed. | Both switch Swedish to English. V2 additionally invents “Day 14” and translates `värden` (host) as “Value”; critical factual/terminology concerns. |
| `ru-01-spoken-written` | Well, I probably sent the report to Irina last evening, but it does not appear in my Sent folder. | Well, I probably sent the report to Irina last evening, but it does not appear in the Sent folder. | Both versions switch Russian to English; critical failure persists. |
| `ru-02-complaint-polite` | This is simply a failure: Order 58102 was cancelled without prior notice, and support has remained silent for four days. | This is simply unacceptable: Order #58102 was cancelled without any prior notice, and support has remained silent for four days. | Both versions switch Russian to English; critical failure persists. |
| `ru-03-diplomatic-criticism` | We note that the comment regarding RFC-19 was not addressed, which resulted in twelve clients being charged an incorrect amount. We respectfully request that the report be corrected by next Tuesday. | Вы пропустили мой замечание по поводу RFC-19, в результате чего 12 клиентов были выставлены с ошибочной ценой. Я прошу вас пересмотреть и скорректировать отчёт до вторника. | V2 stays Russian, but changes “12 clients received an incorrect price” into a malformed claim that they were billed/invoiced at an incorrect price; critical factual change and poor grammar. |
| `sv-09-diplomatic-deadline` | This marks the third instance within a two-week period wherein the export function has failed to populate the 'customer_ref' column. We do not accept that this recurring deficiency be characterized as merely "loose" or incidental; it constitutes a substantive operational failure requiring immediate and decisive remediation. | This is the third instance in two weeks that exports have failed to populate the customer_ref column; I cannot accept this being dismissed as a minor issue. | V2 removes invented “immediate and decisive remediation” and preserves rejection of “resolved,” but switches Swedish to English and adds “minor issue,” changing the criticism. |

Targeted findings: **sv-03 negation now passes**; `sv-09` invented remediation is removed; English and Russian no-target preservation did not improve consistently. In the selected cases, all five Swedish samples still switch to English; both selected Russian language-switch examples still switch. The full corpus comparison below provides the aggregate language outcome.

## Unseen regression corpus

Seven new cases in [unseen-cases.jsonl](unseen-cases.jsonl) were run after prompt v2 was fixed and before the full corpus. Raw responses are in `private/m05a/qwen-unseen-v2-20261022/results.jsonl`. The set covered Swedish negation/conditions/unresolved faults; Russian complaint and uncertain diagnosis; explicit criticism; and requested Russian-to-English translation with identifiers.

| Case | Result |
|---|---|
| `u-sv-negation` | Negations retained, but Swedish was translated to English with no target; critical language failure. |
| `u-ru-complaint` | Critical: replaced complaint with an invented service-provider response, closed the case, and added patience/offer commitments. |
| `u-sv-fault` | Preserved unresolved 503 and no-restart status in structured Swedish. |
| `u-ru-uncertain` | Critical: “probably related” became stronger “most likely caused by”; also added “version” and “morning” details. |
| `u-en-criticism` | Retained the criticism and 12 failed jobs; number formatting is equivalent. |
| `u-sv-conditions` | Preserved both conditions, deadline and restriction in Swedish. |
| `u-translate-identifiers` | Translated into English while retaining prohibition, identifiers and incomplete check status. |

Unseen set outcome: **3 confirmed critical failures in 7 cases** (`u-sv-negation`, `u-ru-complaint`, `u-ru-uncertain`). This shows that explicit rules reduced neither multilingual drift nor diplomatic role invention reliably.

## Full corpus v1/v2 comparison

Both full runs completed 39/39 sequential cases with `temperature=0`, `think=false`, `num_ctx=4096`, seed `20261022`, one request at a time and the same model digest. Detailed outputs remain separate in private run directories. Human review found **17 distinct critical-failure cases in v2**, the same distinct-case count as baseline, though the failure mix changed. V2 corrected the v1 negation reversal and remediation invention but exposed or retained other failures.

### V2 confirmed critical cases

- No-target language policy: `sv-01`, `sv-02`, `sv-03`, `sv-04`, `sv-05`, `sv-08`, `sv-09` (all seven Swedish-only cases), `ru-01`, `ru-02` (two Russian-only cases), and `mix-04` (Russian content collapsed into Swedish): **10 cases**. V1 had 10/12 language switches among Swedish/Russian-only no-target cases; v2 has 9/12. Swedish regressed from 6/7 switches to 7/7; Russian improved from 4/5 to 2/5. The aggregate change is not consistent language preservation.
- `en-03`: diplomatic rewrite weakens “ignored” to “did not address,” changing the criticism’s implication of deliberate disregard.
- `en-11`: first-person unconfirmed status changes to “confirmation ... has not yet been received.”
- `ru-03`: changes clients receiving an incorrect price to clients being billed/invoiced at an incorrect price; the generated Russian is also ungrammatical.
- `mix-02`: changes identifier `v2.8` to `2.8` and translates `healthz` into generic wording despite the requested Swedish target.
- `mix-03`: changes technical identifier `deploy-17` to “deployment of version 17” despite an explicit English target.
- `perf-medium`: source says “I checked”; v2 says “I verified,” implying a stronger verification status.
- `perf-long`: v2 adds UTC to the requested “before 09:00 tomorrow” deadline, inventing a time zone.

Case-level regressions: v1 `perf-medium` said “reviewed” for “checked”; v2 says “verified,” which materially overstates the check. V2 also adds UTC to the `perf-long` deadline without source support. `sv-05` invents “Day 14” and mistranslates “host” as “Value”; `sv-09` also adds “minor issue” while preserving rejection of “resolved.” Those additional defects do not increase the unique-case count. `sv-03` no longer reverses negation, and v2 does not repeat the v1 `sv-09` remediation invention.

### Cases requiring operator judgment

- `en-01`: “a disaster” becomes “highly problematic,” reducing complaint intensity.
- `en-02`: “14 June” becomes “June 14” (equivalent date), but “we” appears in v2 though the input omitted an explicit actor for approval.
- `en-08`: “I think” becomes “appears”; likely equivalent uncertainty, but altered grammatical viewpoint.
- `mix-02`: awkward Swedish wording beyond the clear identifier mutation.
- `perf-long`: the requested update is expanded to focus on trace recovery and investigation; assess whether this adds an unsupported scope.
- Existing v1 ambiguous items remain operator review issues; see the baseline quality comparison and raw outputs.

### Formatting and translation review

V2 followed the requested shapes on the six structured cases and four concise cases: headings/bullets organized the existing content, and concise outputs remained short. This does not establish complete factual correctness; for example, structured `sv-05` adds a date. Explicit translation cases generally retained the core meaning in sampled review, but identifier handling is not reliable: `mix-03` rewrites `deploy-17`, and `mix-02` changes `v2.8`/`healthz` despite the requested Swedish translation. No aggregate translation-accuracy score is claimed; material errors are listed case by case.

### Performance

| Measure | V1 full corpus | V2 full corpus | Difference |
|---|---:|---:|---:|
| Total elapsed | 62.73 s | 61.24 s | -2.4% |
| Warm median request latency | 1.023 s | 1.017 s | -0.6% |
| Warm request range | 0.668–9.517 s | 0.688–9.653 s | similar; long tail +0.14 s |
| Median generation throughput | 42.11 tokens/s | 42.21 tokens/s | +0.2% |
| Peak total GPU use | 8,510 MiB | 8,510 MiB | no observed change |
| Minimum free GPU memory | 6,400 MiB | 6,400 MiB | no observed change |
| Model VRAM at 4K context | 5,517,187,481 bytes | 5,517,187,481 bytes | same placement |
| Peak Ollama container RAM | 1,947,767,668 bytes | 1,946,693,926 bytes | effectively unchanged |

Latency differs by only one run and the v2 cold load was 9.23 s versus 9.26 s in v1. Full-run host RAM was sampled for both by the harness; v2 minimum `MemAvailable` was about 55.8 GiB. GPU offload was full for both, and both explicit unloads left `/api/ps` empty. These single serialized runs do not establish sustained capacity or simultaneous LLM/TTS safety. Generation throughput and tail metrics are descriptive of this synthetic workload only.

## Optional quantization investigation (recommendation only)

As checked on 2026-10-22, Ollama’s official Qwen3.5 catalog exposes `qwen3.5:9b-q8_0` (about 10 GB; catalog short digest `a8ee95bc3592`); no official Q5_K_M tag was found. The official Qwen 3.5 9B base model is labeled Apache-2.0. Catalog availability and model license are not a substitute for pinning and recording the exact pulled artifact digest and validating provenance at pull time. Sources: [Ollama Qwen3.5 tags](https://ollama.com/library/qwen3.5/tags), [Qwen/Qwen3.5-9B model files and license](https://huggingface.co/Qwen/Qwen3.5-9B/tree/main).

Q8 is worth considering only as a separately approved experiment: it is a trusted first-party catalog artifact and could test whether quantization contributes to errors, but prompt v2’s language/mode behavior suggests quantization may not address the main failures. Its listed artifact is roughly 3.4 GB larger than the current 6.6 GB Q4 artifact. The 15 GiB GPU currently has 2,216 MiB baseline STT residency and 6,400 MiB minimum free after the Q4 model in the run; Q8 will consume materially more VRAM. Its exact 4K VRAM requirement is **NOT ESTABLISHED**. A conservative estimate suggests it might fit serially but leave only a few GiB of margin; no inference or download should occur without a separately reviewed capacity check. The same 39 cases take about one minute warm plus cold load; a new cold evaluation would likely cost a few minutes total, with extra time for safe preflight, telemetry and review. No Q5/Q8 model was downloaded and no extra benchmark was run.

## Verification and service impact

- **OBSERVED PASS:** v2 prompt and original 39-case corpus validation; v2 unseen corpus validation; 12 focused unittest cases.
- **OBSERVED PASS:** targeted run 10/10, unseen run 7/7, full v2 run 39/39; all used the exact installed Qwen digest. Each run explicitly unloaded the model and recorded empty `/api/ps` afterward.
- **OBSERVED:** Docker reported Gateway, STT and TTS healthy, each with zero restarts before and after the runs. The model runner did not change Compose or service configuration. Initial in-container HTTP probes failed because the guessed paths/ports and `wget` executable were unavailable; Docker health checks remained healthy. Do not interpret those probes as endpoint checks.
- **NOT ESTABLISHED:** simultaneous LLM/TTS stress remains untested. No full runtime comparison on an alternative quantization was performed.
- Verification commands and outcomes are recorded in [verification.md](verification.md); operator review requirements are in [user-validation.md](user-validation.md).

## Recommendation and stop condition

**Do not accept Qwen3.5 9B Q4_K_M for operator acceptance or M05B.** V2 fixes two important targeted failures but leaves **17 distinct critical-failure cases out of 39** in the full run, including all seven no-target Swedish-only cases switching language, two Russian language switches, changed status/criticism, and identifier mutations. An earlier summary said 15; that count omitted two distinct listed cases (`mix-03` and `perf-long`). The detailed case-level list above is the source of truth; the raw evidence remains unchanged. The unseen corpus includes three further critical failures. Prompt iteration stops here for operator review; any next prompt or model experiment needs a separately scoped, approved evaluation plan. Do not mark M05A PASS, close the milestone, commit, or start M05B.

### Case-by-case v1/v2 review index

All 39 paired outputs were compared; exact raw text, same inputs and settings are in the separate private v1/v2 full-run files. The index records the semantic result of each pair.

| Case | Pair review |
|---|---|
| `en-01-complaint-polite` | Both soften the original “disaster” complaint; v2 is slightly less intense. Operator review. |
| `en-02-spoken-written` | Date format is equivalent; actor and approval status retained. |
| `en-03-diplomatic-criticism` | Critical weakening of “ignored” to “did not address” remains. |
| `en-04-concise-numbers` | Equivalent date and number formatting; material facts retained. |
| `en-05-structured-diagnostics` | Structured facts and unchecked database status retained; shorter labels. |
| `en-06-translate-sv` | Translation retains unfinished backup, date and pending job. |
| `en-07-translate-ru` | Translation preserves uncertainty, both port values and instruction. |
| `en-08-uncertainty` | “I think” becomes event-focused “appears”; operator review of viewpoint. |
| `en-09-commitment` | V2 restores the “today” boundary; no critical failure remains. |
| `en-10-tech-identifier` | Settings and prohibition retained. |
| `en-11-structured-request` | Critical first-person confirmation status still shifts to receipt by an unspecified party. |
| `en-12-translate-en-ru` | Payment negation, amount and transaction retained. |
| `sv-01-spoken-written` | Both switch Swedish to English; critical failure persists. |
| `sv-02-complaint-polite` | Both switch Swedish to English; critical failure persists. |
| `sv-03-diplomatic-criticism` | Negation fixed; v2 switches Swedish to English, so critical language failure remains. |
| `sv-04-concise-date` | Both switch Swedish to English; date and unfinished status retained. |
| `sv-05-structured-technical` | Both switch Swedish to English; v2 invents Day 14 and mistranslates host. |
| `sv-06-translate-en` | Translation preserves invoice, prohibition and three missing lines. |
| `sv-07-translate-ru` | Outputs are identical and preserve possibility/nonconfirmation and times. |
| `sv-08-ambiguous` | Both switch Swedish to English; ambiguity broadly retained. |
| `ru-01-spoken-written` | Both switch Russian to English; critical failure persists. |
| `ru-02-complaint-polite` | Both switch Russian to English; v2 changes “failure” to “unacceptable,” complaint remains. |
| `ru-03-diplomatic-criticism` | Language is fixed; critical change from incorrect price received to incorrect amount billed remains, with malformed Russian. |
| `ru-04-concise-uncertainty` | Russian retained; uncertain cause and timing preserved. |
| `ru-05-structured-tech` | V2 preserves Russian, rejected request and unverified backup; improvement over English v1 output. |
| `ru-06-translate-en` | Outputs are identical and retain prohibition and possible archive copy/date. |
| `ru-07-translate-sv` | Negation and follow-up statement retained. |
| `ru-08-raw-translate` | Outputs are identical and preserve access status, time and incident code. |
| `mix-01-en-ru` | “Rejection” changes to “failure”; potentially material nuance, operator review. |
| `mix-02-sv-en` | Critical identifier changes persist; `v2.8` becomes `2.8`, `healthz` becomes generic wording. |
| `mix-03-ru-en` | Critical `deploy-17` identifier changes to generic deployment/version wording in both versions. |
| `mix-04-sv-ru` | Both collapse multilingual source to Swedish; v2 phrasing remains awkward. |
| `en-13-politeness-complaint` | Outputs are identical and preserve repeated inquiries and incorrect VAT number. |
| `sv-09-diplomatic-deadline` | V2 removes invented remediation but still switches language and adds “minor issue,” changing the speaker’s criticism. |
| `ru-09-translate-sv` | Outputs are identical; untranslated technical identifier and negation retained. |
| `mix-05-en-sv-ru` | Explicit English translation retains open ticket and uncertainty; “verification” becomes “check,” acceptable in context. |
| `perf-short` | Outputs are identical; port distinction retained. |
| `perf-medium` | V2 changes “checked” to “verified,” overstating verification; critical regression. |
| `perf-long` | V2 adds UTC to the 09:00 deadline; critical unsupported detail. |

The case table and critical count are manual semantic review. It is not a model-generated score, and lexical flags are not used as semantic evidence.
