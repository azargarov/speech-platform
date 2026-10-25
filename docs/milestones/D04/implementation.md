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
- Updated active installation guidance and ADR-0023. Historical milestone
  reports and explicitly historical deployment procedures remain unchanged.
- Reconciled D03 records as operator accepted, following the operator's explicit
  closeout statement. D03 remains distinct from D04's pending qualification.

## Size

The four deleted Python files contained 2,367 lines. Across the removed
modules/tests, Makefile, preflight and its focused tests, TTS artifact test, and
the new 342-line smoke client/test, the net source/test/Makefile reduction is
2,348 lines. Documentation lines are excluded from this count.
