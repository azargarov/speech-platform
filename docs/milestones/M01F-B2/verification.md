# M01F-B2 verification record

Verification was run locally in `/home/master/speech-platform` on
2026-10-20. Evidence labels follow [the methodology](../../development/methodology.md).

## OBSERVED

| Command | Result | Evidence |
| --- | --- | --- |
| `.venv/bin/python -m unittest scripts.test_project_lock scripts.test_service_deployment scripts.test_stt_deployment -q` | PASS, exit 0 | 78 tests passed in final review. Includes inherited descendant descriptor, process-group cleanup, recovery locking/audit, preflight/no-op marker absence, failure marker retention and successful marker clearing. |
| `.venv/bin/python -m unittest discover -s scripts -p 'test_*deployment*.py' -q` | PASS, exit 0 | 143 deployment-related tests passed. |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0 | Final review rerun: Go vet, Ruff lint/format, Go config checks, static Compose validation, release validation, Go race tests, all script tests, STT service tests, build, AST parse, governance validation and STT lock policy passed. Script discovery reported 339 tests; STT reported 61 tests. |
| `make governance-check PYTHON=.venv/bin/python` | PASS, exit 0 | Governance structure/reference validation and 2 governance tests passed. |
| `git diff --check` | PASS, exit 0 | No whitespace errors. |

An initial `make verify` stopped at Ruff format because the edited
`scripts/test_service_deployment.py` required formatting. Ruff formatted that
file, and the complete command was rerun successfully as recorded above.

## INTERPRETATION — implementation review

Local tests establish the modeled lock, process, marker and operator-resolution
behavior. They do not establish behavior of the target host's filesystem,
operator permissions or Docker daemon.

## NOT ESTABLISHED — implementation review, before host validation

At that review, no real `make install`, Docker lifecycle action,
production-state initialization, image pull, model download or target-host
recovery had been performed. Later real-host evidence is recorded below.
`flock` does not serialize external Docker clients, cannot prove an escaped
descendant has closed an inherited descriptor, and cannot establish that
daemon-side asynchronous work has ended. Operator validation remains pending;
B2 remains open and M01F-B3 has not started.

## Real-host lock validation — 2026-10-20

### OBSERVED

Executed in `/home/master/speech-platform` as UID/GID `1000:1000` against
`/srv/speech-platform/deployment-state/locks`, using the existing
`scripts.project_lock.ProjectLock` API and dedicated project identities
`speech-platform-m01f-b2-lock-test` and `speech-platform-m01f-b2-lock-test-other`.
No Docker command, install coordinator, state initialization, mutation marker
method or recovery method was invoked.

| Observation | Evidence |
| --- | --- |
| Lock root prerequisites | `stat` reported parent and lock root owned by `1000:1000`, both mode `0700`; `findmnt -T ... -no FSTYPE,SOURCE,TARGET` reported `ext4` on `/dev/mapper/ubuntu--vg-ubuntu--lv`. |
| Process A acquisition | PID `379250` acquired the original-project lock on device `64512`, inode `5767488`. |
| Independent process B contention | PID `379251` failed acquisition with `deployment operation is already active for this project`. |
| Different-project concurrency | PID `379252` acquired and released the second project's lock while A held the original project's lock. |
| Release and reacquisition | A (PID `379250`) reported release; independent PID `379254` then acquired and released the original project lock. |
| Kernel release on termination | Holder PID `379255` was terminated by `SIGKILL` (exit `-9`); PID `379276` then acquired and released the original project lock. |
| Persistent lock file | The original lock file remained on device `64512`, inode `5767488` before and after all scenarios; final owner `1000:1000`, mode `0600`. The lock file was not removed. |
| Uncertainty marker | No `.uncertain` marker existed for either dedicated test identity after execution. |
| Process cleanup | The harness completed its `finally` cleanup and reported all children terminated; all subprocess operations had deadlines, and the complete harness was bounded by `timeout 30s`. |
| Focused implementation tests | `.venv/bin/python -m unittest scripts.test_project_lock -v` — PASS, exit `0`, 14 tests. |
| Whitespace validation | `git diff --check` — PASS, exit `0`, no output. |

