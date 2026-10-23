# ADR 0022: Model lifecycle, predictive warmup and readiness-aware routing

- Status: **Accepted architecture for M06 planning; implementation not authorized by this record**
- Date: 2026-10-23
- Scope: M06 lifecycle and warmup behavior for STT, TTS and local text transformation

## Context

The implementation has separate lifecycle owners. STT eagerly loads one Faster-Whisper model in its supervised child during application startup and retains that child until shutdown. TTS already loads VoxCPM2 lazily, serializes native use, supports internal warmup and unloads after a configured idle interval. Ollama owns local LLM residency through per-request `keep_alive`. M05B selection supports `ordered`, `local_first`, `cloud_first`, explicit model selection, `local_only`, global cloud authorization and configured typed fallback. It does not observe residency.

M05B closed with accepted limitations. It observed a 6,270 MiB minimum free sample during Qwen inference with STT resident; this is not a general capacity guarantee. TTS's current load guard requires 8,000 MiB free. Simultaneous Qwen inference and TTS cold loading remains unqualified. The tracked example config specifies `keep_alive: 0s`; accepted production evidence used finite `5s`. Neither fact proves the runtime behavior of a future warmup request.

The consumer need is to tell the platform which operations are likely while the client performs other work, such as recording. The platform must remain usable without warmup and must not generate user content as a side effect of preparing a model.

## Decision

1. **Lifecycle ownership:** Each inference owner manages its native model. STT retains its supervised child-process boundary and adds lazy load, internal warmup, active/admitted-use protection, configurable idle unload and reload. TTS retains its existing lifecycle. Ollama remains authoritative for LLM residency and receives a finite configured `keep_alive` for warmup and generation. No model-manager service is introduced.
2. **STT readiness:** `/healthz` means the STT process is alive. `/readyz` means it can accept bounded on-demand work, including while the model is intentionally unloaded or loading. Faulted workers that cannot safely process or start work, workers draining/stopped, and cleanup-unconfirmed states are not ready. Internal model state is separate from service readiness. Gateway readiness remains based on required worker service availability, not optional model residency. This is an intentional readiness-contract change; public inference request/response contracts remain unchanged.
3. **STT idle safety:** The model is unload-eligible only after the configured idle interval since its last completed model use, and only while no active operation or admitted pending/queued request requires it. Unload is serialized with load and inference lifecycle operations. Confirmed child exit/reaping is the reliable CUDA resource-release boundary. A timeout or uncertain child cleanup enters a fault/cleanup-unconfirmed state and is not reported as unloaded.
4. **Warmup contract:** M06C adds one authenticated public `POST /v1/models/warmup` accepting stable operation identifiers `stt`, `tts`, and `text_transform`. It is a bounded synchronous request; clients may invoke it asynchronously. It has no job ID, persistent job state or polling route. The plan defines the proposed schema and errors. Warmup only loads/prepares declared operations; it does not synthesize speech, produce transformation text, or transmit user audio/text. Cloud providers are never invoked for warmup.
5. **TTS reuse:** The Gateway calls TTS's existing private warmup endpoint. TTS keeps its current idle timeout, active-use protection, admission slot and VRAM guard. A competing request may receive 429; no promise is made that it joins an active HTTP inference.
6. **Ollama warmup:** Use the native empty request to `/api/generate` with configured model, `stream:false`, top-level `think:false` where supported, and nonzero finite `keep_alive`. Do not pass user content, use `keep_alive:0`, issue `ollama stop`, change shared Ollama configuration, or claim exclusive model ownership. The tracked example's `0s` and the historically qualified production `5s` are documented distinctly. M06C must use a finite configured warmup residency value; initial proposal is 60 seconds, subject to strict configuration validation. Installed-version compatibility is not established by documentation and must be checked in separately authorized qualification.
7. **Routing compatibility:** Do not add `on_local_warming` or `next_eligible` in M06. Cold and warming local models remain candidates according to current M05B policy. A cold/warming local model alone does not cause cloud fallback. Preserve candidate order, explicit selection, `local_only`, `allow_cloud`, and existing typed provider-failure behavior.
8. **GPU coordination:** Retain worker admission and free-memory guards. Avoid overlapping Gateway-initiated cold-load starts where a concrete implementation need is demonstrated; any Gateway-local semaphore is optional, process-local and not a VRAM reservation. Do not evict an active model, preempt inference, or add a general scheduler/resource manager. Insufficient resource outcomes are bounded and do not invalidate unrelated operations.
9. **Compatibility:** Existing inference routes continue to trigger loading on demand and work without a prior warmup. Public STT/TTS/text inference schemas and M05B text-selection semantics remain unchanged. Internal STT readiness changes as specified above; document this for health checks and deployment probes before implementation.

## STT lifecycle states and transitions

The worker state (serving/draining/stopped/failed) remains distinct from model state. M06B may use these model states:

| Model state | Meaning and allowed transitions |
|---|---|
| `unloaded` | No child model resident; worker may accept bounded on-demand work. First inference or warmup starts `loading`. |
| `loading` | One child initialization is in flight. Concurrent inference/warmup joins that attempt within its own deadline. Success becomes `ready`; a recoverable failure with confirmed cleanup returns to `unloaded`; fatal/uncertain failure becomes `faulted` or `cleanup_unconfirmed`. |
| `ready` | Child loaded and able to serve admitted work. After the configured idle interval and with no active/admitted use, transition to `unloading`; inference/warmup refreshes last-use time. |
| `unloading` | No new child use begins until unload/exit is resolved. Confirmed child exit becomes `unloaded`; a new request may then trigger one reload. Unconfirmed exit becomes `cleanup_unconfirmed`. |
| `faulted` | The worker cannot safely start or process model work. `/readyz` is 503. Recovery follows existing fault-latch/manual recovery rules unless the failure is explicitly classified recoverable with confirmed child cleanup. |
| `cleanup_unconfirmed` | Child termination/resource release is unknown. `/readyz` is 503; do not retry load or claim resources released. |

