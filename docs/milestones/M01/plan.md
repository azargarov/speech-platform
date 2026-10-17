# M01 plan

Scope: repository foundation, process skeletons, strict configuration, contracts, health/readiness, Compose/Dockerfiles, verification/CI, ADRs, M00 record and acceptance tests. No inference, streaming, public routing or authentication enforcement. No commits or running service modifications.

Sequence: inspect existing repository/tooling; create boundaries and contracts; implement configuration and health; add isolation and acceptance checks; run canonical verification; document observations and user validation. User validation is mandatory before completion.

Acceptance: make verify succeeds without GPU; all inference routes unavailable; readiness 503; strict invalid configuration rejection; valid OpenAPI; worker isolation and safe Compose rendering; private audio excluded; M00 retrieval limitation explicit.
