# M04 user validation

Status: **PASS — operator acceptance recorded (2026-10-22).**

## Planned review

Review the private English–Swedish vocabulary sample created through the
canonical loopback Gateway. It speaks “Good morning,” pauses for 500 ms, then
speaks “God morgon” under `sv-SE`, using the accepted `fast` mode. The exact
SSML, request status and WAV metadata are recorded in
`private/m04/live-20261022/request-metadata.json` (ignored by Git). The WAV is
`private/m04/live-20261022/english-swedish-fast.wav`, SHA-256
`493ca62e405120b6ad39158aa3eeeb74edf5c6db4515ed9e4c6b89e43e00f9e8`;
mono PCM16, 48 kHz, 2.58 seconds. Both files are stored only under ignored
`private/m04/` with private directory/file permissions.

The operator should assess speech quality, word correctness, language
The operator approved M04 following successful technical validation and
review of the English–Swedish sample. This records acceptance of the agreed
sample and bounded M04 scope. SSML language tags remain context hints and do
not promise accent selection or native language detection. The support remains
a partial SSML 1.1 subset. Cold-start latency, production licensing and
sustained-load behavior remain limitations and are not established by this
sample review.

The operator explicitly approved M04 closeout and a local commit of the
completed changes. Push, tagging, redeployment and starting another milestone
were not authorized.