The lock directory was empty before this test. The two persistent `.lock` files
created for the dedicated identities are intentionally retained, consistent
with the contract that lock files are never unlinked.

### INTERPRETATION

On this host and filesystem, the `ProjectLock` implementation provided
cross-process same-project exclusion, independent-project concurrency, release
on descriptor close, kernel lock release after process death, persistent inode
identity and expected file ownership/mode. The pure locking scenarios did not
create uncertainty state. This validates the library locking boundary only; it
does not exercise install coordination, Docker behavior or recovery.

### NOT ESTABLISHED

No Docker lifecycle operation, installed-generation record, production project
lock, uncertainty marker, model or container was touched. External Docker
clients remain outside `flock` coordination, and daemon-side asynchronous work
is not validated by this test. Operator review is still required; B2 remains
open pending that review and is not closed or advanced by this evidence.

## Controlled real-host install integration preparation — 2026-10-20

Status: **read-only preflight PASS; install not executed; separate operator
approval required.** The observations below are from the target host in
`/home/master/speech-platform`. This is preparation evidence only.

### OBSERVED — preflight and exact plan

- The lock root `/srv/speech-platform/deployment-state/locks` and parent
  `/srv/speech-platform/deployment-state` were owned by `1000:1000`, mode
  `0700`; `findmnt` reported `ext4` on `/dev/mapper/ubuntu--vg-ubuntu--lv`.
  The target project's uncertainty marker was absent both before and after
  planning.
