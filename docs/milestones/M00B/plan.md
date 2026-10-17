# M00B plan

Status: PASS; user validation and closeout approved on 2026-10-17. Work is limited to governance and development infrastructure.

Objective: establish repository governance and seven reusable Codex skills before further platform implementation. Existing M01 work predates this task and must be preserved; its presence does not authorize resumption.

## Scope and design

Create a concise AGENTS.md with mandatory rules separated from recommendations; seven self-contained skills in `.codex/skills/`; methodology and architecture principles; five milestone records; update PLANS.md. Add a portable governance validator, focused validator regression tests and a Make target included in existing CI through make verify. No application, contract, Docker or running-service changes. No commit or automatic progression.

Policy ownership: AGENTS.md holds shared rules; methodology holds stage gates and evidence definitions; architecture principles hold design constraints; skills hold focused workflows and link to common documents. No significant platform architecture decision is introduced, so no new ADR is warranted.

## Acceptance criteria

1. Existing code, contracts, deployment files and historical records remain unchanged.
2. AGENTS.md covers all requested rules, explicitly distinguishing mandatory policy and recommendations.
3. Exactly seven named skills contain supported YAML name/description frontmatter plus triggers, inputs, workflow, outputs, checklist and stop/escalation instructions.
4. Methodology defines Inspect → Design → Plan → Implement → Verify → User Validate → Closeout, proportional artifacts, failures, uncertainty and scope changes.
5. Principles cover application independence, component/provider boundaries, contracts, configuration, privacy, observability, isolation and resource awareness.
6. Installed quick_validate.py passes for every skill; portable checks and focused regression cases pass; semantic consistency review is separately reported.
7. PLANS.md and milestone records agree that M00B is PASS after user validation and M01 remains paused. Validation evidence is attributed accurately; no fabricated results or approvals.

## Verification plan and risks

Run installed skill validator using available Python/PyYAML, `make governance-check PYTHON=.venv/bin/python`, Ruff on added scripts, and canonical `make verify PYTHON=.venv/bin/python`. Inspect cross-document consistency and scoped checksum comparison of pre-existing files. Commands require no GPU or service deployment.

Risks: structural validation cannot prove skill selection quality; the installed validator is machine-local; future discovery by a new Codex session remains a user check. Portable checks provide a fallback without copying machine-local tooling into Git. Preserve previous M01 evidence as historical, not current authorization.
