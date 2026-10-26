# ADR 0025: Modular deployment and optional speech services

- Status: Proposed; implementation and offline verification authorized, awaiting user review
- Scope: Gateway configuration, readiness, Compose service selection, installer preflight and qualification diagnostics
- Extends: [ADR 0018 — Git + Compose product operations](0018-git-compose-product-operations.md), [ADR 0023 — installation preflight](0023-installation-preflight-and-release-path.md), [ADR 0024 — optional Groq STT](0024-optional-groq-stt.md)

## Context

The supported installer and Gateway previously required STT and TTS together. Gateway YAML required both worker URLs, Compose declared both workers as required healthy dependencies, readiness checked both, and preflight/install always checked and deployed the full worker set. This prevented Gateway-only, STT-only and TTS-only deployments even though the public routes and worker lifecycles are independent.

Text transformation already has its own strict `text_transform.enabled`, model enablement, locality and cloud-policy settings. It does not need a second provider configuration system. Deployment configuration must remain separate from consumer business logic, and shared Ollama remains externally owned.

## Decision

- Add `capabilities.stt` and `capabilities.tts` to Gateway configuration. Each is an optional boolean; omission defaults to enabled for compatibility. Only enabled local worker capabilities require their URL, timeout, model artifact, GPU settings, health checks and deployment service.
- Keep optional Groq STT independent of the local STT worker. Explicit Groq requests still require cloud-audio consent. A disabled route returns HTTP 503 `capability_disabled`; an enabled cloud provider without usable credentials returns `provider_unavailable` before provider dispatch.
- Gateway readiness probes only configured local workers. With no local speech worker selected, Gateway readiness checks Gateway operation alone. It remains strict for every enabled worker.
- Give STT and TTS separate Compose profiles, remove hard Compose dependencies from Gateway, and require the installer to name selected services explicitly. Worker images are started and health-checked before Gateway. The default selection remains the full stack.
- Reuse `COMPONENTS=gateway[,stt][,tts]` in Make and preflight. Component selection controls which services are built and recreated; Gateway capability flags independently control which operations are enabled. Preflight scopes artifact, GPU, schema and Compose-profile checks to selected services. An enabled but unselected worker must already be a healthy, owned, compatible service; a disabled worker is not required. Installation builds, retains, verifies, probes, starts and checks only selected services.
- Keep the existing exact-image retention and manual rollback procedure. Retain image IDs only for selected services; rollback selects the same service subset against a compatible private configuration snapshot.
- Extend qualification reports with `capability_state`: `available`, `disabled`, `configured_but_unavailable`, `failing_during_execution`, or `not_established`. Derive it from the actual operation response without adding a provider health framework or making inference requests.

## Alternatives considered

- A second deployment descriptor or provider abstraction was rejected. Existing validated Gateway YAML and Make/Compose selection can express the required capability set.
- Treating every missing worker as a healthy fake or silently falling back was rejected because it would hide configuration errors and alter routing semantics.
- Automatically probing cloud providers during readiness/preflight was rejected because it cannot establish readiness without external requests and may create paid or privacy-sensitive inference. Credentials remain optional; actual provider errors stay explicit.
- A generic orchestration or service lifecycle manager was rejected. Compose profiles and explicit service targets are sufficient for the current one-host deployment.

## Consequences

Existing Gateway YAML without capability flags remains a full-capability configuration. Operators may update Gateway alone while retaining enabled healthy workers, or include only workers that need updating. If an enabled worker is absent or incompatible, preflight directs operators to include it in the deployment or repair it first. Cloud authorization is unchanged. Disabled routes remain authenticated. Deployment tests prove unselected workers are not built, started or retained, and full-stack ordering/readiness remain covered.

The worker process lifecycle is unchanged. Independent multi-host deployment, remote provider health probes, and optional worker-management UX beyond existing Make/Compose tools remain outside this decision.