- `timeout 30s sg stt-model-reader -c '.venv/bin/python -m scripts.provision_models check --release releases/voiceservice-v0.1.2.yaml --store /var/tmp/speech-platform-m01e-fresh-v012/model-store'`
  exited `0` and reported:
  `verified: large-v3-turbo -> /var/tmp/speech-platform-m01e-fresh-v012/model-store/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  The verified release directory was owned `1000:988`, mode `2750`.
- The private `services.yaml` and `profile.yaml` both name
  `speech-platform-m01e-fresh-v012`; the private config sets Gateway host port
  `18084` and listener port `8080`. `docker inspect` observed publication only
  on `127.0.0.1:18084 -> 8080/tcp`; STT and TTS have no published ports.
- Exact plan command (exit `0`):

  ```sh
  timeout 120s sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store PYTHON=.venv/bin/python'
  ```

  Output:

  ```text
  PLAN: services=gateway,stt,tts
  PLAN: dependencies=none
  PLAN: compose_project=speech-platform-m01e-fresh-v012 gateway=127.0.0.1:18084->8080
  PLAN: service=gateway image=ghcr.io/azargarov/voiceservice-gateway@sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30 artifact=verified action=unchanged
  PLAN: service=stt image=ghcr.io/azargarov/voiceservice-stt-cuda@sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8 artifact=verified action=unchanged
  PLAN: service=tts image=ghcr.io/azargarov/voiceservice-tts-health-only@sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6 artifact=verified action=unchanged
  PLAN: gpu_free_mib=8412 admission_threshold_bytes=4294967296
  PLAN: admission=READY
  ```

- Before-state exact-project inventory contained exactly these three running
  containers; a second inventory after planning returned the same IDs and
  running/healthy states. Read-only endpoint probes returned HTTP 200 for
  Gateway `/healthz`, STT `/healthz` and `/readyz`, and TTS `/healthz`.

  | Service | Container ID | StartedAt (UTC) | Restarts | Image ID | Compose config hash | Runtime health/readiness |
  | --- | --- | --- | ---: | --- | --- | --- |
  | Gateway | `012e68af14204da473c4f3f0e131354c8e2978983507fef621e475b945187a15` | `2026-10-19T21:25:34.172003493Z` | 0 | `sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30` | `6031ccc4b7167665eea7beb3c8ea029abba4d5999e824a0299c64735bbde64fe` | running; `/healthz` 200; no Docker healthcheck |
  | STT | `6a835c317c622a852f2c7a9760c028dd990862f8cc67acc96fbc49c6be50b303` | `2026-10-19T21:25:35.670503172Z` | 0 | `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8` | `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109` | Docker healthy; `/healthz` 200 and `/readyz` 200 |
  | TTS | `33337e3f5754d54b6a87deafcf5357505c129185d34e1966f4b35a7dc8543c9d` | `2026-10-19T21:25:44.205148127Z` | 0 | `sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6` | `5852729ea6264290d3b13e0acaa150ae49ac19c7af063fe3a1fa90a74d57254b` | running; `/healthz` 200; no Docker healthcheck |

- Existing experimental STT identity: project
  `speech-platform-stt-cuda-m01e-exp-v012`, container
  `bf7e4255aecf77bbe84a5f1e048849d645514b38f0aa7a2bb9dcea4276cc52f7`,
  StartedAt `2026-10-18T23:11:03.948795311Z`, restart count `0`, image ID
  `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8`,
  Compose config hash
  `2a9b8c4ebec2976e7b496cde579dfb63e06e2a2c673b311e61cf78132f9da4a6`,
  running and Docker healthy; `/healthz` and `/readyz` returned HTTP 200.
- Existing operational STT identity: project
  `speech-platform-stt-runtime-smoke-20261018`, container
  `ff12dafa6bd45de664e58928acf427ebd40ba876983ea2b046bbd495a464d996`,
  StartedAt `2026-10-18T17:35:13.123050511Z`, restart count `0`, image ID
  `sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c`,
  Compose config hash
  `e34727b5960c16008dcd93407f199d6c74581b21d4a4968b8a0796a32eb313df`,
  running and Docker healthy; `/healthz` and `/readyz` returned HTTP 200.
- No target drift was reported: all configured image artifacts were verified,
  all three planned actions were `unchanged`, admission was `READY`, the
  expected exact project was rendered, and the before/after target container
  IDs and states matched. No preflight blockers remain for a no-op plan.
- No install command was executed. No container/network lifecycle operation,
  artifact download, state-generation initialization, production lock or marker
  modification, commit or push occurred.

### Proposed exact command — NOT EXECUTED

This is the command for separate operator authorization. It passes the approved
lock root explicitly and uses the same configuration as the successful plan:

```sh
sg stt-model-reader -c 'make install SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store LOCK_ROOT=/srv/speech-platform/deployment-state/locks PYTHON=.venv/bin/python'
```

### INTERPRETATION

The controlled no-op installation is ready for a separate authorization based
on the current read-only plan and unchanged runtime identities. This is a
point-in-time conclusion. Because the plan does not acquire the install lock,
re-run the full plan and baseline checks immediately before any later
separately authorized install; stop if any identity, health, configuration,
artifact, marker or admission result changes.

### NOT ESTABLISHED

No installation was attempted. The current readiness conclusion does not
authorize `make install`, and does not establish that the runtime will remain
unchanged until a future execution.

## One controlled no-op installation — 2026-10-20

### OBSERVED — mandatory preflight

At `2026-10-20T17:30:48Z`, the repeated canonical plan command was:

```sh
timeout 120s sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store PYTHON=.venv/bin/python'
```

It exited `0` and reproduced the prior result: `gateway`, `stt` and `tts` each
reported `artifact=verified action=unchanged`; project
`speech-platform-m01e-fresh-v012`; Gateway `127.0.0.1:18084->8080`; GPU free
memory `8412 MiB`; `admission=READY`.

Immediately before installation, the target and parent lock roots were owned
`1000:1000`, mode `0700`; `findmnt` reported `ext4` on
`/dev/mapper/ubuntu--vg-ubuntu--lv`. The target uncertainty marker was absent.
The exact three target containers were running, with STT Docker healthy. HTTP
probes returned 200 for Gateway `/healthz`, STT `/healthz` and `/readyz`, and
TTS `/healthz`. The complete before-state also captured the original STT
runtime-smoke project, all three services in experimental project
`speech-platform-stt-cuda-m01e-exp-v012`, Ollama, and all containers in Dify's
`docker` project. Those records were retained temporarily with mode `0600` for
comparison.

Before-state target identities:

| Service | Container ID | StartedAt (UTC) | Restarts | Image ID | Compose config hash |
| --- | --- | --- | ---: | --- | --- |
| Gateway | `012e68af14204da473c4f3f0e131354c8e2978983507fef621e475b945187a15` | `2026-10-19T21:25:34.172003493Z` | 0 | `sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30` | `6031ccc4b7167665eea7beb3c8ea029abba4d5999e824a0299c64735bbde64fe` |
| STT | `6a835c317c622a852f2c7a9760c028dd990862f8cc67acc96fbc49c6be50b303` | `2026-10-19T21:25:35.670503172Z` | 0 | `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8` | `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109` |
| TTS | `33337e3f5754d54b6a87deafcf5357505c129185d34e1966f4b35a7dc8543c9d` | `2026-10-19T21:25:44.205148127Z` | 0 | `sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6` | `5852729ea6264290d3b13e0acaa150ae49ac19c7af063fe3a1fa90a74d57254b` |

### OBSERVED — fail-closed no-op guard

Read-only code inspection found that the coordinator recalculated actions under
the lock but did not compare them with the first preflight, and the staging
helpers could pull/download if a local artifact disappeared. Before the one
installation invocation, `scripts.stt_deployment` was changed to abort if
locked actions differ and to validate images/models in plan mode when every
action is `unchanged`. Regression coverage was added in
`scripts/test_service_deployment.py` for both cases.

- `.venv/bin/ruff format scripts/stt_deployment.py scripts/test_service_deployment.py`
  — exit `0`; one file reformatted, one unchanged.
- `.venv/bin/python -m unittest scripts.test_service_deployment scripts.test_stt_deployment -q`
  — exit `0`; 64 tests passed.

### OBSERVED — exactly one authorized installation invocation

The one command invocation was bounded with `timeout 240s`:

```sh
timeout 240s sg stt-model-reader -c 'make install SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store LOCK_ROOT=/srv/speech-platform/deployment-state/locks PYTHON=.venv/bin/python'
```

Observed output from the single invocation:

```text
PLAN: services=gateway,stt,tts
PLAN: dependencies=none
INSTALL: gateway unchanged and healthy
INSTALL: stt unchanged and healthy
INSTALL: tts unchanged and healthy
```

**Exit status: NOT ESTABLISHED.** The command's output was received, but the
interactive process session expired before its final exit code was captured.
The installation was not retried. No error text or unexpected mutation
proposal was observed. Given the missing exit-status evidence, this record does
not claim a fully evidenced PASS.

### OBSERVED — post-install state

- All three target container records matched the pre-install baseline exactly:
  IDs, `StartedAt`, restart counts, image IDs and Compose config hashes were
  unchanged. All remained running; STT remained Docker healthy.
- Fresh Gateway `http://127.0.0.1:18084/healthz` returned HTTP 200. Fresh STT
  `/healthz` and `/readyz` returned HTTP 200; TTS `/healthz` returned HTTP 200.
