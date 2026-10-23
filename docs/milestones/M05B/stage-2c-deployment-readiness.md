# M05B Stage 2C — Deployment Readiness Review

Status: **Gateway-to-Ollama network path qualified; approved candidate built and offline-verified. A separately authorized deployment attempt stopped at preflight because the root-owned model integrity check could not obtain sudo authorization. No production service was changed.**
The original read-only diagnosis was followed by the specifically authorized
additive Ollama network attachment documented below. The 2026-10-23 deployment
attempt did not recreate Gateway, STT, TTS or Ollama; no inference was run.

## 1. Observed deployment baseline

Inspection date: 2026-10-22 UTC. Docker Compose project: `speech-platform`,
working directory `/home/master/speech-platform`. The running Gateway's
Compose labels identify its source files as:

```text
/home/master/speech-platform/compose.yaml
/home/master/speech-platform/private/m04/live-20261022/rollback.compose.yaml
```

The project environment file is the ignored private `.env`; its values were
not printed. The three product containers were healthy with zero restarts:

| Service | Container ID | Image / image ID | Started | Status |
| --- | --- | --- | --- | --- |
| Gateway | `03df6c803d3fee76c29919a19b19f02cb6eaf89f9e381d356277451cee536665` | `speech-platform-gateway:m03b-high-quality-20261022` / `sha256:d4cfd90de08651cc79e97632ab6ea904a2c0951f1e9e7ff562c923e1242241b9` | `2026-10-22T10:24:54.29065455Z` | running, healthy, restart count 0 |
| STT | `02110b11d58c6d842316a29f29295383cab47a0865284cb69485165a17c79e23` | `speech-platform-stt-cuda:3aa5f68c1d9a058ed2714b7b257c5b258a23c00a` | `2026-10-21T11:07:40.29861024Z` | running, healthy, restart count 0 |
| TTS | `cbda986a4e9ace938023a8ccdb571d4169b2855814970ccab7dd49c82cd19569` | `speech-platform-tts:m03b-high-quality-20261022` | `2026-10-22T10:24:48.2400378Z` | running, healthy, restart count 0 |

Gateway `/readyz` returned HTTP 200 and its published listener is
`127.0.0.1:8080`. STT and TTS have no host-published port; their Docker health
checks were healthy. Gateway's only config mount is
`/home/master/speech-platform/configs/gateway.yaml` (SHA-256
`d64ac8b07c7e2040e8107d08ea0fffbb2dc211339bbc3f1eb94ced4536143d93`). That
config has no `text_transform` block. Gateway has only the `SPEECH_API_TOKEN`
environment variable for application secrets; the variable value was not
read or disclosed. Its runtime variant is `foundation` and image revision
label is `m03b-high-quality-20261022`; M05B is not deployed.

The STT and TTS container IDs, start times, image references and zero restart
counts were captured as the comparison baseline. No post-task production
container mutation occurred.

## 2. Candidate artifacts

| Artifact | Observed identifier |
| --- | --- |
| Candidate tag | `speech-platform-gateway:m05b-stage2c-20261022` |
| Candidate image ID | `sha256:6b17635aa2a61b615d0680cfb1e9e1a8666c12c1b4b81ea482f91f2832b88e20` |
| Image revision label | `m05b-stage2c-0066c9a-working-tree` |
| Source HEAD at build | `0066c9a39fb09725137781cde114f912402033b4` |
| Private candidate config | `private/m05b/stage2c/gateway.yaml`, host mode 0644 within mode-0700 private parents; ignored by Git |
| Candidate config SHA-256 after network qualification | `0c5e22b499187dd413a9b47103db833b91e6869809dddf113cc8afc45c165c95` |
| Gateway-only Compose overlay | `deployments/compose/compose.m05b-stage2c.yaml` |

The image was built from the current working tree, which was dirty. The image
digest records the resulting binary content, but the source is not an immutable
committed release. A deployable candidate must be rebuilt from the reviewed,
clean source state and its final image/config digests re-recorded. The
candidate tag must not be treated as a release identifier.

The private candidate config reuses the implemented schema and current
Gateway/STT/TTS addresses. It enables the text API, sets
`selection.allow_cloud: false`, uses local Qwen at context 8192 with
`think: false`, `num_predict: 1024`, and finite `keep_alive: 5s`. Groq model
entries remain configured but are ineligible while cloud permission is false.
No `GROQ_API_KEY` value is included or supplied. Existing STT/TTS config and
lifecycle behavior are not changed.

The overlay selects the candidate image/config and appends the external
`speech-platform_ollama_private` network to the Gateway's existing three
networks; `build` is reset so a rollout cannot silently rebuild. The ineffective
`host.docker.internal` mapping was removed. Rendered Compose preserves the
loopback-only API port and all existing Gateway network attachments. The
private candidate config points local Ollama at
`http://ollama:11434/api/generate` and keeps `allow_cloud: false`.

## 3. Network findings and diagnosis

**OBSERVED topology:**

| Network | Subnet / gateway | Mode | Members relevant here |
| --- | --- | --- | --- |
| `speech-platform_publish` | `172.28.0.0/16`, `172.28.0.1` | user bridge, `internal=false`, `enable_ip_masquerade=false` | Gateway `172.28.0.2` |
| `speech-platform_stt_private` | `172.30.0.0/16`, `172.30.0.1` | `internal=true` | Gateway `172.30.0.3`, STT `172.30.0.2` |
| `speech-platform_tts_private` | `172.29.0.0/16`, `172.29.0.1` | `internal=true` | Gateway `172.29.0.3`, TTS `172.29.0.2` |
| Docker default `bridge` | `172.17.0.0/16`, `172.17.0.1` | user bridge, masquerading enabled | Ollama `172.17.0.2` |

