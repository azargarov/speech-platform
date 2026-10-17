# STT immutable artifacts, device policy and configuration

Status: accepted for M02 design; implementation authorization remains separate.

## Context

The first adapter targets faster-whisper `large-v3-turbo` on CUDA, with a CPU-only profile required for portability. Model names, local file paths, device IDs and precision are different concerns. M00 identifies neither exact converted artifact nor complete runtime dependency set.

## Decision

Use strict versioned application configuration separately from deployment configuration. Preserve exact M01 health-only config behavior. A stable alias resolves to a logical model family and pinned immutable upstream revision. Backend selection, verified converted artifact identity and execution device are separate values. Each backend may reference its own converted artifact for the same logical model identity. The digest-pinned manifest has normalized relative paths and per-file sizes/digests; configured mount paths stay outside manifest metadata. Fail before load on any mismatch.

Device discovery is adapter-owned. Initial `llm` deployment explicitly selects CUDA and fails closed without CPU fallback. A separate CPU profile uses the same faster-whisper adapter and omits CUDA/NVIDIA dependencies. Portable auto selection uses a deterministic configured order during startup only. There is no runtime device switching, OOM retry, model eviction or GPU reservation.

Pin the complete resolved Python dependency graph and image digest. The approved M02-B CUDA dependency policy explicitly pins faster-whisper 1.2.1, CTranslate2 4.8.3, cuBLAS 12.9.2.10 and cuDNN 9.27.0.42; CUDA NVRTC 12.9.86 is resolved transitively. Keep CPU and CUDA lock sets separate. CTranslate2 4.8.3's versioned changelog establishes Python wheel support for cuDNN 9 and says cuDNN 8 is no longer supported; this takes precedence over the conflicting cuDNN 8 note in its `CONTRIBUTING.md`. CTranslate2's Python wheel notes describe CUDA Runtime as statically linked, so a separately loadable `libcudart.so.12` is not a required package-level assertion. This dependency policy does not establish inference compatibility on a target GPU. Provision models offline and deny runtime model downloads. See the [M02 STT design](../architecture/m02-stt-design.md) for source references and validation limits.

## Consequences

Logical model identity is reproducible independently of converted artifact and container path. CPU tests can exercise the application without NVIDIA tools. GPU free-memory checks remain time-sensitive admission hints. Dependency compatibility and memory must be measured on authorized target hardware.

## Alternatives

Using a mutable model alias such as a moving branch is not reproducible. Putting a device path or backend model identifier in the public API couples consumers to deployment. Automatic fallback after a CUDA OOM hides resource faults and may make latency unpredictable. These are rejected.
