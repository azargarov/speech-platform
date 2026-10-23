# M06 verification plan and evidence

Status: **M06B offline implementation verification ACCEPTED 2026-10-23. Full M06D integration and live M06E qualification remain NOT RUN; deployment is not authorized.**

## Evidence scope

- **OBSERVED:** Before editing, branch was `main`, HEAD was `6a7e395f2fcade3984263e63f2b17725f11815fb`, and the only untracked paths were the M06 ADR and M06 directory. M05B closeout was committed at HEAD.
- **OBSERVED:** The six active M06 documents matched the corresponding pre-deployment backup files. The backup directory was not modified.
- **OBSERVED:** Current STT loading/readiness, TTS lifecycle, Ollama adapter/configuration, Gateway readiness and M05B selection code were inspected during the preceding architecture review; the accepted M05B closeout and qualification records were consulted.
- **INTERPRETATION:** The revised planning requirements assign native model lifecycle to each inference owner and keep Gateway orchestration bounded.
- **M06A baseline NOT ESTABLISHED:** M06 application behavior or tests at the architecture-finalization point, installed-target Ollama warmup compatibility, simultaneous model capacity, live GPU recovery or deployment behavior.

## M06A documentation checks (historical)

- **OBSERVED:** `git diff --check` exited 0. Git reports only tracked changes to `PLANS.md`; because the M06 planning documents are untracked, this command does not inspect their contents.
- **OBSERVED:** A read-only Python check over `PLANS.md`, ADR 0022 and all five M06 Markdown files found no trailing whitespace and found every relative Markdown link target on disk.
- **OBSERVED:** Manual cross-document review confirmed M06A–M06E stage names, M05B closeout state, readiness semantics, warmup statuses, timeout/resource requirements, routing restrictions, and approval gates agree across PLANS, ADR, plan and the four milestone records.
- **OBSERVED:** Final Git scope review showed one tracked modified file (`PLANS.md`) and the six pre-existing untracked M06 planning files. No application code, tests, API OpenAPI document, configuration, deployment file, backup file or private runtime state was changed.
- No application tests, API validators, service actions, container actions, inference, cloud calls or live GPU qualification were run.

## Initial M06B offline verification (historical; superseded below)

- `.venv/bin/python -m compileall -q services/stt` — PASS; no syntax errors.
- `.venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py'` — PASS; 74 tests passed, including STT configuration validation, supervisor/admission lifecycle, lazy startup and warmup, concurrent warmup/inference single initialization, idle unload/reload, idle timeout reset, readiness, HTTP warmup validation, caller timeout behavior, active/queued protection, confirmed load failure, cleanup uncertainty and shutdown during loading.
- `PYTHONPATH=. .venv/bin/python -m unittest services.stt.tests.test_runtime.ApplicationTests.test_model_load_timeout_with_unconfirmed_exit_reports_cleanup_unconfirmed -v` — PASS; confirms cleanup uncertainty latches readiness and prevents further loading.
- `PYTHONPATH=. .venv/bin/python -m unittest services.stt.tests.test_runtime.ApplicationTests.test_shutdown_drains_then_cancels_active_child_and_drops_queue -v` — PASS; confirms shutdown with active and queued fake inference.
- `go test ./internal/gateway` — PASS; existing Gateway readiness/proxy tests remain compatible with worker readiness semantics. No Gateway code was changed.
- `git diff --check` — PASS after the implementation changes.
- `.venv/bin/python -m ruff check services/stt && .venv/bin/python -m ruff format --check services/stt` — PASS; all checks passed and all 23 STT Python files are formatted.
- `.venv/bin/python -m compileall -q services/stt` — PASS.
- `.venv/bin/python -m services.stt.main --config configs/stt.yaml --application-config configs/stt-product-application.yaml --deployment-config configs/stt-product-deployment.yaml --check-config` — PASS; product STT configuration validates without initializing a model.

These checks use fake CPU workers and synthetic audio. They do not establish CUDA behavior, actual VRAM release, target-host idle timing, Gateway readiness integration, or live model performance. M06D still needs the broader offline integration/regression suite. No live inference, GPU experiment, provider request, image build, service restart, or deployment was run.

## M06B concurrency correction verification (OBSERVED 2026-10-23)

Environment: repository worktree on `main`, Python 3.12 virtual environment `.venv`, fake CPU workers and synthetic audio. No production services, GPU models, Docker build or network provider was used.

- `.venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py'` — PASS; 84 tests passed in 15.222 seconds after correcting a timing-sensitive shutdown assertion. The final `make verify` run below also passed the current 84-test STT suite in 15.205 seconds.
- `.venv/bin/python -m unittest services.stt.tests.test_http -v` — PASS; 14 HTTP tests passed, including missing/malformed timeout headers, body size, chunked-body rejection and bounded stalled-body validation.
- A targeted command running four concurrency regressions was repeated five times — PASS; 20 executions total, four tests per repetition. Python's multiprocessing `resource_tracker` emitted re-entrant cleanup warnings during repeated process tests; they did not cause test failures. Their impact on long-running processes is NOT ESTABLISHED.
- `go test ./internal/gateway` — PASS; existing Gateway readiness and proxy tests pass. No Gateway code changed.
- `.venv/bin/python -m services.stt.main --config configs/stt.yaml --application-config configs/stt-product-application.yaml --deployment-config configs/stt-product-deployment.yaml --check-config` — PASS.
- `.venv/bin/python -m ruff check services/stt` — PASS after lifecycle corrections.
- `.venv/bin/python -m ruff format --check services/stt` — PASS after lifecycle corrections; all 23 STT Python files are formatted.
- `.venv/bin/python -m compileall -q services/stt` — PASS after lifecycle corrections.
- `git diff --check` — PASS before the final documentation edits; rerun for final worktree validation.
- `make verify PYTHON=.venv/bin/python` — PASS; exit code 0. This ran lint/format checks across services and scripts, Gateway/STT/TTS configuration checks, Compose configuration rendering and static policy validation, release validation, `go test -race ./...`, 523 repository script tests, the 84-test STT suite, `go build ./...`, Python AST compilation, governance validation/tests, and STT/TTS lock checks. Compose commands rendered configuration only; no containers were started, images built, or services contacted.

