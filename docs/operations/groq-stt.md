# Optional Groq STT

Groq STT is an optional Gateway provider. It is disabled by default; ordinary
STT requests therefore remain local and do not transmit audio outside the
host.

To enable it, set the Gateway configuration:

```yaml
groq_stt:
  enabled: true
  capacity: 2
  model: whisper-large-v3-turbo
  api_key_env: GROQ_STT_API_KEY
```

Add `GROQ_STT_API_KEY=<secret>` to the private Gateway secrets file selected by
`GATEWAY_SECRETS_FILE`. The Gateway rejects enabled configuration when the
credential is missing or malformed. The key is independent of `GROQ_API_KEY`
for text transformation. With Groq disabled, no key or network access is
required.

Every request sent to Groq also requires `X-Allow-Cloud-Audio: true`. The text
transformation `allow_cloud` option does not authorize audio. `X-STT-Provider:
local` pins a request to local Faster-Whisper; `X-STT-Provider: groq` pins it to
Groq and is rejected without the consent header. When the provider header is
omitted, requests are local-only unless the consent header is true. A
consenting request prefers local admission and can use Groq when local capacity
is occupied. After a provider has accepted a request, its failure is returned;
the request is not automatically sent to another provider.

The Gateway configures one local operation and up to two Groq operations, with
a total of two active STT operations across providers. Three requests may wait
in the existing bounded FIFO queue. Uploads are read only after provider
admission. This is a memory-conscious request-count bound, not a GPU memory
reservation or guarantee of coexistence with TTS, Ollama, or other host users.
At the 25 MiB request ceiling, a conservative transient estimate for two
simultaneous Groq uploads is about 114 MiB for bounded multipart buffers plus
parsed audio copies. Adding a maximum 64 MiB TTS response and up to 8 MiB for
two bounded STT worker/provider response and mapping buffers gives roughly
186 MiB before Go runtime, HTTP and allocator overhead. This leaves nominal
headroom under the default 256 MiB Gateway limit but is not a measured RSS cap;
offline Stage A does not establish capacity under stress.

The current adapter supports WAV, FLAC, MP3, Ogg, and M4A/MP4 audio; `auto`,
English, Russian, and Swedish transcription; and optional segment timestamps.
It rejects streaming, non-empty explicit model selection, and cross-language
translation. It does not call Groq's separate translation endpoint, accept
remote audio URLs, retry automatically, or log/persist audio. Rate limits map
to 429; provider timeouts to 504; unavailable or rejected provider calls return
sanitized errors.

Sending authorized audio to Groq transmits it outside SpeechPlatform. Groq's
documentation says inference data is not retained by default, while temporary
input/output retention may occur for reliability or abuse investigation for up
to 30 days. Review organization data controls, including Zero Data Retention,
and applicable privacy requirements before enabling it. See the [Groq
transcription API](https://console.groq.com/docs/speech-to-text) and [data
controls](https://console.groq.com/docs/your-data).

## Qualification evidence (2026-10-24)

The operator-authorized comparison used only `private/audio/english1.wav`,
`private/audio/english.wav`, and `private/audio/russian.m4a`. The original bytes
were sent to local Faster-Whisper and Groq; Groq Turbo and Large v3 were each
compared on all three inputs. All eleven bounded requests, including one
simultaneous local/Groq pair, returned HTTP 200 with expected language and
provider provenance. No retries were made. Pairwise outputs were highly
concordant, but no verified reference transcripts were available, so accuracy
remains unverified and WER/CER were not calculated. Groq Turbo was faster than
Large v3 on each sample and remains the configured optional default for latency
reasons, not an accuracy claim. Local Faster-Whisper remains the default
provider.

Observed GPU usage rose from 174 MiB to a sampled peak of 2,450 MiB and returned
to baseline; this was a single workload observation, not a capacity guarantee.
Gateway, STT and TTS stayed healthy without container restarts. Account-specific
Groq retention and Zero Data Retention settings were not inspected and remain
unverified. Exact transcripts and audio stay in ignored private qualification
artifacts and are deliberately omitted here.
