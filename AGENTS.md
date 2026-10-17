# Repository instructions

## Mandatory rules

- Inspect repository state, applicable instructions, existing contracts, plans and relevant code before editing. Preserve existing work and private files.
- Design before implementation: state responsibilities, affected boundaries, compatibility and validation approach. Scale artifacts using [methodology](docs/development/methodology.md); significant decisions require an ADR.
- Keep Gateway, STT and TTS responsibilities separate. Keep application business logic outside this platform and inference engines outside public contracts.
- Keep deployment addresses, ports, model IDs, paths, timeouts and resource limits in validated configuration. Reject unknown fields, missing required values and invalid values.
- Use small, cohesive modules, explicit dependencies and interfaces at meaningful boundaries. Inject dependencies where substitution or testing needs it. Do not require an interface for every concrete type. No hidden mutable state or unnecessary global dependencies.
- Preserve backward compatibility unless the user explicitly approves a breaking change. Make errors, cancellation and cleanup explicit at I/O boundaries.
- Keep private audio, credentials, local fixtures and sensitive test data under root `private/`; never add its contents to Git. Use secure, private defaults: no credentials in Git, no persistent audio or transcript logging by default, no sensitive payloads in structured logs, least privilege and private worker networking. Define temporary-data cleanup.
- Maintain relevant contracts, operational documentation and decision records alongside changes. Behavioral changes require appropriate tests, including regression coverage for fixes.
- Record actual verification commands, outcomes and limitations. Never fabricate results or equate inspection with executed verification. Classify evidence as OBSERVED, INTERPRETATION or NOT ESTABLISHED.
- Stop milestone advancement and closeout until the user explicitly approves. User validation is required before marking a milestone complete. Implementation authorization does not authorize commits; commits require explicit user approval. Existing approval remains valid within its stated scope.
- Work only in the authorized repository and scope. Do not modify unrelated repositories or running services. In particular preserve Ollama, Dify and the original M00 experiment. Separately authorized deployment work must follow its reviewed plan.

## Recommendations

Prefer standard libraries, simple explicit solutions, deterministic behavior and low coupling. Add dependencies or abstractions only for demonstrated needs; explain material trade-offs. Avoid speculative extensibility and premature optimization.

## Skill routing

Read only skills relevant to the task under `.codex/skills/`:

| Skill | Applies to |
| --- | --- |
| architecture-design | Component boundaries and significant design decisions |
| clean-code | Implementation or refactoring of application code |
| api-contracts | Public or internal API changes |
| testing-validation | Verification plans, tests and execution evidence |
| security-privacy | Changes to trust, data or exposure boundaries |
| deployment-operations | Container, configuration or operational changes |
| milestone-management | Planning, tracking, user validation and closeout |

Skills refine these rules; they do not grant extra scope or operational authority. The canonical workflow and proportional artifact requirements are in the methodology. See [principles](docs/architecture/principles.md) for architectural constraints and [PLANS.md](PLANS.md) for milestone state.