The first full-suite run exposed a timing-sensitive shutdown assertion requiring exactly one `not_ready` result. The active request can validly end as `cancelled`, `deadline_exceeded` or `not_ready` at the shutdown boundary, while queued work is rejected; the test now verifies those allowed outcomes and the subsequent full suite passed. An initial raw HTTP stalled-body test was blocked by the client-side incomplete request body, so it was replaced with a deterministic test of the bounded request-stream validation helper used by the handler. This establishes helper deadline behavior, not end-to-end behavior under every HTTP server or proxy buffering configuration.

**NOT ESTABLISHED:** Native device-probe behavior under CUDA, whether native code allocates driver resources before returning, forced termination of a non-cooperative native call (Python cannot safely terminate it), production target timing/VRAM, and deployment health-probe behavior. If preflight exceeds its bound or remains alive at shutdown, the worker conservatively reports cleanup uncertainty and blocks reload; process restart/recovery remains an operator action.

## M06B ownership and shutdown correction verification (OBSERVED 2026-10-23)

Environment: repository worktree on `main`, Python 3.12 virtual environment `.venv`, fake CPU workers and synthetic audio. No production services, GPU models, Docker build or network provider was used.

- `PYTHONPATH=. .venv/bin/python -m unittest services.stt.tests.test_runtime.ApplicationTests.test_preflight_handoff_timeout_and_completion_have_one_owner services.stt.tests.test_runtime.ApplicationTests.test_shutdown_during_non_cooperative_inference_is_bounded_and_latched services.stt.tests.test_runtime.ApplicationTests.test_supervisor_shutdown_lock_wait_is_bounded -v` — PASS; 3 focused regression tests passed.
- `for run in 1 2 3 4 5; do PYTHONPATH=. .venv/bin/python -m unittest -q services.stt.tests.test_runtime.ApplicationTests.test_preflight_handoff_timeout_and_completion_have_one_owner services.stt.tests.test_runtime.ApplicationTests.test_shutdown_during_non_cooperative_inference_is_bounded_and_latched; done` — PASS; 10 test executions across five repetitions.
- `.venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py' -v` — PASS; 87 STT tests passed in 16.354 seconds.
- `go test ./internal/gateway` — PASS; existing Gateway readiness tests passed.
- `.venv/bin/python -m services.stt.main --config configs/stt.yaml --application-config configs/stt-product-application.yaml --deployment-config configs/stt-product-deployment.yaml --check-config` — PASS.
- `.venv/bin/python -m ruff check services/stt` and `.venv/bin/python -m ruff format --check services/stt` — PASS; all 23 STT Python files formatted.
- `.venv/bin/python -m compileall -q services/stt` — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS; exit code 0. The target completed repository lint/format, configuration and Compose rendering checks, `go test -race ./...`, script tests, the 87-test STT suite, `go build ./...`, AST compilation, governance validation/tests, and STT/TTS lock checks. Compose commands rendered configuration only; no containers were started, images built, or services contacted.
- `git diff --check` — PASS after final documentation edits.

The preflight handoff regression directly verifies that timeout-first transfers cleanup ownership and completion-first transfers ownership to the loader; a concurrent barrier race is repeated 25 times per test invocation. The blocked-inference regression holds an accepted operation past shutdown cancellation and verifies bounded return, no overlapping runner shutdown, false readiness, and a persistent cleanup-uncertain state after the fake call is released. A separate supervisor test verifies a bounded lock-acquisition timeout and no false child-exit claim.

**LIMITATION / NOT ESTABLISHED:** Python cannot safely terminate an arbitrary thread stuck in native inference or device discovery. In that condition SpeechPlatform returns from `close` within its derived configured deadline, leaves the model state cleanup-unconfirmed and readiness false, and does not call runner shutdown while inference owns it. The supervised child may remain alive until the operation returns or an operator recovers the worker process. This does not establish host/GPU cleanup for a non-cooperative production native call. CUDA, production timing/VRAM and live deployment behavior remain unqualified and outside M06B.

**Operator acceptance (user-reported 2026-10-23):** M06B implementation and the offline verification recorded above are accepted, with the stated limitation concerning non-cooperative native calls. This acceptance does not include M06D full integration verification, M06E live GPU qualification, deployment, or overall M06 completion.

## M06B closeout verification (OBSERVED 2026-10-23)

- `make verify PYTHON=.venv/bin/python` — PASS; exit code 0. The full repository target completed, including lint/format, configuration checks, Compose rendering/static policy checks, race-enabled Go tests, script tests, all 87 STT tests, Go build, Python AST compilation, governance checks, and dependency-lock checks. Compose commands rendered configuration only; no services were started or contacted and no images were built.
- `git diff --check` — PASS after the M06 acceptance/status record updates.
- **Scope review:** The commit contains only the 19 existing M06 planning, STT lifecycle, configuration-example, test, and milestone-record files. No private directory content, credentials, production inference data, TTS/Ollama runtime, Gateway routing, deployment runtime, or unrelated repository files are included. The pre-deployment backup remains untouched.

M06B implementation and offline verification acceptance is recorded above. M06C remains the next planned development stage. M06D integration verification and M06E live GPU qualification/deployment remain pending and separately gated.

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
