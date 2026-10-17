# Worker network reachability

Status: accepted for the M02 design; implementation authorization remains separate.

## Context

The M01 Compose file places Gateway, STT and TTS on one internal network. No worker ports are published, but any container attached to that network can address both worker ports. The internal STT contract wording says access is limited to a private worker network; this does not by itself mean only the Gateway can connect.

## Decision

Use separate internal Compose networks: `stt_private` shared only by Gateway and STT, and `tts_private` shared only by Gateway and TTS. Keep the Gateway as the only host-published service. Do not attach STT and TTS to a common network. Compose configuration expresses this topology; M02 implementation and deployment still require separate approval.

## Consequences

Compose configuration statically expresses that STT and TTS are not attached to each other's networks and that workers have no published host ports. `internal: true` networks restrict external routing from those networks. Gateway is intentionally dual-homed and can address both workers; compromise of Gateway therefore exposes both worker protocols to an attacker controlling it. This is reachability control, not cryptographic authentication or authorization.

The isolation does not protect against host root, Docker daemon administrators, a compromised Docker runtime, or kernel vulnerabilities. It does not prevent a host administrator from attaching containers to a network, inspecting traffic, or changing the Compose project. It does not isolate CPU, RAM, disk or GPU resources; workers still share the host and GPU with Ollama and Dify. Ollama and Dify are not attached to these networks, and their networking is outside this project. The topology is a static configuration claim until the separately authorized deployment is actually inspected.

## Alternatives

Keep one internal network and rely on no direct code dependency; simpler, but permits lateral container access. Add per-worker credentials/mTLS; stronger against network peers but expands key management and authentication scope. M02 uses network segmentation and does not add worker credentials; revisit authentication if the threat model or deployment exposure changes.