Gateway's current `/etc/hosts` has no `host.docker.internal` entry, and its
Docker `ExtraHosts` is empty. From the Gateway network namespace, Docker DNS
`127.0.0.11` returned NXDOMAIN for `host.docker.internal`. The initial
candidate overlay draft added a host-gateway mapping to `172.28.0.1`, but TCP
to that address and Ollama's `172.17.0.2` still timed out. That mapping was
removed after the dedicated network was qualified. The Gateway route table contains
connected routes to its three current networks and a default route via
`172.28.0.1`; `172.17.0.0/16` is not directly connected.

Ollama is not Compose-managed by this project. It remains on Docker's default
bridge, publishes container port 11434 on host `0.0.0.0` and `::`, and has
`OLLAMA_HOST=0.0.0.0:11434`. The following **read-only, non-generation** probes
were observed:

| Path | Result | What it establishes |
| --- | --- | --- |
| Host `127.0.0.1:11434/api/version` | HTTP 200, Ollama 0.33.1 | Host loopback to published endpoint works |
| Host `192.168.1.106:11434/api/version` | HTTP 200 | Host LAN interface to published endpoint works; this broad existing bind is not changed here |
| Host `172.17.0.2:11434/api/version` | HTTP 200 | Ollama listens on its container address |
| Gateway namespace `host.docker.internal` | NXDOMAIN on current Gateway; initial overlay draft mapped it to host bridge gateway | Name resolution was missing, but the mapping did not repair TCP; the current overlay removes it |
| Gateway namespace `172.28.0.1:11434` with candidate mapping | TCP timeout | Host-side route/listener path is filtered or otherwise unavailable from Gateway bridge |
| Gateway namespace `172.17.0.2:11434` | TCP timeout | Direct cross-bridge access is unavailable |
| Gateway namespace `api.groq.com` | DNS A/AAAA resolution succeeds; TCP 443 fails on IPv4 and IPv6 | DNS works; container egress path does not |
| Host to an `api.groq.com` IPv4 address | TCP 443 connected | Host uplink works; failure is specific to container egress path |

**INTERPRETATION — Ollama:** there are two distinct issues. The current
Gateway lacks a hostname mapping, and adding one does not repair the observed
TCP path. The Ollama listener itself is healthy and reachable from the host.
The Gateway's request to the host bridge address likely encounters host/Docker
forwarding policy; its request to `172.17.0.2` crosses an isolated Docker
bridge boundary. IP forwarding is enabled (`net.ipv4.ip_forward=1`), but that
does not establish that Docker's filter rules permit either route.

**INTERPRETATION — Groq egress:** the direct configuration cause is explicit:
the Gateway's only non-internal network disables bridge masquerading. Its
outbound packets retain the private `172.28.0.2` source, for which the LAN
router has no return route. Host TCP succeeds and Gateway DNS succeeds, while
Gateway TCP fails. This is consistent with missing outbound SNAT on this
bridge. Cloud stays disabled; do not enable masquerading as a side effect of
fixing Ollama access.

**NOT ESTABLISHED:** exact firewall drop rule/counter for either the host
bridge-to-published-port path or cross-bridge path. `nft list ruleset`,
`iptables -S`, and `iptables-save` returned permission errors because the
diagnostic environment lacks the required network-administration capability.
No firewall, route, network, or container changes were made. The direct cause
of the Groq egress failure is strongly indicated by the no-masquerade network
setting; an additional host firewall restriction cannot be excluded.

### Authorized network qualification — 2026-10-22

**OBSERVED:** preflight used Docker context `default`, Docker Engine 29.1.3,
host name `llm`. The proposed network name was unused. Existing Docker IPv4
subnets ranged from `172.17.0.0/16` through `172.30.0.0/16` without overlap;
Docker allocated `172.31.0.0/16` for the new network. Before the change,
Ollama container `72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba`
was running on `bridge` at `172.17.0.2`, with its existing host port bound on
`0.0.0.0:11434` and `[::]:11434`.

**OBSERVED:** Docker created network
`speech-platform_ollama_private` (ID
`f45063e992ba78f6c2499173af314d03d3b917349bd7ef8b15da7ea6f39c3fbd`) as a
user-defined bridge with `internal=true`, subnet `172.31.0.0/16`, gateway
`172.31.0.1`. The existing Ollama container was connected with alias `ollama`
at `172.31.0.2`; its original `bridge` attachment, container ID, start time,
published port and restart count 0 remained present. After removing both
disposable probes, Ollama was the only member of the new network. The
production Gateway was not attached.

**OBSERVED:** disposable probe `65a578a73f99d89fd9b03de34c641d92ad7bc4b76e0c3b1e1aeccf3ee008e746`,
attached only to the private network, resolved `ollama` as `172.31.0.2` and
received HTTP 200 with version `0.33.1` from `GET /api/version`. A second
probe's TLS-verified connection to `https://1.1.1.1` failed to connect (curl
exit 7); the first probe could not resolve/reach `https://example.com` (curl
exit 28). These checks establish no general external path from a container
attached only to this internal network. They do not test external egress from
the existing multi-network Gateway or Ollama containers.

**OBSERVED:** after network changes, host `GET /api/version` still returned
version `0.33.1`; `GET /api/ps` returned `{"models":[]}`. No generation, model
load or unload API was called. Immediate pre-change `/api/ps` was not captured,
so unchanged pre/post model residency is **NOT ESTABLISHED**. The Gateway
remained healthy/ready at HTTP 200. Gateway, STT and TTS retained their exact
preflight container IDs and start times, stayed healthy and retained restart
count 0. Their network attachments were unchanged.