- The target uncertainty marker remained absent. The persistent lock file was
  owned UID/GID `1000:988`, mode `0600`, inode `5767490`. Using the existing
  `ProjectLock` API, PID `393528` acquired the exact project lock, verified its
  inode, and released it; acquisition succeeded after installation.
- The original STT container (`ff12dafa6bd45de664e58928acf427ebd40ba876983ea2b046bbd495a464d996`)
  and the experimental project's Gateway, STT and TTS containers (IDs
  `efc4aef7b7ada5422ce6c5e0ce0d44ecc178bf37e0b584f09b10da8858c533c0`,
  `bf7e4255aecf77bbe84a5f1e048849d645514b38f0aa7a2bb9dcea4276cc52f7`, and
  `cbe5adcb28832d900c883763e1d32fa6453b432dec6de15b2a572eb1ad1130a0`) matched
  their pre-install records exactly. Original and experimental STT remained
  Docker healthy; their `/healthz` and `/readyz` endpoints returned 200.
  Experimental Gateway and TTS `/healthz` endpoints returned 200.
- Ollama container ID `72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba`
  matched its baseline identity and running state; `/api/version` returned
  HTTP 200 with version `0.33.1`. Docker has no configured Ollama healthcheck.
- All 13 Dify `docker` project container records matched before/after, including
  IDs, start times, restart counts, image IDs, config hashes, runtime states
  and Docker health statuses. API, PostgreSQL, Redis and Sandbox remained
  healthy; other running services had no Docker healthcheck; the existing
  `init_permissions` container remained exited with code 0. This establishes
  no observed container-state regression, not application-level Dify behavior.
