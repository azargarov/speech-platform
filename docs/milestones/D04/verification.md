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

## Live regression

Read-only production preflight under `stt-model-reader` passed with PASS=33,
WARN=2, FAIL=0, SKIP=2, and reported READY TO INSTALL. Warnings were fresh
internal networking (verified by post-start checks) and uncommitted source
(commit reviewed changes before installation). Read-only `make status` showed
Gateway, STT and TTS healthy at source `2ec766855c5c355bd312c47bb79549cf99c80b1f`.

**Earlier BLOCKED observation:** before the operator authorized the D04 commit,
`python scripts/deploy_images.py source` exited 2 with
`make install requires a clean Git worktree`. No install/restart command was
run at that point. The operator has since authorized the separate D04
implementation commit and live regression; final live results will be appended
after the committed clean-tree installation.