**OBSERVED:** the candidate Compose overlay rendered with networks
`publish`, `stt_private`, `tts_private`, and `ollama_private`; the external
network name is `speech-platform_ollama_private`. The rendered API port remains
bound to `127.0.0.1:8080`; the config mount resolves to the private candidate
file; `extra_hosts` is empty. The candidate config retains `allow_cloud: false`
and uses `http://ollama:11434/api/generate`. No production Compose command was
applied and no Gateway network was changed.

**INTERPRETATION:** the dedicated DNS/TCP/read-only API path is qualified for a
future Gateway attachment. The internal network does not grant egress to
containers attached only to it. The existing shared Ollama container remains
on its original bridge, so existing bridge clients retain their network path.
The existing host port remains exposed on all host interfaces as before and
was not changed here.

**NOT ESTABLISHED:** any live inference through the new network, the
multi-homed Ollama container's general egress behavior, production Gateway
connectivity after it joins the network, local model quality, or Gateway
deployment readiness. A separately authorized Gateway deployment and bounded
functional validation are still required.

## 4. Minimal network options

| Option | Required changes | Security and service effects | Assessment |
| --- | --- | --- | --- |
| Dedicated Gateway-to-Ollama network | Completed Ollama-only network setup; future Gateway overlay attaches to this network and uses `http://ollama:11434/api/generate` | Network is internal. STT/TTS networks remain as-is. Ollama configuration and existing default-bridge/publication remain unchanged; existing bridge clients keep their path. The additional Ollama attachment must be recreated if the container is replaced. Existing all-interface host publication remains unchanged and should be reviewed separately. | **Qualified for Gateway-only deployment review.** This does not authorize deployment. |
| Host-gateway plus narrow forwarding | Keep candidate `extra_hosts`; use `host.docker.internal:11434`; add a host/Docker forwarding allow rule limited to Gateway source and Ollama port, with stable source identity. The exact rule cannot be specified safely until the active NAT/filter path is inspectable. | Leaves STT/TTS networks and Ollama config unchanged. A source-IP or bridge-interface exception can be brittle when Gateway/network is recreated; a broader subnet exception exposes Ollama to every container on that bridge. Existing Ollama published port remains as currently bound. | Not recommended before firewall visibility and a stable, narrowly scoped match are established. |
| Gateway-only outbound network | Add a separate non-internal Gateway egress bridge with masquerading and host egress policy; retain `allow_cloud:false`; do not alter the existing `publish` network | Applies only to Gateway if only Gateway is attached; STT/TTS and Ollama are unchanged. NAT alone gives broad outbound capability, not Groq-only access; firewall/egress restrictions and cloud review are required. | Not needed for local Ollama. Reserve for a separately authorized cloud deployment. |

Recommended declarative delta, after separate authorization:

```yaml
# candidate Gateway config
text_transform:
  providers:
    - id: host-ollama
      endpoint: http://ollama:11434/api/generate

# Gateway-only Compose overlay: append this network; preserve existing three.
services:
  gateway:
    networks:
      - ollama_private
networks:
  ollama_private:
    external: true
    name: speech-platform_ollama_private
```

The existing Ollama container received only the additional network alias
`ollama`; its default bridge, published port, image, environment, restart
policy and configuration remain unchanged. The network was created as an
internal bridge and attached without restarting Ollama. The actual network
name is `speech-platform_ollama_private`; see the qualification evidence
above.

### Proposed incremental verification and rollback

The network creation, Ollama connection, probe, and candidate render below
were executed under the current task's networking authorization. The Gateway
attachment/recreation and inference remain outside this authorization:

1. Preflight recorded container IDs, start times, restart counts, health and
   existing network attachments. Host `/api/version` and GPU baseline were
   not captured before the attachment; immediate pre-change `/api/ps` was
   also not captured.
2. The isolated network was created and attached to Ollama:
   ```sh
   docker network create --driver bridge --internal speech-platform_ollama_private
   docker network connect --alias ollama speech-platform_ollama_private ollama
   ```

3. A disposable probe attached only to the new network verified
   that Docker DNS resolves `ollama` and read-only `GET /api/version` returns
   HTTP 200. Do not call `/api/generate`. Confirm Ollama container ID,
   restart count, old `bridge` attachment, and host published endpoint remain
   unchanged.
4. The candidate overlay/config was revised and rendered to attach the Gateway to
   `speech-platform_ollama_private` and use `http://ollama:11434/api/generate`.
   Confirm the rendered networks include all original Gateway networks plus
   the new one; STT/TTS definitions remain byte-for-byte unchanged.
5. Only after separate deployment authorization, recreate only Gateway with
   the revised overlay. Check Gateway `/readyz`, unchanged STT/TTS identities
   and health, Ollama identity/health, and the read-only version path from a
   disposable probe sharing the dedicated network. Confirm cloud remains
   disabled and an IPv4 TCP probe from Gateway's namespace to Groq port 443
   still fails. This check must not send HTTP or inference data to Groq.
6. For rollback after Gateway deployment, first run the existing Gateway-only
   rollback Compose command in section 6 so Gateway detaches from the new
   network and returns to its captured image/config. Then, only after
   inspection confirms no other client is attached, disconnect Ollama and
   remove the temporary network:

   ```sh
   docker network disconnect speech-platform_ollama_private ollama
   docker network rm speech-platform_ollama_private
   ```

