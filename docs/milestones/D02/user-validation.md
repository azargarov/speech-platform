# D02 — User Validation

## Validation requested

Review the Make + Compose deployment path and its migration behavior. In
particular, review the reported obsolete Gateway image-pin blocker before any
private `.env` edit or live deployment.

## Current status

Operator authorized the D02 fix commit and live target-host qualification on
2026-10-25. Qualification passed: all three services run the committed images
and authenticated local STT/TTS smoke checks succeeded. The operator accepts
D02 and approves closeout on 2026-10-25.

The obsolete image pins were removed after backup. The model-store traversal
check was corrected without changing permissions or ownership. The authorized
install rebuilt and replaced only the SpeechPlatform Gateway, STT and TTS
services. Exact previous images and a private configuration backup were
retained before replacement; backup compatibility is not established.
Authenticated smoke checks passed using
synthetic/local data; no cloud inference occurred. Recovery preparation is not
rollback execution: the render-checked command does not explicitly select the
retained image IDs, and compatibility of the pre-migration `.env` backup with
the new deployment path is NOT ESTABLISHED. See [verification](verification.md)
for image identities and results. D02 is accepted and closed; D03 is next
planned and has not started.