- No target identity changed and no unexpected container/network lifecycle
  effect was observed. The unchanged install output and fail-closed staging
  mode are consistent with no image pull or model download. No uncertainty
  marker, installed-state generation, update, rollback, cleanup, unrelated
  project mutation, commit or push was performed.

### INTERPRETATION

The install coordinator reported all three services unchanged and healthy; the
post-install identities, health checks, marker check and library lock
reacquisition passed. Protected project container state and observed endpoints
show no regression. The missing captured exit status is an evidence gap, so
operator review should decide whether this execution is accepted as PASS or
requires a separately authorized follow-up. No automatic retry is permitted.

### NOT ESTABLISHED

The exact process exit status of the one `make install` invocation is not
established. The run did not initialize installed-state generations and makes
no claim about future runtime stability or Dify application-level behavior.

## Final review and read-only host validation — 2026-10-20

### OBSERVED — final code verification

| Command | Result | Evidence |
| --- | --- | --- |
| `.venv/bin/python -m unittest scripts.test_project_lock scripts.test_service_deployment scripts.test_stt_deployment -q` | PASS, exit 0 | 78 tests passed in 4.415 seconds. Covers the latest action-change-after-lock guard, unchanged-install read-only artifact validation, process/descendant safety, uncertainty marker handling, and lock acquisition/release. |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0 | 339 script tests, 61 STT service tests, Go vet/race/build, lint/format, config and release validation, Compose config validation, governance validation and STT lock policy all passed. This verification renders/validates Compose configuration; it did not perform lifecycle operations. |
| `make governance-check PYTHON=.venv/bin/python` | PASS, exit 0 | Governance validator PASS; 2 governance tests passed. |
| `git diff --check` | PASS, exit 0 | No whitespace errors. |

The final focused suite and complete verification were run after the latest
implementation corrections. Earlier evidence in the real-host install section
records the focused suite before the one installation invocation; that
invocation itself occurred after those corrections and printed all three
services as unchanged and healthy. The real-host flock scenarios also precede
the latest coordinator corrections, while the lock implementation and its
host-tested behavior were not changed by those corrections.

### OBSERVED — current read-only host state

Read-only inspection was performed after the final code verification. No
`make install`, Docker lifecycle operation, image pull, model download,
generation initialization or marker operation was run.