7. Recheck the original Ollama bridge attachment and host `/api/version`,
   original Gateway image/config/readiness, STT/TTS IDs and health, and
   restart counts. Do not remove the network if an unexpected client remains;
   stop and ask the operator to resolve ownership.

No production inference or model loading is needed for this network
qualification. Any later live transformation smoke test requires its own
explicit authorization.

The previous untracked candidate overlay and private candidate config were
preserved at mode 0600 under
`private/m05b/stage2c/pre-network-rollback-20261022/`. If the candidate-artifact
change itself must be rolled back, restore those two files with:

```sh
cp private/m05b/stage2c/pre-network-rollback-20261022/compose.m05b-stage2c.yaml deployments/compose/compose.m05b-stage2c.yaml
chmod 0664 deployments/compose/compose.m05b-stage2c.yaml
cp private/m05b/stage2c/pre-network-rollback-20261022/gateway.yaml private/m05b/stage2c/gateway.yaml
chmod 0644 private/m05b/stage2c/gateway.yaml
```

## 5. Cloud and credential policy

Initial deployment policy is `allow_cloud: false`; cloud processing remains
disabled regardless of credentials. Do not include Groq credentials in the
initial Gateway environment. Any future Groq enablement requires a separate
review of cloud data exposure, egress, provider policy, cost limits and
credential injection, followed by an explicit config change to
`allow_cloud: true` in a new, hashed release config.

The Gateway currently resolves configured `api_key_env` values from process
environment. If cloud is later authorized, the existing private credential
file can be read into a short-lived deployment shell without printing it and
passed to Compose via an explicitly reviewed cloud overlay. The resulting
container environment is visible to Docker administrators through inspection;
this limitation must be accepted or a file-based credential interface must be
implemented and separately reviewed. Never place the key in tracked YAML,
Compose output, command arguments, shell history or logs. No credential was
read during this task.

## 6. Rollout and rollback procedure (prepared, not executed)

The following commands target the observed project and only the Gateway. They
must not be run until the dedicated network exists, the candidate overlay and
private config are revised to use it, the candidate is rebuilt from a clean
reviewed source revision, functional validation is authorized, and the
operator explicitly authorizes deployment. The currently tracked overlay
still contains only the ineffective host-gateway mapping. Re-record the
candidate tag/digest/config hash before use.

Candidate rollout:

```sh
cd /home/master/speech-platform
export M05B_GATEWAY_IMAGE=speech-platform-gateway:<reviewed-candidate-tag>
export M05B_GATEWAY_CONFIG=/home/master/speech-platform/private/m05b/stage2c/gateway.yaml
docker compose --env-file .env -p speech-platform \
  -f compose.yaml \
  -f private/m04/live-20261022/rollback.compose.yaml \
  -f deployments/compose/compose.m05b-stage2c.yaml \
  up -d --no-deps gateway
```

This targets service `gateway` with `--no-deps`; it must not change STT, TTS,
Ollama, or Dify. Never run `down`, `--remove-orphans`, `--force-recreate` on
the project, or a project-wide `up` for this procedure.

Rollback to the exact observed M04 rollback Compose definition and current
Gateway config:

```sh
cd /home/master/speech-platform
docker compose --env-file .env -p speech-platform \
  -f compose.yaml \
  -f private/m04/live-20261022/rollback.compose.yaml \
  up -d --no-deps gateway
```

The rollback uses the current config and image reference captured above. Verify
the image ID, config mount/hash, container health, restart count, Gateway
`/readyz`, and unchanged STT/TTS IDs and restart counts after either operation.
The commands are exact for the observed files but remain unexecuted and are
not deployment authorization.

## 7. Post-deployment validation matrix

Run only after deployment authorization and resolution of the network blocker.
Use synthetic fixtures, the private API token, bounded calls, and no live
cloud request while `allow_cloud` is false.

| Check | Expected result | Evidence / abort |
| --- | --- | --- |
| Container identity and Compose scope | Only Gateway replaced; STT/TTS IDs and start times unchanged | Before/after container IDs, restart counts, image/config hashes; abort on any speech worker recreation |
| Gateway health | Container healthy and `GET /readyz` is 200 | Timestamped status and bounded sanitized logs; rollback on unhealthy or repeated restart |
| STT | Synthetic private audio through `POST /v1/stt/transcriptions` completes within configured 180s | HTTP status, duration, nonempty metadata; do not retain transcript in tracked logs; abort on health/GPU degradation |
| TTS | Short synthetic text through `POST /v1/tts/speech` returns valid WAV within configured 600s | HTTP status, content type, WAV metadata/size; private generated audio cleaned after review; abort on health/GPU degradation |
| Raw text passthrough | Exact input returned with generated=false and zero provider invocations | Public metadata and provider counters; no model inference |
| Local transformation | One explicit `local-qwen`, `local_only:true`, context 8192 request returns valid completed text and expected logical model/provider metadata | Synthetic request/response privately reviewed; one request only unless separately approved; no fallback; abort on provider failure/timeout |
| Cloud boundary | With `allow_cloud:false`, no Groq request occurs even if explicit cloud selection is attempted | Fake-provider regression evidence or request counter; cloud calls must remain zero |
| Resource recovery | Ollama expires naturally after finite keep-alive; GPU returns toward baseline without unload command | Passive `/api/ps` and GPU samples; any pressure or persistent memory degradation aborts further local inference |

The API and auth schema were validated offline. STT/TTS and local transformation
functional checks above were not run in this preparation task.

## 8. GPU and model-quality restrictions

