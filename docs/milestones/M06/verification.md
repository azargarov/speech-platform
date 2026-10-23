# M06 verification plan and evidence

Status: **M06 COMPLETE; M06A–M06E accepted 2026-10-23 with the limitations recorded below.**

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

M06B implementation and offline verification acceptance is recorded above. This historical closeout entry predates M06C operator acceptance; M06D integration verification and M06E live GPU qualification/deployment were then pending and separately gated.

## M06C implementation and focused offline verification (OBSERVED 2026-10-23)

Environment: branch `main`, HEAD `820ce204ee9ac86b52a8affc175144b75809dcac` before the M06C changes. Tests used fake worker HTTP servers and a local HTTP test server for the Ollama protocol. No production worker, Ollama service, cloud provider, GPU model, container start, image build, deployment, or service restart was used.

- `go test ./internal/gateway ./internal/texttransform ./internal/config` — PASS during focused implementation; public request handling, local Ollama adapter and validated configuration packages passed.
- `go test -race ./internal/gateway ./internal/texttransform ./internal/config` — PASS after adding a deterministic stalled-body deadline test. An earlier race-enabled run identified a data race between the timeout callback and replacement of `r.Body`; the callback now captures the size-limited body after it is installed. The corrected race-enabled run passed.
- `.venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py'` — PASS; 87 existing M06B STT regression tests passed. No STT implementation was changed in M06C.
- `.venv/bin/python -m unittest scripts.test_acceptance -v` — PASS; 6 tests passed, including validation of all OpenAPI documents.
- `.venv/bin/python -m unittest scripts.test_service_deployment_profile -v` — PASS; 7 tests passed, including the new `warmup_timeout` allowlist/range/write-timeout check.
- `make verify PYTHON=.venv/bin/python` — first run **FAILED** because the canonical deployment-profile validator rejected the newly configured `warmup_timeout`. The validator and its test were updated to accept and bound the field. The final full run **PASSED**: lint and format (109 files), Gateway/STT/TTS config checks, Compose configuration rendering/static checks, release validation, `go test -race ./...`, repository script tests (524 tests), all 87 STT tests, `go build ./...`, Python AST compilation, governance checks/tests, and STT/TTS lock checks. Compose commands rendered config only; they did not start services or build images.
- `git diff --check` — PASS after the final code and documentation changes.

Focused Gateway regressions exercise strict/duplicate/unknown JSON handling before worker calls, authentication, content type and both declared/chunked body size limits, stalled-body timeout before side effects, STT timeout-header propagation and response validation, TTS success/unavailable/timeout/429 behavior, ordered partial outcomes, same-operation singleflight/`warming`, request deadline exhaustion, and response sanitization. Text-transform tests inspect the native warmup request for the configured local model, empty user-content fields, top-level `think:false`, `stream:false`, finite `keep_alive`, discarded generated output, provider failure and timeout; disabling the only local model returns unavailable without selecting cloud. Config tests cover the 180-second Gateway and 60-second Ollama warmup defaults and invalid bounds. Offline tests establish the request shape against a fake server only.

**NOT ESTABLISHED:** Installed Ollama version behavior for empty-prompt warmup; real Ollama model loading, model residency/expiry, resource pressure or interaction with external Ollama clients; target GPU coexistence or VRAM recovery; real STT/TTS worker integration under deployment networking; client behavior during actual connection loss. Those require M06D integration/regression qualification and separately authorized M06E target qualification. At this historical evidence point M06C had not yet been operator-accepted; acceptance is recorded after the correction evidence below.

## M06C concurrency and Ollama response corrections (OBSERVED 2026-10-23)