| Check | Result |
| --- | --- |
| Lock root | `/srv/speech-platform/deployment-state/locks`, ext4, owner `1000:1000`, mode `0700`; parent state root also `1000:1000`, mode `0700`. |
| Target uncertainty marker | Absent. |
| Target project containers | Gateway, STT and TTS all running; IDs, `StartedAt`, restart counts, image IDs and Compose config hashes match the recorded pre-install identities above. Restart count remains 0 for each. |
| Implemented service health/readiness | Gateway `127.0.0.1:18084/healthz` returned 200; STT `/healthz` and `/readyz` returned 200 and Docker reported healthy; TTS `/healthz` returned 200. Gateway and TTS do not define Docker healthchecks. |
| Lock availability | Existing target lock file owner `1000:988`, mode `0600`, device `64512`, inode `5767490`; current process PID `393528` acquired and released it through `scripts.project_lock.ProjectLock`. |
| Original operational STT | Same recorded container identity, running and Docker healthy; `/healthz` and `/readyz` returned 200. |
| Experimental VoiceService | Gateway, STT and TTS IDs matched the records; all running, STT Docker healthy; implemented health/readiness endpoints returned 200. |
| Ollama | Same recorded container identity, running; `/api/version` returned 200 (`0.33.1`). No Docker healthcheck is configured. |
| Dify | 13 containers observed with the recorded state/health matrix; API, PostgreSQL, Redis and Sandbox healthy, other active services running without Docker healthchecks, and `init_permissions` exited 0. Earlier pre/post-install snapshots matched all 13 container records. |

An initial ad hoc host assertion script stopped on its STT comparison, and a
separate diagnostic script had a local type error. Direct field-by-field
`docker inspect` comparison then confirmed every recorded STT field matched;
the corrected comprehensive read-only check passed. These were checker errors,
not observed host drift, and no host state was changed.

### INTERPRETATION — acceptance recommendation

| Canonical B2 requirement | Assessment |
| --- | --- |
| Cross-process project lock, independent project concurrency, persistent inode and kernel release | PASS — focused tests and real-host `ProjectLock` scenarios recorded above. |
| Lock held across install work with process/descendant cleanup safeguards | PASS — focused regressions and full verification passed; escaped descendants and asynchronous daemon work remain documented limits. |
| Action changes after lock and no-op artifact loss fail closed | PASS — latest regression tests passed; the single authorized no-op invocation reported all three services unchanged and healthy. |
| Uncertainty marker behavior | PASS — local behavior tests passed; target marker absent before/after the recorded install and current read-only check. |
| Controlled no-op runtime preservation and health | PASS — exact target identities and restart counts preserved; implemented health checks passed; protected host projects showed no observed regression. |
| Historical install process exit status | NOT ESTABLISHED — interactive session expired after the observed successful per-service output. It was not retried and no exit code is inferred. |

Available independent evidence satisfies the approved behavioral acceptance
criteria for this bounded no-op execution despite the missing historical
process exit status. Recommendation: **PASS for technical acceptance, pending
operator review and explicit closeout**. This recommendation does not claim
that the missing exit code was zero. Operator closeout is recorded below.

## Closeout verification — 2026-10-20

### OBSERVED — local repository

Executed in `/home/master/speech-platform` during closeout:

| Command | Result | Evidence |
| --- | --- | --- |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0 | Full repository verification target completed, including Go vet/race/build, Ruff checks, configuration and static Compose validation, release validation, script and STT service tests, governance validation and STT lock policy. Static Compose validation did not start services. |
| `make governance-check PYTHON=.venv/bin/python` | PASS, exit 0 | Governance structure/reference validator passed; 2 governance tests passed. |
| `git diff --check` | PASS, exit 0 | No whitespace errors. |

No install command, Docker lifecycle command, network mutation, generation
initialization or uncertainty-marker manipulation was performed during
closeout. The earlier real-host lock scenarios and the one authorized no-op
installation remain recorded above without modification. The historical
`make install` process exit code remains **NOT ESTABLISHED**; it was not
reconstructed or retried.

### OBSERVED — operator validation

The operator reviewed the final acceptance report and explicitly approved
M01F-B2 closeout with status **PASS**, dated 2026-10-20. The approval accepts
the bounded evidence scope while retaining the missing historical install
exit code as a limitation. See [user validation](user-validation.md).

### INTERPRETATION — final status

M01F-B2 is **COMPLETE — PASS**. This closeout does not implement update,
rollback or baseline adoption, and does not start M01F-B3. External Docker
clients remain outside the lock; escaped descendants cannot always be
observed; asynchronous Docker daemon work may outlive the CLI. The persistent
uncertainty marker remains the documented fail-closed signal for cooperating
installers when completion cannot be established.
