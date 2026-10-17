# STT immutable artifacts, device policy and configuration

Status: accepted for M02 design; implementation authorization remains separate.

## Context

The first adapter targets faster-whisper `large-v3-turbo` on CUDA, with a CPU-only profile required for portability. Model names, local file paths, device IDs and precision are different concerns. M00 identifies neither exact converted artifact nor complete runtime dependency set.

## Decision

Use strict versioned application configuration separately from deployment configuration. Preserve exact M01 health-only config behavior. A stable alias resolves to a logical model family and pinned immutable upstream revision. Backend selection, verified converted artifact identity and execution device are separate values. Each backend may reference its own converted artifact for the same logical model identity. The digest-pinned manifest has normalized relative paths and per-file sizes/digests; configured mount paths stay outside manifest metadata. Fail before load on any mismatch.

Device discovery is adapter-owned. Initial `llm` deployment explicitly selects CUDA and fails closed without CPU fallback. A separate CPU profile uses the same faster-whisper adapter and omits CUDA/NVIDIA dependencies. Portable auto selection uses a deterministic configured order during startup only. There is no runtime device switching, OOM retry, model eviction or GPU reservation.

Pin the complete resolved Python dependency graph and image digest. Validate faster-whisper, CTranslate2, CUDA, cuBLAS and cuDNN as a versioned combination. M00 faster-whisper 1.2.1 is only a candidate; it is not a verified runtime pin. Provision models offline and deny runtime model downloads.

## Consequences

Logical model identity is reproducible independently of converted artifact and container path. CPU tests can exercise the application without NVIDIA tools. GPU free-memory checks remain time-sensitive admission hints. Dependency compatibility and memory must be measured on authorized target hardware.

## Alternatives

Using a mutable model alias such as a moving branch is not reproducible. Putting a device path or backend model identifier in the public API couples consumers to deployment. Automatic fallback after a CUDA OOM hides resource faults and may make latency unpredictable. These are rejected.
