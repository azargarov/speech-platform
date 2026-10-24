# Initial full SpeechPlatform release qualification

Status: implementation, offline verification and isolated qualification completed;
release-candidate review/commit authorized on 2026-10-24; candidate GitHub execution
and final release acceptance remain pending. No tag/push/publication or working-stack deployment.

## Design and scope

[ADR 0023](../adr/0023-installation-preflight-and-release-path.md) records the
responsibilities and compatibility decisions. The canonical product path remains
Git + root Compose; historical VoiceService profiles remain available but do not
select the current inference stack. Install scripts own prerequisite checks and
selected service creation; workers retain all inference/lifecycle/resource control.
Public routing, authentication and API behavior are preserved.

Acceptance checks are grouped prerequisite outcomes, blocking/optional failures,
selected service isolation, provenance, actual isolated install/reinstall/remove,
synthetic API smoke, model idle behavior, and complete offline verification.
Installed model artifacts and externally owned Ollama are explicit prerequisites.
No real cloud inference, downloads of model weights, or mutation of shared Ollama.

## Initial observations

OBSERVED: branch main, HEAD `7176248b55d3016f31e685da545aa03d98447a42`, clean before
this task. The working Gateway, STT and TTS containers were healthy. Private audio
and vocabulary outputs were preserved under ignored `private/`.

- Product CLI rejected STT/TTS selection; it still supported full stack by omitting
  service. The historical profile enabled only STT and lacked its default service
  and TTS config files.
- VoiceService v0.1.2 references foundation Gateway and health-only TTS images, not
  the currently accepted application stack. Its STT artifact manifest remains the
  pinned model identity, independently of those historical runtime images.
- Root short volume syntax interpreted a relative Gateway path as an undefined
  named volume in direct Compose use. Long bind syntax and canonical path resolution
  remove that ambiguity.
- README and historical operations text described TTS/text transformation as future
  or candidate functionality despite later accepted implementation.
- Publisher built real CUDA TTS through Make but resolved its image from the old
  health-only Compose definition; its expected role/package also remained old.
- Normal verification did not discover the worker's TTS test directory directly.

## Changes under review

- `make preflight`, plan/install service scopes, read-only grouped outcome report,
  clean-source installation gate, bounded CUDA device probe, and selected health.
- Deployment variables omitted from `.env` no longer inherit ambient shell overrides;
  project identity is explicit, and effective Docker context (including DOCKER_CONTEXT
  precedence) must select a local Unix endpoint. Remote daemons are outside scope.
- GPU probes have unique owned names and bounded failure cleanup; uncertainty is
  reported explicitly rather than claiming an unconfirmed probe was removed.
- Local metadata probes disable proxies/redirects and run with a hard subprocess
  deadline, so a stalled/trickling provider cannot hold preflight indefinitely.
- `stop`/`remove` preserve images/volumes/models and external networks; status/logs
  no longer require healthy providers or model integrity checks.
- Private optional cloud credential file validates ownership/exposure, key names,
  reserved process variables and interpolation-sensitive values; only Gateway
  receives credentials. Disabled cloud requires no secrets and no cloud calls.
- Shared Ollama is inspected/reused without network attachment or recreation;
  metadata version/tags and installed model names are checked without inference.
- CUDA TTS publication resolves the actual image and lock identity. A publish tag
  must already resolve to the exact clean source; descriptor schema accepts CUDA
  TTS with synthesis capabilities and pinned model references while preserving
  the historical descriptor. No registry digest is fabricated.
- CI image jobs use separate runners for Gateway/STT CPU/STT CUDA/TTS. TTS runner
  clears unused Android SDK space only on the disposable GitHub runner. Gitleaks
  action is pinned; TTS offline tests and FFmpeg are included in verification.

## Observed host and preflight evidence

OBSERVED on this private development server: Ubuntu 24.04.5 amd64; Docker 29.1.3;
Compose 5.6.0; Quadro RTX 5000, NVIDIA driver 580.178.04. Initial GPU reading was
174 MiB used, 14,736 MiB free. Disk availability initially 113 GiB.

