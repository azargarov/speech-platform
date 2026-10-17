# Architecture principles

These principles constrain design decisions; the [methodology](../development/methodology.md) defines the evidence and review process. Existing design is recorded in [overview.md](overview.md) and [ADRs](../adr/).

| Principle | Design consequence |
| --- | --- |
| Application independence | VoiceHub, Chess Tutor, Drawing Tutor and agents are consumers. Consumer workflows and business rules stay outside Speech Platform. |
| Component separation | Gateway owns public authentication, validation and routing. Independent STT/TTS workers own inference and model lifecycle. Workers have no direct dependency on each other. |
| Provider replaceability | Map stable platform aliases to configured providers internally. Engine-specific parameters and identifiers do not leak into public contracts. Add an adapter when a concrete provider needs one. |
| Contract-first APIs | Specify public and internal contracts separately before implementation. Version explicitly, use consistent errors and preserve compatibility unless the user approves a change. Capabilities describe supported behavior truthfully. |
| Configuration-driven deployment | Validate configuration strictly. Keep addresses, paths, ports, models, timeouts and limits out of application logic. Start with one host and Compose; keep network boundaries explicit so future host placement does not change business logic. Do not add distributed orchestration now. |
| Privacy by default | Keep audio transient, logs free of audio/transcripts and secrets, workers private and temporary-data cleanup explicit. Provision models separately from restricted runtime networking. |
| Observability | Use structured operational events and Prometheus-compatible metrics without sensitive labels. Liveness means the process responds; readiness means it can serve its intended work. Instrument latency, errors and capacity as functionality arrives. |
| Failure isolation | Propagate deadlines and cancellation; bound input, concurrency and queues. Worker failures must not imply failure of unrelated services. Describe unavailable capabilities explicitly and plan recovery. |
| Resource awareness | Account for the initial RTX 5000 16 GB GPU, 64 GB RAM and shared host. Measure before tuning; distinguish observed workloads from guarantees. Make limits configurable and avoid optimizing hypothetical scale. |

Separate application use cases from HTTP, model libraries and container details. Prefer small explicit dependencies and introduce interfaces only where they make a real boundary substitutable or testable. Future multiple-host deployment is a design constraint on contracts and configuration, not authorization to implement scheduling, service discovery or distributed state.