The observed Stage 2A local-Qwen peak was approximately 8,640 MiB used with
6,270 MiB free; TTS's existing load guard requires 8,000 MiB free. This does
not support a claim that TTS cold-load can overlap safely with local Qwen. Keep
local inference sequential, never force-unload, and defer TTS cold-load until
Ollama residency expires naturally and measured free memory is at least the
existing 8,000 MiB threshold. Abort if GPU free memory falls below the
Stage 2B 1,024 MiB hard floor, CUDA/driver errors occur, or STT/TTS health or
restart counts change unexpectedly. If memory does not recover naturally,
stop admitting local text work (roll the Gateway back to the text-disabled
baseline if needed), preserve monitoring, and allow Ollama's finite residency
to expire. Recheck `/api/ps`, GPU free memory, and speech-service health before
resuming. Do not issue unload commands, kill model runners, or restart Ollama
as an automatic response. If memory remains degraded after natural expiry or
health does not recover, leave local transformation disabled and escalate to
the operator; do not continue with TTS cold-load or another inference request.

Stage 2A's nine-case 4K/8K comparison recorded lexical-invariant failures for
7/9 cases at each context. Completion and memory recovery were observed, but
those outputs do not establish acceptable transformation quality. Generated
text is unverified and must be reviewed by the user. The M05A accepted model
limitations, including local Qwen's tendency to answer in English without an
explicit translation request, remain in force. Stage 2A operator review is
still pending; do not represent these results as a pass or quality guarantee.

## 9. Abort and rollback triggers

Abort rollout or immediately roll the Gateway back if any of the following
occurs:

- Candidate config, image ID, source revision or rendered Compose differs from
  the reviewed values.
- Ollama connectivity cannot be verified without inference, or an unreviewed
  cloud path/policy is enabled.
- Gateway fails health/readiness, repeatedly restarts, or returns broad 5xx on
  its health or passthrough checks.
- STT/TTS health, identity, start time or restart count changes unexpectedly.
- GPU free memory crosses the 1,024 MiB floor, driver/OOM errors appear, or
  resource attribution/measurement becomes persistently unreliable.
- Any unauthorized cloud request, credential disclosure, response/reasoning
  leakage, or private-data retention occurs.
- Local model output is incomplete/invalid or unacceptable on operator review.

Do not retry a failed live provider request automatically. Preserve bounded
private evidence, stop and request operator review.

## 10. Readiness decision

**Not ready for deployment authorization.** The earlier connectivity blocker is
resolved: the internal Ollama network was created and qualified in the
authorized networking task, and its provisioning is now automated in the
canonical installer. Remaining deployment gates are:

1. The current source worktree is dirty and repository governance requires
   separate operator authorization before commits. Build and verify the
   candidate from the reviewed clean release revision after that checkpoint.
2. Stage 2A quality results are accepted with limitations: seven lexical
   invariant failures per context remain failed. Local Qwen is retained only
   for user-reviewed transformations; no perfect meaning-preservation or
   multilingual-quality guarantee is made.
3. STT/TTS and local text-transform post-deployment smoke checks have not been
   run and require separate deployment/runtime authorization.
4. Groq egress remains unavailable because the Gateway publish bridge disables
   masquerading. Cloud stays disabled; future cloud enablement needs separate
   reviewed egress and policy configuration.

The automation and offline checks recorded in section 11 do not change these
gates or authorize rollout.

No code-level lifecycle changes were introduced. TTS lazy loading, idle unload
and active-inference protections remain unchanged. No additional service,
scheduler, forced eviction or M06 behavior is included.

## 11. Ollama network provisioning automation — 2026-10-22

**OBSERVED — implementation:** the canonical root deployment path now detects
enabled local Ollama models in the configuration selected by `GATEWAY_CONFIG`
(default `configs/gateway.yaml`). The optional `GATEWAY_CONFIG` path must resolve
to a regular file inside the repository and may not traverse symlinks. The selected
file is validated and mounted read-only into Gateway. `make plan` reports the
network prerequisite. `make install` prepares the external internal bridge and
attaches the configured, already-running Ollama container before Compose
build/start. The helper validates existing network type, exact container
identity, required alias, existing network attachments, and published ports.
It creates no Ollama container and does not restart, disconnect, or delete
Ollama or networks. Repeated preparation reuses a valid network and attachment.
The default container and network names are overridable through the private
`.env` keys `OLLAMA_CONTAINER_NAME` and `OLLAMA_NETWORK_NAME`.

**OBSERVED — Compose/config behavior:** the root stack gains the external
`ollama_private` network only when an enabled local Ollama-backed model is
configured. Gateway retains its existing publication, STT-private and
TTS-private attachments; STT and TTS definitions and network attachments do
not change. Legacy STT/TTS-only or cloud-only configuration does not select the
Ollama network. Cloud access is not enabled by this work. A Gateway-only update
is available as `make install SERVICE=gateway`; it first requires healthy
existing STT/TTS workers and uses Compose `build gateway` and `up -d --no-deps
gateway`.

**OBSERVED — verification:**

| Check | Result |
|---|---|
| `python -m unittest scripts.test_ollama_network scripts.test_product_deployment -v` (using `.venv/bin/python`) | PASS, 22 tests covering create/reuse/conflict, missing container, attachment, idempotency, no destructive cleanup, conditional overlay selection and config validation |
| `go test ./internal/texttransform ./cmd/gateway` | PASS; read-only DNS/TCP/version probe tests include DNS/TCP/HTTP failures and malformed version responses |
| `.venv/bin/ruff check` and `.venv/bin/ruff format --check` on deployment scripts | PASS |
| `make verify PYTHON=.venv/bin/python` | PASS on rerun: `go vet`, Ruff, Gateway/STT/TTS config validation, Compose rendering and checks, release validation, Go race tests, 513 script tests, 64 STT worker tests, Go build, governance, and lock checks |
| `git diff --check` | PASS |
| Documentation link validation | PASS through `make verify` governance checks |

