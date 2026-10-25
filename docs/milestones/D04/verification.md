# D04 — Verification Record

Date: 2026-10-25. Repository: `/home/master/speech-platform`.

## Initial state

**OBSERVED:** Git HEAD was `2bfc0089cf8282b4fad9b20914ac1bc0128a7915`.
The worktree initially contained uncommitted D03 closeout documentation. That
documentation was reviewed and committed separately as
`ebd45115766fcefe7049ad29eeae2327c315aa3e` before the D04 implementation
commit; it contains no D04 source changes.

## Offline checks

**OBSERVED:**

- Focused Ruff and tests: `ruff check scripts` PASS; final
  `unittest scripts.test_api_smoke scripts.test_preflight scripts.test_tts_model -v`
  PASS (43 tests).
- `make -n` validation rendered `init`, `preflight`, `install`, `status`,
  `logs`, `stop`, `test-stt` and `test-tts`. `gpu-check`, `remove` and `plan`
  each returned “No rule to make target”, as expected after retirement.
- Active code/Makefile reference search found no references to the removed
  modules or their symbols. Remaining mentions occur in historical evidence or
  explicitly superseded ADR text.
- `make verify PYTHON=.venv/bin/python` PASS (exit 0): Ruff check/format, Go
  vet/race tests/build, Compose configuration checks, release and dependency
  lock validation, 274 script tests, 92 STT tests, 63 TTS/SSML tests, and
  governance validation (2 tests).
- `git diff --check` PASS; `make governance-check PYTHON=.venv/bin/python` PASS
  after the final documentation edits (validator plus 2 governance tests).
- The first focused test run had two test-harness failures: a case-sensitive
  expected-message assertion and a fixture using the function's bound default
  repository path. Both tests were corrected; no production behavior was
  involved, and the focused rerun passed all 42 tests.

## Initial live regression attempt

The first D04 deployment attempt occurred after this original check and is
recorded below.

**Earlier BLOCKED observation:** before the operator authorized the D04 commit,
`python scripts/deploy_images.py source` exited 2 with
`make install requires a clean Git worktree`. No install/restart command was
run at that point. The operator has since authorized the separate D04
implementation commit and live regression.

## D04 deployment and D04B live qualification

**OBSERVED:** D04 implementation commit was
`9ef27aed39056c6c5eab693801a30c2aee1c6d78`. Before replacement, exact running
Gateway/STT/TTS image objects at source `2ec766855c5c355bd312c47bb79549cf99c80b1f`
were present and retained by exact image ID. The compatible D03 private
configuration bundle at
`private/deployment-backups/d03-rollback-20261025T110233Z/` was present; its
directory was mode 0700 and `.env` mode 0600. Environment key names matched
the active configuration; secret values were not displayed.

**OBSERVED:** `sg stt-model-reader -c 'make preflight PYTHON=.venv/bin/python'`
reported PASS=34, WARN=1, FAIL=0, SKIP=2 and READY TO INSTALL. The one warning
was fresh internal networking, subsequently verified by ready health checks.
Cloud inference was skipped because no cloud provider was enabled.

**OBSERVED:** `sg stt-model-reader -c 'make install PYTHON=.venv/bin/python'`
passed. Gateway, STT and TTS images built and identity checks passed; both CUDA
container probes passed. Compose recreated only the three SpeechPlatform
containers, which became healthy and ready. The D04 source revision and image
IDs were:

| Service | Container | Image ID | Source revision | Restarts | Health |
| --- | --- | --- | --- | ---: | --- |
| Gateway | `b30754afeb46` | `sha256:4dfae8feff1af02c91ba59f064952d8486f66643cfdaa44abcbe9f105905ee2f` | `9ef27aed39056c6c5eab693801a30c2aee1c6d78` | 0 | healthy |
| STT | `68cd2ab1e47a` | `sha256:90c2db7a74dc3d4dc8801ef6137a6162b586602fa663a074280cf431ae90c1ca` | `9ef27aed39056c6c5eab693801a30c2aee1c6d78` | 0 | healthy |
| TTS | `121eda1cf527` | `sha256:51416bc0b656e855c64c058a5cdd1afa035141bc52cd3cf123b556b0920895fa` | `9ef27aed39056c6c5eab693801a30c2aee1c6d78` | 0 | healthy |

**OBSERVED — initial smoke CLI defect:** invoking `scripts/api_smoke.py`
directly from Make failed with `ModuleNotFoundError: No module named
'scripts'` before opening an HTTP connection. No inference request was sent.

**OBSERVED — D04B fix:** commit
`fd0518e75a96f94390fdd7c049043f0bb59f5de4` changes both Make targets to
`$(PYTHON) -m scripts.api_smoke`. Focused tests execute the STT and TTS module
CLI help paths from the repository root and verify Make's rendered target
commands. Focused smoke tests passed (7 tests), Ruff check/format passed,
group-context module CLI checks passed, `make verify PYTHON=.venv/bin/python`
passed, and `git diff --check` passed.

**OBSERVED — authenticated STT smoke:** one request through the fixed
`make test-stt` command returned successfully in 5.339 seconds. Safe response
metadata was `detected_language=en`, `source_language=en`,
`output_language=en`, `translated=false`. Transcript was nonempty (291
characters) and remains in a private mode-0600 temporary capture; it is not
included here.

**OBSERVED — authenticated TTS smoke:** one synthetic request through the
fixed `make test-tts` command completed in 94.888 seconds. The private WAV is
291,884 bytes, mode 0600, duration 3.04 seconds, mono, 48 kHz, PCM signed 16-bit.

**OBSERVED — service and isolation checks:** post-smoke `make status` reported
all three services healthy on the exact source and image IDs above. Their
restart counters remained zero. Gateway `/healthz` and `/readyz` returned HTTP
200. Shared Ollama remained container
`72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba`, on the same
image, running with zero restarts. Unrelated container identities, network
IDs and volume names matched the pre-install inventory. Active Gateway
configuration has `allow_cloud=false`; neither smoke client contacted a cloud
provider. The existing stopped `adoring_cerf` container was present before and
after and was not changed.

**INTERPRETATION:** these single-request smokes establish local API operation
for the observed inputs only. They do not qualify sustained load, simultaneous
STT/TTS, LLM/TTS GPU contention, language accuracy or cloud inference.

## Final code reduction

**OBSERVED:** D04 implementation commit `9ef27aed39056c6c5eab693801a30c2aee1c6d78`
has 2,806 code/Makefile deletions and 483 insertions, net reduction 2,323
lines. D04B is a separate 49-insertion, 2-deletion Makefile/test commit.
