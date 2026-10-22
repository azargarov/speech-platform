# M05A user validation

Status: **VALIDATED and CLOSED 2026-10-22 for bounded evaluation and operator-reviewed candidate retention.**

## Operator review checklist

Review the tracked [quality comparison](quality-comparison.md), [prompt refinement](prompt-refinement.md), prompt v2 and the complete private outputs:

- `private/m05a/qwen-full-20261022/results.jsonl`
- `private/m05a/gemma-full-20261022/results.jsonl`
- First-use timing and preflight outputs under `private/m05a/preflight-*`.
- Short/medium/long resource samples under `private/m05a/resources-*`.

The Groq adapter procedure and review record are in
[groq-cloud-evaluation.md](groq-cloud-evaluation.md), with all 46 responses
per model reviewed in [groq-semantic-review.md](groq-semantic-review.md). The
credential is held in `private/groq_api`; never send it in chat or place it in
Git, command arguments or Compose configuration.

Please assess and record:

- [x] Prompt v2 behavior and its known language limitations were reviewed and
      accepted for generated text subject to user review.
- [x] The operator retained local Qwen3.5 9B Q4_K_M, Groq Qwen3.8 27B and
      Groq GPT-OSS 120B for the planned optional module, accepting known quality
      limits subject to user review. This is selection for future qualification,
      not a correctness guarantee or production-readiness finding.
- [x] Local and Groq findings were reviewed; local Qwen v2 has
      17 original and three unseen critical case IDs; Groq Qwen3.8 has four
      confirmed original critical cases and none unseen; GPT-OSS has five
      confirmed original critical cases and one unseen. See the case-level
      review; counts are not a winner score.
- [x] English, Swedish and Russian samples and translation findings were
      reviewed; known defects remain documented.
- [x] Qwen's Apache 2.0 license and Gemma 3's separate Terms of Use were
      recorded. No Gemma production-use approval is implied.
- [x] Resource, serialized behavior and cold-start evidence were reviewed;
      simultaneous LLM/TTS inference remains untested and production capacity
      is not established.
- [x] The operator's planning decision retains the three selected candidates;
      local evaluation artifacts remain installed for inspection.
- [x] Compare both 46-case Groq output sets against local Qwen3.5 evidence;
      review is recorded in [groq-semantic-review.md](groq-semantic-review.md).
- [x] Operator-judgment cases were reviewed as accepted known limitations:
      payment wording in `en-12`, “by/before
      Friday” in `ru-07`, `klart` in `mix-05`, and technical-identifier
      Unicode/spacing fidelity for GPT-OSS.
- [ ] Account plan/quota and billing were not established; rate-limit headers
      are historical snapshots, not current account state. This does not change
      the bounded candidate-retention decision.

The review records critical cases and unresolved judgment items; it does not
automatically select a model. Meaning preservation remains primary. A model
selection or different decision should be recorded with the operator's
rationale. No M05B work is authorized by this review checklist.

## Cleanup procedure

Both candidates are currently unloaded but their model artifacts remain in
the existing Ollama store. If the operator decides to remove them, remove only
these newly added exact tags:

```sh
docker exec ollama ollama rm qwen3.5:9b-q4_K_M
docker exec ollama ollama rm gemma3:12b-it-q4_K_M
docker exec ollama ollama list
docker exec ollama ollama ps
df -h /var/lib/docker
```

Confirm the pre-existing Ollama tags remain listed, `ollama ps` is empty, and
disk availability increased. Do not run `docker volume rm`, `docker system
prune`, restart Ollama, or remove unrelated model tags. Raw responses and
telemetry under ignored `private/m05a/` can be removed separately after the
operator no longer needs the evidence; they are synthetic but retained
privately for reproducibility.

## Decision record

- Reviewer: **Operator**
- Review date: **2026-10-22**
- Feedback and acceptance decision: **Retain local Qwen3.5 9B Q4_K_M, Groq
  Qwen3.8 27B and Groq GPT-OSS 120B as candidates for the optional text
  module. Accept documented quality limitations subject to user review of
  generated text. This does not establish production readiness.**
- Explicit M05A closeout approval: **Approved 2026-10-22 by the request to
  “close out m05a and commit.”**
- Cleanup decision and outcome: **Retain evaluation model artifacts and
  private synthetic results for further inspection.**

M05A is closed for its bounded evaluation and candidate-retention scope. M05B
implementation, deployment and closeout require their own authorization.