- `go test -race ./internal/gateway ./internal/texttransform -run 'Warmup' -count=1 -v -timeout=40s` — PASS. Gateway warmup tests cover the original owner cancelling while two followers remain, shorter owner deadline versus longer follower, follower cancellation, all callers leaving while the shared attempt remains owned, bounded attempt deadline, Gateway shutdown cancellation, shared final result, and distinct-operation serialization through upstream return. Ollama tests cover completed response, empty/malformed/truncated JSON, missing/false `done`, provider error under 2xx, oversized body, non-2xx, timeout and cancellation. Provider details remain sanitized.
- `go test -race ./internal/gateway -run 'TestWarmup(InitiatorCancellation|ShortDeadline|AllCallers|AttemptDeadline|DistinctOperations)' -count=30 -timeout=60s` — PASS; all selected boundary-race tests passed 30 repetitions.
- `go test ./internal/gateway ./internal/texttransform ./internal/config` — PASS.
- `go test -race ./internal/gateway ./internal/texttransform ./internal/config` — PASS.
- `.venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py'` — PASS; 87 tests.
- `.venv/bin/python -m unittest scripts.test_acceptance -v` — PASS; 6 tests, including validation of every OpenAPI document. The public route's 408 request-body deadline is now specified consistently in implementation, OpenAPI and ADR-0022; it means the body was not validated and no upstream operation began.
- `make verify PYTHON=.venv/bin/python` — PASS. This runs Go vet, Ruff lint/format, config checks, Compose rendering/static validation only, release validation, `go test -race ./...`, repository script tests, the STT unit suite, Go build, Python AST compilation, governance and lock validation. No service was started, image built, or deployment performed.
- `git diff --check` — PASS.

An initial focused run caught the changed caller-deadline outcome (`warming` while the shared attempt remains active) and a fake-server teardown that needed an explicit release path. Both test issues were corrected; the final focused commands above pass. These checks establish coordinator context ownership and response validation against deterministic fakes, not installed Ollama behavior, native cancellation, or GPU coexistence.

**Operator acceptance (user-reported 2026-10-23):** M06C offline implementation and verification are accepted, including documented limitations concerning shared GPU resources, native model-loading cancellation and unqualified installed Ollama behavior. This acceptance does not include M06D integration/regression qualification, M06E live GPU qualification, deployment, or overall M06 completion. M06E and deployment remain separately gated.

## M06D offline integration and regression verification (OBSERVED; accepted 2026-10-23)

M06D builds on accepted M06B lifecycle tests and M06C Gateway/adapter tests. It adds real Gateway handler integration against local fake STT/TTS/Ollama HTTP servers and worker HTTP paths with fake model backends. No production services, installed Ollama, CUDA model, cloud provider, container start, image build, deployment or service restart were used.

- `go test -race ./...` — PASS; all Go packages passed under the race detector, including the M06 public Gateway integration test and warmup, text-transform and configuration regression suites.
- `PYTHONPATH=. .venv/bin/python -m unittest discover -s services/stt/tests -p 'test_*.py' -v` — PASS; 89 tests. Includes new real STT HTTP application integration using the supervised fake child and synthetic audio: unloaded ready state, internal warmup, two transcriptions sharing the loaded child, and ready state after use. A separate case proves first inference loads without prior warmup. Existing deterministic lifecycle concurrency/failure tests also passed.
- `PYTHONPATH=. .venv/bin/python -m unittest discover -s services/tts/tests -p 'test_*.py'` — PASS; 24 tests. Includes worker HTTP tests using the actual TTS lifecycle and handler with fake model factories, exercising cold synthesis, warmup, model reuse and synthesis, plus simulated insufficient VRAM mapping to a bounded 503 resource failure. The admission regression verifies an active synthesis causes both another synthesis and a competing warmup to return 429 without a warmup call.
- `go test ./internal/gateway -run TestM06WarmupAndInferenceIntegrationAcrossAllBackends -count=1 -v` — PASS. The end-to-end handler test checks text inference before warmup; six public operation groupings (STT, TTS, text transform individually, STT+text transform, STT+TTS, all three) with ordered ready outcomes; then STT/TTS/local text inference. Fakes assert internal auth forwarding, STT timeout metadata, empty warmup request, no prompt/system on Ollama warmup, configured local model, finite separate warmup residency and normal inference `keep_alive` unchanged.
- `PYTHONPATH=. .venv/bin/python -m unittest services.stt.tests.test_runtime.M06HTTPIntegrationTests.test_internal_warmup_then_transcription_uses_same_model_child -v` — PASS; focused STT HTTP integration test.
- `PYTHONPATH=. .venv/bin/python -m unittest services.tts.tests.test_tts.WorkerHTTPTests.test_warmup_and_http_synthesis_share_fake_model_lifecycle services.tts.tests.test_tts.WorkerHTTPTests.test_http_warmup_reports_simulated_insufficient_vram_safely services.tts.tests.test_tts.WorkerHTTPTests.test_worker_admission_is_single_slot -v` — PASS; focused TTS warmup/inference, resource failure and active-slot tests.
- `go test ./internal/gateway -run 'TestM06WarmupAndInferenceIntegrationAcrossAllBackends|TestPublicWarmup|TestWarmup' -count=1` — PASS; integration and Gateway warmup API regressions passed.
- `.venv/bin/python -m unittest scripts.test_acceptance -v` — PASS; 6 tests, including OpenAPI validation, Compose isolation and worker API contract checks.
- `make verify PYTHON=.venv/bin/python` — an initial run FAILED only because Ruff reported formatting needed in the newly changed Python test files. After formatting, subsequent runs PASSed with exit code 0. The final run completed Go vet, Ruff lint/format, Gateway/STT/TTS config checks, Compose render/static checks, release validation, `go test -race ./...`, 524 repository script tests, 89 STT tests, Go build, Python AST compilation, governance validation/tests (2 tests), and dependency lock checks. Compose commands rendered configuration only; no containers were started and no images were built.
- `git diff --check` — PASS after documentation and test changes.