An initial full verification run failed the existing static guard because the
new Gateway probe included a literal deployment URL. The probe was revised to
use the configured HTTP endpoint and explicit port; the rerun passed. No
production Docker resource, running service, Ollama instance, model or cloud
provider was contacted or changed during this task. No live inference was run.

The read-only Gateway `--check-ollama` mode verifies the configured Ollama
alias with DNS resolution, TCP connection and bounded `GET /api/version`; it
never calls a generation or model-management endpoint. The deployment helper
runs this probe after Gateway readiness and stops the install flow if the
provider is unreachable.

Gateway rollback and network cleanup remain separate. An install failure does
not automatically detach Ollama or remove a network, including a newly created
network. The operator must inspect ownership and membership before any explicit
cleanup. The runbook documents Gateway rollback, project removal, and
operator-reviewed network retirement separately.

**INTERPRETATION:** the canonical installation and upgrade path is now
implemented and offline-verified. The existing manually provisioned
`speech-platform_ollama_private` network remains the expected external network
for this host. This implementation does not establish that a newly built
production Gateway has used the probe, and it does not authorize deployment.

**NOT ESTABLISHED:** a clean release build, production Gateway deployment,
post-deployment Gateway-to-Ollama check, live transformation, or cloud egress.
Stage 2A quality findings are operator-accepted with limitations; no quality
pass is claimed. Deployment requires explicit operator authorization. The
existing network's creation/attachment was not repeated or modified here.

## 12. Release-candidate proposal — 2026-10-22

This is a reviewed proposal only. No image build from a clean source checkpoint,
production deployment, service restart, inference request or closeout occurred
in this preparation. The candidate image recorded above was built from a dirty
worktree and is not a release artifact. Repository governance requires
separate operator authorization before commits.

The local-only configuration is the ignored private file
`private/m05b/stage2c/gateway.yaml`; revalidate it and record its digest at
release time. It enables local Qwen at 8192 context, `think: false`,
`num_predict: 1024`, and `keep_alive: 5s`, while `allow_cloud: false`. Select it
by setting `GATEWAY_CONFIG=private/m05b/stage2c/gateway.yaml` in the mode-0600
`.env`. The canonical installer validates the selected config, prepares or
reuses the external Ollama network, builds only the requested service, and uses
`up -d --no-deps gateway` for a Gateway-only update. It never automatically
detaches Ollama or deletes the external network after failure or rollback.

After an authorized clean source checkpoint, the proposed image build command
is:

```sh
SOURCE_REVISION="$(git rev-parse HEAD)" docker compose --env-file .env -f compose.yaml build gateway
```

Review the resulting `speech-platform-gateway:<revision>` image ID and render
the selected configuration before rollout. The deployment command proposed
for a separately authorized rollout is:

```sh
make plan PYTHON=.venv/bin/python
make install SERVICE=gateway PYTHON=.venv/bin/python
```

Before and after rollout, record Gateway/STT/TTS container IDs, image IDs,
`StartedAt`, health and restart counts. Confirm STT and TTS retain their IDs,
start times and restart counts. Gateway-only install requires healthy STT and
TTS, builds only Gateway and uses `--no-deps`. Confirm Gateway `/readyz`, then
allow the installer to run the configured read-only `--check-ollama` probe
(DNS, TCP, `GET /api/version`) without loading a model. Live text transformation
and STT/TTS functional smoke tests need separate explicit authorization. Do not
run concurrent TTS/LLM inference; the observed Qwen peak was about 8,640 MiB
and simultaneous TTS cold loading is not qualified.

If rollback is separately authorized, use the recorded pre-M05B image and
configuration overlay. For the observed baseline, the proposed Gateway-only
rollback command is:

```sh
GATEWAY_CONFIG="$PWD/configs/gateway.yaml" docker compose --env-file .env -p speech-platform -f compose.yaml -f private/m04/live-20261022/rollback.compose.yaml up -d --no-deps gateway
```

This restores the recorded pre-M05B Gateway image/config and omits the Ollama
network overlay; it does not disconnect or restart shared Ollama. Verify
Gateway/STT/TTS health and confirm STT/TTS IDs, start times and restart counts
remain unchanged. Inspect the prior private rollback overlay and baseline image
before execution. Network retirement is a distinct operator-reviewed action.

## 13. Approved release build and controlled deployment preflight — 2026-10-23

**OBSERVED — artifact:** from approved source commit
`c3f0079227af573f7715640afa5b229a22c46ab6`, the Gateway image was built using
`SOURCE_REVISION=c3f0079227af573f7715640afa5b229a22c46ab6 docker compose
--env-file .env.example -f compose.yaml build gateway`. The resulting tag is
`speech-platform-gateway:c3f0079227af573f7715640afa5b229a22c46ab6`; image ID
and local RepoDigest are
`sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159`.
The `org.opencontainers.image.revision` label equals the approved commit;
service labels identify the foundation Gateway. Platform is `linux/amd64`.
The private candidate config SHA-256 is
`0c5e22b499187dd413a9b47103db833b91e6869809dddf113cc8afc45c165c95`; observed
settings are `allow_cloud: false`, Ollama endpoint
`http://ollama:11434/api/generate`, 8192 context and `keep_alive: 5s`.
Candidate `--check-config` passed in a network-disabled container. Compose
rendering retained loopback-only publication, the three existing Gateway
networks plus the external Ollama network, and unchanged STT/TTS service
definitions.

