# D04 — Implementation Record

## Design

The existing `preflight.py`, `compose.py` and `deploy_images.py` remain the
deployment boundary. Removed code is not replaced with orchestration. Read-only
Ollama validation remains in preflight; the old module's network create/connect
behavior is retired. An independent standard-library Gateway smoke client keeps
the existing STT API test path and adds an equivalent bounded TTS smoke path.

## Changes

- Removed the legacy product installer and its installer-specific tests, plus
  the unused Ollama network mutator and its tests.
- Removed obsolete Make targets and the `NO_BUILD` forwarding logic. Existing
  `make init`, `preflight`, `install`, `status`, `logs` and `stop` remain.
- Kept the existing TTS manifest digest as the artifact source of truth rather
  than importing it from deployment code.
- Retained preflight's read-only Ollama network/model checks and moved its small
  resource-name validation into `preflight.py`.
- Added an independent authenticated Gateway smoke client for STT and TTS.
  STT retains its existing local-audio request and terminal output behavior;
  TTS writes a new mode-0600 WAV only under `private/`.
- D04B changed both Make smoke targets to run `python -m scripts.api_smoke`.
  Focused tests execute both module CLI help paths and verify the Make target
  commands. This fixes the direct-script import failure without path mutation.
- Updated active installation guidance and ADR-0023. Historical milestone
  reports and explicitly historical deployment procedures remain unchanged.
- Reconciled D03 records as operator accepted, following the operator's explicit
  closeout statement. D03 remains distinct from the D04 qualification that was
  pending at the time of that closeout.

## Size

The four deleted Python files contained 2,367 lines. The committed D04
source/test/Makefile diff is 2,806 deletions and 483 insertions, a net
reduction of 2,323 lines. Documentation lines are excluded. The separate D04B
CLI fix adds 49 lines and deletes 2 lines across the Makefile and focused
smoke-client tests; it is not part of the D04 implementation reduction tally.