Gateway preflight: PASS=22 WARN=2 FAIL=0 SKIP=4. Enabled local Ollama endpoint,
private network/alias, version/tags/model availability and Gateway DNS/TCP/HTTP
passed; cloud skipped. The full-stack preflight correctly failed both model
checks because this account lacks the model-reader group. No sudo authorization
was cached; preflight did not escalate or modify access. This is a host prerequisite,
not an absent-model claim.

For isolated qualification only, existing pinned STT/TTS artifacts were copied
read-only through a nonroot disposable container with the configured reader GID
into ignored `private/release-qualification/models`; original stores remain intact.
The operator owns the copies and the worker reader GID is preserved. No model
weights were downloaded. The isolated preflight then passed with 26 PASS, 2 WARN,
0 FAIL and 1 SKIP using the default cloud/LLM-disabled configuration.

## Isolated execution evidence

OBSERVED: a fresh detached application checkout at the exact accepted HEAD was
created under ignored `private/release-qualification/checkout`, with no existing
qualification containers or networks. Its private .env used project
`speech-platform-release-qualification`, loopback port 18086 and the staged model
store. Candidate uncommitted installer modules were imported from the working tree;
application source/config defaults/build context came from the clean checkout.
This distinction is explicit: a fresh checkout of the eventual candidate commit
is NOT ESTABLISHED until operator-authorized commit and rerun.

The first full install built all three images, ran actual container CUDA driver
probes (no model load), created only the isolated project's resources and passed
health/readiness. Synthetic core API checks passed:

| Check | Observed outcome |
| --- | --- |
| Public STT warmup | 200; 3.72s |
| Plain TTS with omitted new options | 200, valid 4.64s WAV; 81.63s including cold load |
| SSML + extra_high_quality + gentle | 200, valid 6.04s WAV; 17.46s |
| Synthetic audio transcription | 200, nonempty transcription; 4.71s |
| Invalid audio processing | sanitized 400 |
| Missing bearer token after isolated auth activation | 401 |
| Authenticated invalid mode | 400 |
| Local-only text transformation before LLM warmup | 200; 10.93s |
| Public local text warmup | 200; 10.11s |
| Local-only Swedish text transformation | 200; 10.09s; linguistic correctness not asserted |

A real selected-Gateway test exposed a singleton JSON Compose `ps` response that
was rejected by the readiness parser. The Gateway itself was healthy; the parser
was corrected to normalize a single object and a regression test was added.
The corrected scoped rerun and remove/reinstall evidence is recorded below.

No private generated text, token or audio payload is recorded here. Private logs
and synthetic WAVs remain in `private/release-qualification/`.

## GitHub Actions and versioning