**OBSERVED — live preflight, 2026-10-23 05:35 UTC:** production Gateway
`03df6c803d3fee76c29919a19b19f02cb6eaf89f9e381d356277451cee536665` was
healthy on rollback image ID
`sha256:d4cfd90de08651cc79e97632ab6ea904a2c0951f1e9e7ff562c923e1242241b9`,
started `2026-10-22T10:24:54.29065455Z`, restart count 0, published only at
`127.0.0.1:8080`, and attached to `publish`, `stt_private`, and `tts_private`.
`/healthz` and `/readyz` both returned HTTP 200. STT
`02110b11d58c6d842316a29f29295383cab47a0865284cb69485165a17c79e23` and TTS
`cbda986a4e9ace938023a8ccdb571d4169b2855814970ccab7dd49c82cd19569` were
healthy with restart counts 0 and their recorded start times unchanged.
Ollama `72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba`
was running with restart count 0, attached to its original `bridge` and
`speech-platform_ollama_private` networks; the private network remained an
internal bridge with Ollama as its only container. Host `GET /api/version`
returned HTTP 200 and `ollama ps` showed no resident model. The GPU baseline
was 2,216 MiB used and 12,694 MiB free out of 15,360 MiB. The recorded M03B
rollback tag existed and resolved to the exact image ID of the running
Gateway; its rollback Compose render selected only the prior Gateway image
and omitted the Ollama network overlay.

The private `.env` initially lacked `GATEWAY_CONFIG`. The candidate config
path was added temporarily and `.env` remained mode 0600. The required
`make plan PYTHON=.venv/bin/python` returned exit 2 before producing a plan:
the model store is root-owned and its read-only integrity check requires sudo
authorization (`sudo -v`). No model data was changed. Because the same
preflight is mandatory for install, `make install SERVICE=gateway` was not
run. The temporary `GATEWAY_CONFIG` line was removed, restoring `.env` to its
preflight contents and mode. Six untracked M06 planning files were preserved.

**INTERPRETATION:** the image, private config, running baseline and rollback
artifact match the approved identities. The deployment did not proceed
because canonical preflight could not complete the read-only model integrity
check. The Gateway remains on M03B; no runtime checks or transformation were
performed against the candidate.

**NOT ESTABLISHED:** successful canonical install, candidate Gateway health
and Ollama connectivity in the production network namespace, post-deployment
STT/TTS preservation, local transformation quality, post-request GPU recovery,
or natural model expiry under the deployed Gateway.

Private preflight evidence: `private/m05b/stage2c/deployment-preflight-20261023T053556Z/report.json` (mode 0600). The initial continuation suggestion to use a detached worktree is superseded by the ownership-path investigation in Section 14: the running Compose project is bound to this checkout's canonical path. This record does not close M05B.

## 14. Deployment-preflight blocker diagnosis — 2026-10-23

**OBSERVED — model-store validation:** `make plan` calls the shared `checks()`
path with `model=True`. That path verifies the release descriptor and pinned
manifests, then runs both `scripts.provision_models check` (all required
release artifacts, including STT) and `scripts.tts_model check`. The checker
reads each on-disk manifest, walks the artifact directories, validates the
regular-file set and sizes, and hashes every payload file. The `check` actions
are read-only; no model data, permissions or manifests are changed. This is
performed for `plan` and `install`, including `SERVICE=gateway`; the current
installer has no service-scoped check option. **INTERPRETATION:** model hashes
are not intrinsically needed to replace only Gateway while healthy STT/TTS
containers and their mounts remain untouched, but the current canonical
deployment policy requires complete model integrity before every plan/install.
No integrity check was bypassed.

The current shell is UID/GID `1000:1000` and lacks `stt-model-reader` GID 988.
The store root `/srv/speech-platform/models` is `root:stt-model-reader`, mode
`2710`; current `stat` confirmed the digest directories are inaccessible to
this shell. Older M01E evidence records a successful check at an earlier point
and metadata-fingerprint observations, but the current installer does not
accept a timestamped attestation in place of re-hashing current payloads.
Minimum privilege under the existing helper is to run `sudo -v` interactively
as the operator, then run the plan/install as the normal `master` user. Its
existing fallback uses `sudo -n` only for the two read-only artifact-check
commands. Do not change store ownership or modes.

**OBSERVED — source cleanliness and project ownership:** current `git status`
contains only the two uncommitted M05B Stage 2C documentation files and the
six untracked M06 planning files; the index is clean and HEAD remains
`c3f0079227af573f7715640afa5b229a22c46ab6`. `git worktree list` reports only
the original checkout. `verify_project_ownership()` checks the running
`speech-platform` project's Compose config file path against the current
checkout's resolved `compose.yaml`. Docker reports the running project was
created from `/home/master/speech-platform/compose.yaml` plus its rollback
overlay. A detached worktree at another path is therefore not a supported
drop-in: it fails that ownership check (or, under another project name,
collides with the occupied loopback port). No source-cleanliness check was
weakened.

For a later approved install with no code changes, preserve changes at the
same canonical checkout path by parking them in the ignored private tree:

