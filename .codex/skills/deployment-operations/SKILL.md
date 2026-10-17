---
name: deployment-operations
description: Prepare or review Speech Platform Docker, configuration and operational
  changes for reproducibility, isolation and safe recovery on the shared host.
---

# deployment-operations

## Triggers

Use for Dockerfiles, Compose, runtime configuration, provisioning, resource/health changes or deployment/runbook requests. Preparing deployment artifacts does not authorize changing running services.

## Required inputs

Target environment, current Compose/config/runbooks, image/dependency versions, resource needs, intended rollout/rollback and authorization scope.

## Workflow

1. Inspect deployment artifacts and available tooling read-only. Account for existing Ollama/Dify without altering them; identify only the dedicated Speech Platform resources.
2. Keep builds reproducible through pinned versions, controlled build contexts and documented inputs; prefer digests/locks when practical. Keep deployment values configurable and validate missing/unknown/invalid values.
3. Validate private networking, least privilege, safe mounts and practical CPU/memory/process limits. Define health as process liveness and readiness as usable service state; avoid dependency-induced liveness loops.
4. Define structured logs and Prometheus-compatible metrics, startup/shutdown, failure recovery, rollback and model-cache/provisioning lifecycle. Bound resource use without speculative tuning.
5. For GPU-dependent workers check host NVIDIA availability (for example `nvidia-smi`) and authorized container GPU access before GPU validation. If hardware/tooling is unavailable, use GPU-free structural checks and mark GPU readiness NOT ESTABLISHED; never make GPU mandatory for CI.
6. Run rendered Compose/config checks and appropriate build checks. If a tool is missing, document manual/structural inspection limits. Prepare exact rollout, smoke-test and rollback commands; execute only within explicit deployment authorization.

## Expected outputs

Reviewable deployment/config artifacts, resource/health decisions, validation evidence and non-disruptive recovery/rollback runbook.

## Validation checklist

- [ ] Build inputs/version limitations recorded; configuration is environment-independent.
- [ ] Workers private and shared services untouched; limits and observability assessed.
- [ ] GPU checks and runtime validation distinguished from static/build success.
- [ ] Rollback covers known-good images/config; commands target dedicated project resources.

## Stop and escalation

Stop a deployment when authorization, target identity, rollback or required GPU capacity is missing. Continue artifact preparation. Never prune/restart shared services or overwrite the M00 experiment.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