OBSERVED via the GitHub connector: no run exists for local HEAD `7176248...`.
Latest inspected runs: `39771115876` on `e5706ba5...` failed; `39760874009` on
`18c456f7...` failed; earlier `39584052092` on `a6feae1e...` succeeded.
[Run 39771115876](https://github.com/azargarov/speech-platform/actions/runs/39771115876)
passed `make verify` and failed `make image` while installing CUDA TTS wheels with
`OSError: [Errno 28] No space left on device`. Candidate CI edits have not run on
GitHub; local inspection/tests are not equivalent to that run. SSH origin access
from this session was denied, but read-only GitHub API access succeeded.

Existing Git tags are v0.1.0, v0.1.1 and v0.1.2. Therefore this is the first full
SpeechPlatform product release, not literally the repository's first tag.
Recommend v0.2.0 after accepted changes are committed and main CI passes. Preserve
historical tags/descriptors. Tag publication will produce actual registry digests
and metadata for the exact source; no such new publication is claimed here.

## Limits and next gate

- Clean candidate commit checkout and candidate GitHub Actions execution remain
  pending; candidate commit is now authorized, but no push/tag is authorized.
- Published image/digest retrieval for the future tag and any descriptor generated
  from that publication remain unexecuted. Source-build install is the supported
  current product workflow.
- Ubuntu apt packages in images are not individually version pinned; source/base,
  Python locks and model hashes are pinned, but byte-identical rebuilds are not
  promised. Immutable published digests are the reproducible retrieval boundary.
- GPU headroom observations are not reservations or general coexistence guarantees.
- No paid cloud request or container vulnerability scan is claimed. Cloud adapter
  behavior is covered by deterministic mocks; local redacted gitleaks scans passed with reviewed exact exclusions; GitHub execution of that job is pending.

Final execution evidence and the readiness recommendation follow.

## Final observed execution

The scoped JSON parser correction passed its regression test and the real
Gateway-only install. A subsequent immutable-ID check exposed Docker containerd's
separate OCI index/attestation versus executable platform identities. The check
now validates the selected platform manifest when Docker exposes it, while
retaining config-ID checks for classic stores. Both formats and mismatch rejection
are tested. The real final Gateway-only rerun passed, including the network probe.

OBSERVED lifecycle qualification:

- TTS-only stop left Gateway and STT running. TTS install restored it without
  replacing Gateway/STT. STT-only install preserved Gateway/TTS identities.
- Full removal left zero qualification containers and zero qualification internal
  networks. External Ollama network, images, model artifacts and volumes remained.
- Full reinstall passed; a second install preserved all three container IDs,
  demonstrating convergence without unnecessary replacement.
- Reinstalled public TTS returned a valid synthetic WAV (74.11s including cold
  load); public STT warmup returned ready (3.88s). An explicit unsupported STT
  translation returned documented `400 unsupported_translation` (4.11s), without
  cloud fallback. Local Swedish text transformation had already passed separately.
- TTS reported unloaded after configured idle. STT logs showed ready → unloading,
  child exit code 0, then unloading → unloaded; Gateway remained ready. The first
  harness assertion incorrectly expected a direct ready → unloaded transition;
  inspection corrected the harness to the actual approved state machine, with no
  application change or repeat inference required.
- GPU sampled after TTS load: 5,816 MiB used / 9,094 MiB free. After final removal:
  174 MiB used / 14,736 MiB free. These are workload observations, not reservations.
- Qualification containers were removed after testing. Working Gateway/STT/TTS
  and shared Ollama matched the saved IDs, images, start times, restart counts and
  network sets. Working service health stayed healthy with zero restarts.

All isolated runtime images carried source revision
`7176248b55d3016f31e685da545aa03d98447a42`. Executable linux/amd64 manifests:

| Service | Platform manifest SHA-256 |
| --- | --- |
| Gateway | `c85eace0556337df0902c2dbe07acdf804b3493284f689802b82525bfca7cc42` |
| STT | `2b602235dfc847f52fe496c2cda166804c0b934f0ca983872cf18a4e78221bf9` |
| TTS | `2f9becf6fb741e8be840fa88a75b959ee6f265cbd6fe3aeaf720d7b404211f2c` |

The changed TTS provenance-label Dockerfile also built successfully as
`speech-platform-tts:release-qualification-candidate`, index ID
`8d92628e4a8bcfdfe483a863247d6d38e7c7013ba79b2144e12d11a60accfacf`.
It is explicitly labeled `uncommitted-qualification`, not a release source; it
was not deployed/published. Its lock label matched the tracked TTS lock digest.

OBSERVED registry metadata: all three historical v0.1.2 descriptor digest
references remained readable through `docker buildx imagetools inspect --raw`.
The health-only historical TTS descriptor was preserved. New TTS publication now
selects `voiceservice-tts-cuda`; no new remote digest or release is claimed.
The GitHub Releases collection returned no release objects; local Git tags exist.

Host tools observed: Python 3.12.3 and Go 1.24.0. The installer checks host Go
against `go.mod`; container/CI Go remains pinned separately to 1.27.2. New
preflight reports also check Docker storage when visible, not only checkout space.
Final working-stack Gateway preflight: PASS=26 WARN=2 FAIL=0 SKIP=4, READY TO INSTALL.
Final working-stack full preflight: PASS=31 WARN=5 FAIL=2 SKIP=1, NOT READY TO INSTALL;
the two failures remain the account's original model-reader access prerequisites.
The isolated accessible-store configuration passed install gates. No host group
membership or root permissions were modified.

## Security verification

Gitleaks 8.30.1 was downloaded into the ignored qualification workspace and
verified against its official release checksum
`551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`.
The initial scan identified two non-secret false positives: the test environment
variable identifier `M05B_TEST_MISSING_KEY` and a public Git commit ID in the
historical baseline's `api_source_revision`. The tracked `.gitleaks.toml` extends
default rules and excludes only those exact extracted values on their exact
file paths within the generic-api-key rule; it does not globally skip those files.
A same-path synthetic-token negative check confirmed other tokens remain detectable.
Reviewed history scan (63 commits) and candidate source scan passed with redacted
reports. Private data/.env/model directories were not exported into the candidate
source scan. Initial scanner findings/negative-test iterations remain private;
no actual credential finding was established.

Cloud validation tests cover disabled credentials, missing/enabled private files,
invalid values/reserved process names, and Gateway-only forwarding through rendered
Compose. Provider adapter/config tests use mocks; no paid inference was called.

## Verification commands and remaining release gate

- `make verify PYTHON=.venv/bin/python`: complete local suite, including Go race
  tests, script tests, STT tests, all 30 TTS tests, OpenAPI/config/Compose validation,
  lint, governance and lock checks: 555 script tests, 89 STT tests, 30 TTS tests
  and 2 governance tests; all passed.
- Focused prerequisite/installer, image-publication/tag-binding, release-descriptor
  and workflow-policy tests passed; actual isolated install/scope/remove/reinstall
  commands used `private/release-qualification/operate.py` to load candidate tooling
  against the clean pinned application checkout.
- `python -m compileall -q scripts services` and `git diff --check`: final checks.
- Earlier runtime qualification performed no commits/staging. On 2026-10-24 the
  operator authorized reviewing and committing this release candidate, with no
  push, tags, publication or working-stack replacement.

**Recommendation: NOT READY to tag the current working tree.** The implementation
is reviewable and isolated runtime qualification passed, but the candidate must be
committed after the authorized review and pass main/PR GitHub CI, including the disk-space fix,
before an approved v0.2.0 tag. Repeat the clean-checkout install from that exact
candidate commit to close the tooling/source qualification distinction. Resolve
model-reader access for this account before a full-stack install using the
original host store. Registry publication and any new immutable release descriptor
must use actual future tag metadata, never copied historical or invented digests.

An additional cached isolated full install/status/remove cycle passed after
environment isolation changes; subsequent Docker-context precedence, bounded
metadata probes and GPU-probe cleanup changes passed focused regression tests
and the complete verification suite. The final uniquely named CUDA probe also
passed and left no probe container. No inference was repeated in that cycle.
The source-drift regression blocks activation if HEAD/.env/private Gateway config
changes during a build. Secret-scan PR comments and artifact uploads are disabled;
CI only reports the scan result with the pinned scanner/configuration. All three
release image build jobs must pass before any publication job can start.

## Release-candidate commit review — 2026-10-24

The operator authorized review and commit of the 24 installation, CI, provenance,
test and documentation files. Review checked selected-service scope, source/image
identity, read-only prerequisite reporting, optional cloud credentials and shared
Ollama preservation. No worker inference logic or public API contract changed.

OBSERVED: `make verify PYTHON=.venv/bin/python` and the focused prerequisite,
product installer, publication, descriptor and workflow-policy suites were rerun
for the commit. Exact outcomes and the resulting commit ID are in the completion
report at `/tmp/report`; private execution logs remain under
`private/release-qualification/commit-*.log`. The configured Gitleaks scan covers
Git history and an export of exactly the staged files, excluding ignored data.

NOT ESTABLISHED: candidate execution on GitHub, and fresh-checkout installation
from the resulting candidate commit. These remain release gates. No push, tag,
publication or deployment is part of this commit task.