The idle timer is based on completed real model use, including a successful warmup. Timer expiry alone never unloads while a request is active, pending or queued. Accepted queued work keeps or reacquires the model before execution. State output must omit audio, transcripts, prompts, credentials and private paths.

## Proposed public warmup contract (M06C)

Request: `application/json`, strict object, maximum 4 KiB, no unknown fields. `operations` is required, contains 1–3 unique strings from `stt`, `tts`, `text_transform`; result ordering follows request ordering.

```json
{"operations":["stt","text_transform"]}
```

Response: HTTP 200 when the Gateway accepted and attempted the operation set, including partial per-operation failures. `complete` is true only when every requested operation returned `ready`.

```json
{
  "results": [
    {"operation":"stt","status":"ready"},
    {"operation":"text_transform","status":"resource_unavailable","code":"resource_unavailable"}
  ],
  "complete": false
}
```

Per-operation `status` values are `ready`, `warming`, `unavailable`, `resource_unavailable`, `overloaded`, `timed_out`, and `not_attempted`. `warming` is used only when the Gateway can confirm the same operation remains in flight at the caller's bounded deadline. `timed_out` means completion may be unknown; it does not mean the worker/provider canceled loading or released memory. If the total deadline expires before a later operation starts, that result is `not_attempted` with `code: deadline_exceeded`. Continue after per-operation failures while total time remains. Stable optional `code` values explain the category without raw upstream details. A client disconnect cancels its wait when possible; it does not authorize forced worker termination or an unload request.

Common request errors use the Gateway's existing error envelope: 400 for malformed JSON, unknown fields/operations, empty list or duplicate operation; 401 when configured bearer authentication fails; 405 for non-POST; 408 when reading the request body exceeds the bounded warmup request deadline (the body was not validated and no upstream operation begins); 413 above the body limit; 415 for non-JSON content; 503 when the Gateway is stopping or cannot attempt any requested operation. Individual operation failures remain in the HTTP 200 results so successful operations are retained. Results never expose model/provider identifiers, endpoint URLs, credentials, paths, or provider bodies.

`text_transform` prepares the first enabled, cloud-authorized local candidate in the existing resolved order, without changing inference order. If none is eligible, return `unavailable`. The Ollama request has no `prompt`, `system`, audio, transcript or user text. It sets `stream:false`, finite nonzero `keep_alive`, and top-level `think:false` where supported. It relies on Ollama's documented empty-request preload behavior; response handling must discard generated content defensively and later runtime qualification must confirm the installed version does not generate user-facing output.

Repeated requests are safe. Concurrent requests for the same target join one in-flight load where the owning worker/runtime permits it; otherwise they wait within the request deadline or return `overloaded`/`timed_out`. Different operations are processed sequentially within one request to avoid avoidable overlapping cold-load starts. The ordinary inference path remains independent of prior warmup.

## Alternatives rejected or deferred

- **Generic model manager, database, distributed lock, job queue, polling API:** duplicates ownership and adds state not needed for this single-host bounded workflow.
- **General GPU scheduler/reservation and forced eviction:** unsupported by current evidence; process-local coordination cannot reserve shared GPU memory and eviction could disrupt active work.
- **Gateway-managed TTS lifecycle:** duplicates an existing tested owner; reuse TTS warmup/state.
- **Automatic cloud fallback for local cold/warming:** changes privacy, cost and ordering semantics; explicitly deferred and forbidden as a consequence of warmup state alone.
- **`on_local_warming` / `next_eligible`:** deferred; does not enable the warmup requirement and creates extra policy states.
- **Cloud model warmup, generated dummy content, client-specific warmup route, platform client implementation:** excluded from M06.
- **Dedicated Ollama service as an M06 prerequisite:** rejected for current implementation. Preserve shared service; require operator choice between a dedicated endpoint and acceptance of documented shared-server eviction risk before live qualification.

## Consequences and remaining qualification limits

STT startup becomes faster and readiness semantics change, while the first STT inference may incur model load latency. TTS lifecycle remains stable. Gateway adds one small orchestration route. A process-local semaphore, if later justified, coordinates only local request initiation and is not a resource guarantee. Ollama may load, expire or evict models under its own rules; `/api/ps` is observational and does not reserve memory. Historical GPU samples are not capacity guarantees. Live GPU behavior, installed Ollama warmup compatibility and the shared-server impact remain unestablished until the separately authorized M06E qualification.

## References

- [M06 plan](../milestones/M06/plan.md)
- [ADR 0007 — STT execution lifecycle](0007-stt-execution-lifecycle.md)
- [ADR 0019 — STT active cancellation](0019-stt-active-cancellation.md)
- [ADR 0020 — TTS lifecycle](0020-voxcpm2-tts-integration.md)
- [ADR 0021 — M05B provider selection](0021-configurable-text-transformation.md)
- [Ollama Generate API](https://docs.ollama.com/api/generate), [Ollama FAQ: preload and residency](https://docs.ollama.com/faq), [Ollama running models API](https://docs.ollama.com/api/ps)
