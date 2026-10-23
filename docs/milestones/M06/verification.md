# M06 verification plan and evidence

Status: **M06A documentation checks recorded; M06 application implementation verification NOT RUN.**

## Evidence scope

- **OBSERVED:** Before editing, branch was `main`, HEAD was `6a7e395f2fcade3984263e63f2b17725f11815fb`, and the only untracked paths were the M06 ADR and M06 directory. M05B closeout was committed at HEAD.
- **OBSERVED:** The six active M06 documents matched the corresponding pre-deployment backup files. The backup directory was not modified.
- **OBSERVED:** Current STT loading/readiness, TTS lifecycle, Ollama adapter/configuration, Gateway readiness and M05B selection code were inspected during the preceding architecture review; the accepted M05B closeout and qualification records were consulted.
- **INTERPRETATION:** The revised planning requirements assign native model lifecycle to each inference owner and keep Gateway orchestration bounded.
- **NOT ESTABLISHED:** Any M06 application behavior, tests, installed-target Ollama warmup compatibility, simultaneous model capacity, live GPU recovery or deployment behavior.

## M06A documentation checks

- **OBSERVED:** `git diff --check` exited 0. Git reports only tracked changes to `PLANS.md`; because the M06 planning documents are untracked, this command does not inspect their contents.
- **OBSERVED:** A read-only Python check over `PLANS.md`, ADR 0022 and all five M06 Markdown files found no trailing whitespace and found every relative Markdown link target on disk.
- **OBSERVED:** Manual cross-document review confirmed M06A–M06E stage names, M05B closeout state, readiness semantics, warmup statuses, timeout/resource requirements, routing restrictions, and approval gates agree across PLANS, ADR, plan and the four milestone records.
- **OBSERVED:** Final Git scope review showed one tracked modified file (`PLANS.md`) and the six pre-existing untracked M06 planning files. No application code, tests, API OpenAPI document, configuration, deployment file, backup file or private runtime state was changed.
- No application tests, API validators, service actions, container actions, inference, cloud calls or live GPU qualification were run.

## Planned offline verification for M06B–M06D

**M06B lifecycle verification** uses fakes for process, worker and clock boundaries. It covers lazy startup, first inference, internal warmup, concurrent load singleflight, initialization deadline, confirmed failure recovery, timer reset after use, active/admitted pending/queued protection, unload/reap/reload races, readiness while unloaded/loading, fatal/cleanup-unconfirmed behavior and shutdown.

**M06C contract and integration verification** uses fake Gateway workers and Ollama boundaries. It covers public authentication, JSON content type/body bound, unknown/duplicate/empty operation handling, validation before side effects, per-operation and partial outcomes, repeat/concurrent requests, overall deadline, disconnect semantics, no content generation/transmission, no cloud warmup, finite nonzero keep-alive, top-level think field, no unload, TTS 429/admission/active-use/idle/VRAM safeguards, and unchanged M05B selection/fallback.

**M06D full offline integration** verifies the following alongside scoped regressions and repository checks:

- STT lazy startup, first inference, internal warmup, concurrent load singleflight, initialization deadline and confirmed failure recovery.
- Idle timer reset after model use; unload only after idle timeout and zero active/admitted pending/queued use; unload/reap/reload races; no duplicate child.
- `/healthz` liveness and `/readyz` availability while unloaded/loading; not-ready fault, drain and cleanup-unconfirmed cases; Gateway readiness stability.
- Public warmup auth, JSON content type/body bound, unknown/duplicate/empty operation handling and full validation before side effects.
- Per-operation ready/partial/unavailable/resource/overloaded/timed-out results, caller disconnect, repeat/concurrent requests, overall deadline, shutdown and no false cancellation or release claims.
- No audio, transcript, prompt or user text in warmup; no synthesis or user-facing LLM output; no cloud provider invocation.
- Ollama warmup serialization: empty request, configured model, `stream:false`, top-level `think:false`, finite nonzero keep-alive and no unload request.
- TTS endpoint reuse and its existing 429/admission/active-use/idle/VRAM safeguards.
- M05B ordering, explicit selection, `local_only`, `allow_cloud`, typed failure fallback and inference without prior warmup.
- Strict configuration, public/private API contracts, shutdown, scoped regression suites and full verification required by the authorized implementation scope.

## Separate M06E live qualification

Live qualification is **NOT AUTHORIZED** by M06A. After M06D evidence, obtain explicit approval for target identity, shared Ollama ownership/eviction acceptance, operation order, resource envelope, timeouts, monitoring, recovery and rollback. Record model state, load/warm latency, natural idle expiry, sampled GPU use/free memory, worker health and Ollama running-model observations. Do not stop or reconfigure Ollama, force unload, assume perfect isolation, or deploy without the separate deployment authorization.