The full Gateway integration exercises three fake upstreams in deterministic operation order and normal inference across all three routes. Existing tests additionally cover validation/auth/no-side-effects, request size and stalled bodies, overload/partial outcomes, same-operation shared attempts with independent deadlines/cancellation, Gateway shutdown, distinct-operation serialization, Ollama malformed/incomplete/provider-error/oversized/timeout cases, selection policies and typed fallback. The existing STT suite exercises zero-timeout unload, active/queued/pending/upload protection, lifecycle reload, failed cleanup, and ready/not-ready states. The TTS suite exercises lazy lifecycle, idle unload, active inference protection, recovery and worker admission.

No application/runtime correction was revealed as necessary. The added test code was adjusted for the existing STT startup facade and test-only byte limits; neither indicates a product defect. No routing behavior or API contract changed.

**NOT ESTABLISHED for M06E:** actual GPU memory coexistence or sufficiency, native model load/unload latency or cancellation, actual CUDA cleanup, deployed Docker network behavior, behavior/residency of the installed Ollama version, production readiness timing, and real multi-client shared Ollama impact. Fake resource outcomes are not capacity evidence. These remain outside the offline evidence and require separate explicit operator authorization.

**Operator acceptance (user-reported 2026-10-23):** M06D offline integration and regression qualification is accepted based on the evidence recorded above. This acceptance is limited to the offline test scope. It does not establish real GPU capacity, native CUDA load/unload or cancellation behavior, installed Ollama compatibility or residency, shared Ollama ownership safety, or production networking. M06E live GPU qualification and production deployment each remain pending separate explicit authorization.

### M06D coverage retained from the approved plan

The accepted M06B/M06C suites plus M06D integration checks cover:

- STT lazy startup, first inference, internal warmup, concurrent load singleflight, initialization deadline and confirmed failure recovery.
- Idle timer reset after model use; unload only after idle timeout and zero active/admitted pending/queued use; unload/reap/reload races; no duplicate child.
- `/healthz` liveness and `/readyz` availability while unloaded/loading; not-ready fault, drain and cleanup-unconfirmed cases; Gateway readiness stability.
- Public warmup auth, JSON content type/body bound, unknown/duplicate/empty operation handling and full validation before side effects.
- Per-operation ready/partial/unavailable/resource/overloaded/timed-out results, caller disconnect, repeat/concurrent requests, overall deadline, shutdown and no false cancellation or release claims.
- No audio, transcript, prompt or user text in warmup; no synthesis or user-facing LLM output; no cloud provider invocation.
- Ollama warmup serialization: empty request, configured model, `stream:false`, top-level `think:false`, finite nonzero keep-alive and no unload request.
- TTS endpoint reuse and its existing 429/admission/active-use/idle safeguards, plus simulated resource-exhausted error mapping.
- M05B ordering, explicit selection, `local_only`, `allow_cloud`, typed failure fallback and inference without prior warmup.
- Strict configuration, public/private API contracts, shutdown, scoped regression suites and full verification required by the authorized implementation scope.

