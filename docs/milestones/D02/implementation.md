# D02 — Implementation Record

## Changes

- Added a bounded Compose command wrapper (`scripts/compose.py`) that fixes the
  project and Docker context, sanitizes the environment, selects the existing
  Ollama overlay only when configured, verifies project ownership before service
  operations, and rejects unsupported/destructive commands.
- Added focused installation checks (`scripts/deploy_images.py`) for a clean full
  Git revision, current Compose-owned container identity, exact-image rollback
  tags, built-image labels/platform, isolated CUDA driver/device access, running
  image identity, and status reporting.
- Changed Make targets so `install` builds and updates all three services in
  order; `status`, `logs`, and `stop` use only the supported Compose project.
  The old product installer and its tests remain available as fallback.
- Fixed root Compose project identity and removed obsolete image-pin examples.
- Updated installation/runbook guidance and added mocked deployment tests.
- Updated preflight to ignore ambient Docker/Git selection overrides, enforce the
  local default Docker context and fixed project, and reject legacy Gateway
  image pins with a specific migration message.

## Preserved boundaries

Preflight stays read-only. Installation does not rewrite `.env`, rotate tokens,
download models, call cloud providers, or alter Ollama. The only Docker removal
performed by the CUDA probe helper is cleanup of its own uniquely named probe
container. `make stop` uses Compose stop and preserves resources.

## Deviations and limitations

- D02 target-host qualification was not performed. The existing private `.env`
  contains `GATEWAY_EXPECTED_IMAGE_ID` and
  `GATEWAY_EXPECTED_SOURCE_REVISION`; preflight rejects both until manually
  reviewed and removed. Private configuration was not changed.
- The new installer requires clean committed source. The working-tree changes
  are uncommitted and no commit was authorized, so install correctly was not
  attempted.
- No image build, CUDA probe, container replacement, inference, or smoke test was
  performed in this implementation pass.
- `scripts/product_deployment.py` remains the fallback; D02 does not retire it.
