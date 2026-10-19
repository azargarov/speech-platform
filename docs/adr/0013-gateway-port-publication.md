# ADR 0013: Publish Gateway through a dedicated bridge

- Status: Proposed; target deployment validation required
- Date: 2026-10-19

## Context

Gateway must publish one loopback-only host port while STT and TTS remain on
internal worker networks. The immutable v0.1.2 Gateway image is Distroless and
contains only `/gateway`; it has no Docker healthcheck, shell, curl, wget, or
healthcheck command. Gateway already serves `/healthz` and `/readyz`.

On Docker Engine 29.1.3, the inspected Gateway had the requested binding in
`HostConfig.PortBindings`, but `NetworkSettings.Ports["8080/tcp"]` was null,
`docker port` returned no mapping, and the configured host port refused a
read-only HTTP request. It was attached only to the Compose `stt_private`
internal bridge (plus `tts_private`). Docker's internal bridge behavior
explains this discrepancy: the requested mapping is retained but not realized.
Docker documents internal bridge isolation and host port publication separately
([bridge driver](https://docs.docker.com/engine/network/drivers/bridge/),
[port publishing](https://docs.docker.com/engine/network/port-publishing/)); the
Moby project has a report with the same `HostConfig.PortBindings` versus null
`NetworkSettings.Ports` symptom and the additional non-internal bridge workaround
([Moby discussion #53256](https://github.com/moby/moby/discussions/53256)).

## Decision

Propose a dedicated `gateway_publish` bridge attached only to Gateway. Keep
STT and TTS exclusively on their existing internal networks. Configure the
publication bridge with IP masquerading disabled to limit Gateway egress while
allowing Docker to realize its loopback host port mapping. The orchestrator
will verify both Docker's realized `NetworkSettings.Ports` mapping and a
successful host-side HTTP 200 from `/healthz` before reporting Gateway ready.

The healthcheck remains host-side. Compose cannot execute an HTTP probe inside
the current immutable image, and `--check-config` only validates configuration;
it does not prove that the running server is live or ready. `/readyz` currently
returns 503 by design because inference routing is not implemented, so
`/healthz` is the appropriate service liveness/readiness signal for this
foundation release.

## Alternatives

- Add a Compose healthcheck using `CMD-SHELL`, curl, wget, or Python: rejected;
  none exists in the Distroless image.
- Invoke `/gateway --check-config`: rejected as a health signal because it
  starts a separate process and validates config, not the running listener.
- Rebuild or replace the image with an embedded probe: rejected for this fix;
  it requires a new release and is unnecessary for host-side orchestration.
- Remove `internal: true` from worker networks: rejected because that would
  weaken STT/TTS network isolation.

## Consequences and validation

The immutable v0.1.2 image remains unchanged. Gateway receives a separate
bridge with IP masquerading disabled; the exact host, firewall, and routing
behavior must be validated on the target before service acceptance. Local
static checks and mocked regressions do not establish target publication,
reachability, or egress isolation. No running service is modified by this ADR.
