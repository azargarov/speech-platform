# TTS worker operations

M03B adds VoxCPM2 to the existing `tts` service in the root `compose.yaml`.
The worker has no published host port and is reachable only from the Gateway
over the internal `tts_private` network. It runs as UID/GID 65532 with a
read-only root, read-only config/model mounts, no capabilities and no runtime
model downloads.

## Model artifact

The pinned artifact manifest is
[`releases/artifacts/voxcpm2.yaml`](../../releases/artifacts/voxcpm2.yaml); its
canonical SHA-256 is configured as `TTS_MODEL_MANIFEST_SHA256` in `.env`. The
model store layout is
`$TTS_MODEL_STORE/<manifest-sha256>/{artifact,manifest.yaml}`. By default,
`TTS_MODEL_STORE` uses `MODEL_STORE`, matching the existing content-addressed
STT model convention. For a user-owned store, check or explicitly fetch it
with:

```sh
make tts-model-check TTS_MODEL_STORE=/srv/speech-platform/models
make tts-model-fetch TTS_MODEL_STORE=/srv/speech-platform/models
```

Fetching is a separate network operation. The worker itself is offline. Keep
the model files outside Git and do not change the pinned manifest digest
without reviewing the model revision and hashes.

For the protected root-owned store, run the pinned check, fetch, then check as
root with `stt-model-reader` as the primary group. This preserves the store's
existing `root:stt-model-reader` ownership and `2710` mode; it does not change
the store root's mode. Its parent `/srv/speech-platform` may remain
`root:root` mode `0711`; the parent does not need the reader group. The
provisioner checks the parent path for real directories, symlinks, unsafe
writable components and trusted ownership. It stages the digest directory as
mode `2750` and files as `0640` for the worker's reader group.
Run the first check separately; if it reports only that the artifact is not
cached, run fetch and then the final check. Stop on hash, ownership, or other
permission errors instead of changing store permissions.

```sh
sudo -u root -g stt-model-reader .venv/bin/python -m scripts.tts_model check \
  --store /srv/speech-platform/models --reader-gid 988 --owner-uid 0
sudo -u root -g stt-model-reader .venv/bin/python -m scripts.tts_model fetch \
  --store /srv/speech-platform/models --reader-gid 988 --owner-uid 0
sudo -u root -g stt-model-reader .venv/bin/python -m scripts.tts_model check \
  --store /srv/speech-platform/models --reader-gid 988 --owner-uid 0
```

The fetch downloads only the exact revision and files in the pinned manifest,
then verifies each file hash before activating the content-addressed directory.
An existing verified digest is reused. Do not recursively change ownership or
permissions on the model store.

## API and modes

`POST /v1/tts/speech` accepts JSON `{ "text": "...", "language": "auto" }`
and returns complete `audio/wav` PCM16. Plain text is limited to
10,000 Unicode characters and the JSON body to 64 KiB. `language` is `auto`,
`en`, `ru` or `sv`; auto passes multilingual text without language metadata.
Explicit codes add a model instruction hint. The service does not return a
detected language code. Optional compatibility `voice` accepts only `default`.

### Minimal SSML input

Set `input_format` to `ssml` explicitly; omitted or `text` input is never
interpreted as XML. SSML input uses the W3C namespace
`http://www.w3.org/2001/10/synthesis`, requires a `<speak version="1.1"
xml:lang="...">` root, and supports only nested `<lang xml:lang="...">` and
`<break time="..."/>`. For example:

```xml
<speak xmlns="http://www.w3.org/2001/10/synthesis" version="1.1" xml:lang="en-US">
  Hello, <break time="250ms"/><lang xml:lang="sv-SE">hej</lang>.
</speak>
```

`xml:lang` accepts `en`, `ru`, `sv` and their two-letter regional tags (for
example `en-US`, `ru-RU`, `sv-SE`). Language values inherit through nesting;
an inner `lang` overrides its parent. Regional subtags map to the existing
base language hint. They do not select a guaranteed accent and do not report
detected language. With SSML, request `language` must be omitted or `auto`.

Break times accept integer `ms` or decimal `s` with at most three fractional
digits. They are converted to exact 48 kHz frame counts. Adjacent breaks remain
separate in document order. Whitespace-only XML formatting nodes are ignored;
non-whitespace text, including spaces adjacent to inline elements, is retained.
Any other element or attribute, malformed XML, DTD or entity declaration is
rejected with a structured error. External resource resolution is not used.