```sh
set -eu
backup="private/m05b/stage2c/deploy-preserve-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 0700 "$backup"
git diff --binary -- docs/milestones/M05B/stage-2c-deployment-readiness.md docs/milestones/M05B/verification.md > "$backup/m05b-docs.patch"
chmod 0600 "$backup/m05b-docs.patch"
git diff --cached --quiet
mv docs/adr/0022-model-lifecycle-predictive-warmup.md "$backup/adr-0022-model-lifecycle-predictive-warmup.md"
mv docs/milestones/M06 "$backup/M06"
git restore --worktree -- docs/milestones/M05B/stage-2c-deployment-readiness.md docs/milestones/M05B/verification.md
git status --short
```

Before continuing, confirm the remaining worktree is clean and HEAD is still
the approved commit. Keep the private backup until after deployment/rollback
assessment, then restore the two records with `git apply --binary
"$backup/m05b-docs.patch"` and move the two M06 paths back. Verify their saved
hashes and the final `git status`; remove the private backup only after
successful restoration. The `.env` remains ignored/private and must select
`private/m05b/stage2c/gateway.yaml` in mode 0600 for plan/install.

**OBSERVED — artifact reuse:** the approved image is still present under
`speech-platform-gateway:c3f0079227af573f7715640afa5b229a22c46ab6` with the
expected image ID. However, `make install SERVICE=gateway` unconditionally
runs `docker compose build gateway`; it has no no-build or expected-image-ID
option. The existing helper does not verify the exact candidate ID between
build and `up`. A rebuild from the same source may reuse BuildKit cache, but
identity preservation is **NOT ESTABLISHED**. Therefore the exact approved
image cannot currently be guaranteed through the canonical installer. Do not
use direct `compose up --no-build` as a workaround because it bypasses the
installer's preflight, network preparation and post-start probe.

**INTERPRETATION / decision gate:** no code changes are required to resolve
the model permission and dirty-worktree conditions; use the supported
read-only sudo fallback and temporarily preserve/restore local-only changes at
the original Compose path. A focused installer enhancement is required if
deployment must reuse this exact image: provide an explicit no-build mode that
requires an expected local image ID and validates its revision/service labels
before any lifecycle operation. That change needs offline regression tests,
separate implementation/commit authorization, and a fresh release review. The
alternative is to authorize a new build and approve its resulting image ID
before deployment; the current installer cannot pause after build for this
review. No change or deployment was made in this diagnostic task.

## Verified no-build Gateway deployment preparation — 2026-10-23

This section supersedes Section 14's observation that the canonical installer
cannot reuse the approved image. The installer now has an explicit no-build
mode, limited to `plan` and `install` with `SERVICE=gateway`. Normal installs
continue to build as before. No deployment was executed for this tooling
change.

The only approved target remains:

| Identity | Approved value |
| --- | --- |
| Source revision | `c3f0079227af573f7715640afa5b229a22c46ab6` |
| Local tag | `speech-platform-gateway:c3f0079227af573f7715640afa5b229a22c46ab6` |
| Image ID | `sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159` |

After the installer change is separately reviewed and committed, prepare the
existing canonical checkout at `/home/master/speech-platform` using the private
backup/restore procedure in Section 14. Preserve its original Compose path,
the two modified M05B records and all six M06 files; do not weaken the clean
worktree check. Keep `.env` mode 0600 and set these private values:

```dotenv
GATEWAY_CONFIG=private/m05b/stage2c/gateway.yaml
GATEWAY_EXPECTED_IMAGE_ID=sha256:5b07af8af964262e44d9961b39e2b1b346deef90d100ffb4cb39c45d2ef97159
GATEWAY_EXPECTED_SOURCE_REVISION=c3f0079227af573f7715640afa5b229a22c46ab6
```

The expected identity can instead be supplied using the script's explicit
`--expected-image-id` and `--expected-source-revision` options. Do not put
credentials or private config contents on the command line.

The plan/install preflight still verifies Git cleanliness and provenance,
Compose project ownership, model-store integrity, credentials, worker health,
and (when selected config enables local Ollama) network preparation/readiness.
Run the operator's interactive `sudo -v` first; the existing helper uses
non-interactive sudo only for its two read-only model artifact checks. It does
not change model-store data or permissions. The no-build image gate additionally
requires a full image ID and full source revision, verifies the approved
revision is an ancestor of HEAD, checks that Gateway build inputs have not
changed since that revision, and inspects the local tag's image ID, source,
service, role, runtime-variant and platform labels. It never pulls or builds.
The identity is inspected again immediately before Compose recreation.

Proposed commands, after a separate deployment authorization:

```sh
cd /home/master/speech-platform
sudo -v
make plan SERVICE=gateway NO_BUILD=1 PYTHON=.venv/bin/python
make install SERVICE=gateway NO_BUILD=1 PYTHON=.venv/bin/python
```

The install uses the canonical Compose project, prepares/reuses the approved
Ollama network if required, retains Gateway-only `--no-deps`, and invokes
Compose `up --no-build --pull never`. It then performs the existing readiness
and read-only Ollama API checks. Abort on any missing/mismatched image, label,
revision, dirty worktree, failed preflight, unexpected Compose scope, or failed
post-deployment health/readiness/connectivity check. No cloud access is enabled.

If rollback is separately authorized, restore only Gateway with the previously
validated overlay and current known-good configuration:

```sh
GATEWAY_CONFIG="$PWD/configs/gateway.yaml" docker compose --env-file .env \
  -p speech-platform -f compose.yaml \
  -f private/m04/live-20261022/rollback.compose.yaml \
  up -d --no-deps gateway
```

Then verify the restored image ID, `/healthz`, `/readyz`, and unchanged STT/TTS
container identities and health. Gateway rollback does not disconnect or
restart Ollama and does not remove the external network. Do not automatically
run network cleanup. The commands above are a proposal only; neither plan nor
install was run during this implementation task.