## M06E live qualification

Live qualification and scoped deployment were authorized and performed on 2026-10-23. The operator accepted M06E and M06 overall on 2026-10-23 based on the bounded evidence below.

## M06E deployment and live qualification (OBSERVED; accepted 2026-10-23)

**Initial state:** branch `main`, clean at accepted HEAD `73cd0ccd185be48e634134263db4b90547a83d28`. Existing Gateway/STT/TTS and separate Ollama identities were inspected before replacement. No unrelated container/network/volume changes were made; Ollama stayed running and cloud remained disabled.

**Deployment:** `make verify PYTHON=.venv/bin/python` passed before deployment. Active root Compose rendered with the absolute private Gateway config, and Gateway/STT config validators passed. `make plan PYTHON=.venv/bin/python` first could not read the root-owned model store under the current login; the read-only plan passed using the existing `stt-model-reader` group (`sg stt-model-reader -c ...`). Candidate Gateway and STT images were built from accepted HEAD. STT was recreated service-scoped, and Gateway was recreated through `make install SERVICE=gateway`; TTS was retained. Gateway-only install used canonical readiness/revision checks and preserved the existing Ollama network attachment.

- Gateway container `f153da3718f8c857f61be21c7538f6336e4e17d961e7a00ecb29a299929bff71`; image `sha256:8d4317c229849d40582042a93858ae4dc906de74932cc7fdc1f79b597ddbcfb7`; revision `73cd0ccd185be48e634134263db4b90547a83d28`.
- STT container `e35f5df729c84295e44bf9777ceb761e5fdcf7d0668c3f6df92e20987858e7db`; image `sha256:506a7bc42906ab2d12845f88e399059a2b08e32000b8b339149435dc1a047381`; revision `73cd0ccd185be48e634134263db4b90547a83d28`.
- TTS remained container `cbda986a4e9ace938023a8ccdb571d4169b2855814970ccab7dd49c82cd19569`; image `sha256:0e39b7bfba33cc2a8ba6bbb459fad3fbd2c827fa51e9b2d774787517678e4c2d`; tag `m03b-high-quality-20261022`.
- Ollama container was not changed. Final Gateway `/healthz` and `/readyz`, STT `/healthz` and `/readyz`, and TTS `/healthz` returned HTTP 200. Gateway/STT/TTS restart counts were zero after qualification.

**STT live observations:**

- Initial GPU baseline: 2,216 MiB used, 12,694 MiB free; RTX 5000, 15,360 MiB.
- STT started unloaded while health and readiness were available. Internal warmup returned `{"model_state":"ready"}` in 3.655 s. Resident sample was 2,074 MiB used / 12,836 MiB free.
- Public warmup while resident returned ready in 72 ms. Synthetic speech transcription succeeded twice: first 0.841 s and repeat 0.265 s. GPU sample during use reached 2,280 MiB used / 12,630 MiB free.
- After at least 60 seconds idle, logs showed `ready → unloading → unloaded`; supervised child exited 0 and was absent from the process list. GPU fell to 4 MiB used / 14,906 MiB free. Readiness remained HTTP 200.
- Inference without preceding warmup then cold-reloaded and succeeded in 4.048 s; repeat took 0.282 s. STT was again idle-unloaded before final baseline sampling.

**TTS live observations and compatibility issue:**

- Existing worker uses the prior `m03b-high-quality-20261022` image and `/config/tts.yaml` from `private/m04/live-20261022/rollback-tts.yaml`. Its state endpoint reported unloaded, its existing internal warmup returned loaded after 68.21 s, and GPU reached about 5,264 MiB used / 10,096 MiB free. The model later unloaded after its idle period.
- Initial deployment's public TTS warmup returned `unavailable/invalid_worker_response`: TTS responds with `model_state:"loaded"` and `inference_active:false`, unlike STT's `ready`. The committed correction validates the TTS response and maps it to public `ready`. The retained image rejected the default `input_format:"text"`; the committed compatibility correction omits that default while preserving explicit SSML.
- Current source TTS config validation rejects the deployed legacy config because it lacks fields required by the current schema; no TTS config or image was changed. Updating TTS requires a compatible config/image path and is not silently assumed.