The worker configuration bounds an SSML document to 49,152 UTF-8 bytes, speech
to 10,000 characters and 64 segments, nesting depth to 16, and markup elements
to 256. A break is at most 10 seconds and requested total silence is at most
30 seconds by default. Before inference, an estimate based on text characters,
segment count and silence must fit the configured 64 MiB output budget; the
composed audio is also checked against that hard byte limit. The estimate is a
protective heuristic, not a duration guarantee. Limits are validated by the
worker configuration loader.

Each speech segment uses the existing serialized model lifecycle and selected
TTS mode. The worker holds segments in memory and returns one mono PCM16 48 kHz
WAV only after every segment succeeds. A failed segment returns an error and
does not expose earlier audio as a successful partial result. Native inference
is not interrupted mid-call on client disconnect; existing lifecycle draining
semantics remain in effect. This is a limited, provider-backed subset, not
full SSML 1.1 support.

`quality` uses 10 diffusion steps and is the default. `auto` selects the same
configuration. `fast` uses eight steps and `high_quality` uses 16 steps.
`extra_high_quality` selects 32 steps. It is opt-in and does not change the
default. Higher step counts are not assumed to sound better without listening
comparison.
The operator accepted the tested eight-step samples and selected 16 steps as
an additional quality option after listening to the 10-, 12- and 16-step
comparison. In the single seeded experiment, mean generation latency and
weighted RTF were 10.35 s / 2.249 at 10 steps, 10.26 s / 2.352 at 12 steps,
and 14.40 s / 2.976 at 16 steps; peak CUDA allocation/reservation was 5,458.5 /
5,690 MiB for each setting. These are experimental measurements from four
inputs on the RTX 5000, not latency guarantees. Full provenance is recorded in
[M03 verification](../milestones/M03/verification.md). Generation is not real-time and
may take longer than the audio duration. The default Gateway deadline is ten
minutes; timeout/disconnect drops the response but does not kill active native
inference. The model unloads after 60 idle seconds to return GPU memory to STT.

The optional public `audio_processing` request field accepts `none` (default)
or `gentle`. `gentle` runs a fixed FFmpeg chain on the completed WAV: conservative
whole-program EBU R128 normalization toward -18 LUFS, 1.5:1 compression with
20 ms attack and 250 ms release, and peak protection. The two-pass FFmpeg work
has a 30-second total deadline and uses the configured WAV byte limit. Silence
and near-silent output bypass processing; digital silence in SSML is preserved.
Because the complete programme is processed as one unit, this does not perform
independent phrase-level level matching. It retains phrase-to-phrase loudness
differences while avoiding one FFmpeg process per SSML segment. FFmpeg failures
return structured errors; temporary WAV files are removed on success, failure
or timeout. The default `none` path does not invoke FFmpeg.

The Gateway accepts four concurrent API requests; the TTS worker admits one
inference at a time and returns 429 when occupied. Requests are not queued.
The model loads on first synthesis, can be loaded through the private
`/internal/v1/warmup` route, and reports `loaded`, `unloaded`, or `loading` at
`/internal/v1/state`. The idle timer unloads it after the configured interval
once inference is inactive. Restarting the worker starts unloaded and the next
request loads it again.

## Resource and recovery behavior

The TTS worker uses the configured NVIDIA device, requires a point-in-time
8 GiB free-VRAM check before model load, and limits its CUDA allocator to the
configured fraction. These checks do not reserve memory or guarantee
coexistence with STT. STT/TTS simultaneous inference performance remains
unestablished. A CUDA memory error returns a structured 503 and releases the
TTS model allocation for a later retry; no retry loop is started.

Compose bounds TTS CPU, container memory, PIDs and shutdown grace separately
from STT. Process health reports liveness; readiness reports that the worker
can accept a request while its model may still be unloaded. The first request
includes cold load time. Explicit warm-up can be requested on the private
worker network by an operator; it does not change the public contract.

Text and generated audio are not logged or retained. Audio is encoded in
memory. The worker uses a bounded temporary cache under a container tmpfs.
Production licensing review remains open, and sustained-load capacity is not
established. This guide records the implemented M03B behavior, not unrestricted
production readiness.