**Ollama and contention:**

- Installed Ollama 0.33.1 accepted public empty-prompt `text_transform` warmup with HTTP 200/ready in 8.759 s. `ollama ps` showed `qwen3.5:9b-q4_K_M`, 100% GPU, 6.1 GB, with about 60 seconds residency remaining. A synthetic normal transformation returned HTTP 200, provider `host-ollama`, model `local-qwen`, `fallback_occurred:false`, in 10.260 s. Public warmup followed by normal local transformation worked on the installed version.
- Combined public STT+text-transform warmup completed in 16.425 s. GPU reached 9,102 MiB used / 5,808 MiB free. With STT and Qwen resident, TTS warmup returned per-operation `resource_unavailable` in 0.298 s; TTS stayed unloaded and GPU use did not increase. No model was forcibly evicted.
- Ollama naturally expired its model: `ollama ps` became empty and GPU use returned from 9,102 MiB to 174 MiB (14,736 MiB free). STT readiness remained HTTP 200; TTS remained unloaded. Final sample: 174 MiB used, 14,736 MiB free, 0% utilization, 37 C.

**Corrected deployment and final requalification:** the operator authorized correction commit `f2f2d337271d5ed677daf13a8c5fcd875d68000a`. Canonical Gateway installation built and deployed Gateway only. Final Gateway image ID is `sha256:abbbe810b130c532f5931c28ad749654047217f777af22f6a435a33dc09690ba`, revision label `f2f2d337271d5ed677daf13a8c5fcd875d68000a`, container `255e6a6c2bd77d3064ff29974cbaa5f9e0785dabe38ced799d1003b38f19086c`. STT/TTS were not recreated in this follow-up. Public TTS warmup returned HTTP 200/ready in 58.527 s; public synthetic plain-text synthesis returned HTTP 200 with valid WAV (291,884 bytes) in 5.413 s. Public STT warmup returned ready in 3.422 s while TTS was resident. After both workers unloaded, public text-transform warmup returned ready in 10.363 s. Final health probes: Gateway `/healthz` and `/readyz`, STT `/healthz` and `/readyz`, and TTS `/healthz` all HTTP 200; restart counts were zero. Cloud-disabled configuration remained unchanged.

Final deployed identities at closeout: STT container `e35f5df729c84295e44bf9777ceb761e5fdcf7d0668c3f6df92e20987858e7db`, image `sha256:506a7bc42906ab2d12845f88e399059a2b08e32000b8b339149435dc1a047381`, source revision `73cd0ccd185be48e634134263db4b90547a83d28`; TTS container `cbda986a4e9ace938023a8ccdb571d4169b2855814970ccab7dd49c82cd19569`, image `sha256:0e39b7bfba33cc2a8ba6bbb459fad3fbd2c827fa51e9b2d774787517678e4c2d`, retained tag/revision `m03b-high-quality-20261022`; separately managed Ollama container `72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba`, image `sha256:075246f72d4109385b4a01c3ac8e9cbd26a0bcb21cd7aa30edbccd24e1b3180c`, installed version 0.33.1. No Ollama configuration, network, image, or container was changed.

**Final offline verification:** `make verify PYTHON=.venv/bin/python` — PASS, exit 0 after the Gateway correction; included Go vet, Ruff lint/format, config/Compose checks, race-enabled Go suites, 89 STT tests, Go build, Python AST compilation, governance and lock checks. `git diff --check` — PASS for the M06 closeout documentation.

**Accepted limitations / not established:** explicit SSML was not live-qualified; tested GPU coexistence does not establish capacity for untested workloads; Ollama remains shared and is not exclusively controlled by SpeechPlatform; non-cooperative native calls require conservative cleanup and may require operator recovery; installed model residency is not guaranteed beyond observed conditions; effects on external Ollama clients were not established. Existing text-transformation routing and cloud authorization remain unchanged; no fallback policy was added for cold or warming local models. The operator accepted these limitations on 2026-10-23. M06 is accepted complete within the recorded scope.
