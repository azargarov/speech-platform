# Gateway qualification CLI

Run a single request from the repository root with `.env` configured with the Gateway URL and API token:

```sh
.venv/bin/python -m scripts.qualify stt --audio private/audio/sample.wav
printf '%s' 'Synthetic text for rewriting.' | .venv/bin/python -m scripts.qualify transform --mode written --format normal
.venv/bin/python -m scripts.qualify transform --text 'Hej.' --target-language en --mode written
.venv/bin/python -m scripts.qualify tts --text 'Synthetic speech.' --output private/audio/qualified.wav
```

STT defaults to the local provider. Groq audio requires both `--provider groq` and explicit `--allow-cloud-audio`. Text transformation defaults to `local_only=true`; `--allow-cloud` explicitly permits configured cloud routing but cannot override Gateway policy. Translation is text transformation with `--target-language`. Raw mode requires normal formatting. Use `--text-file` or stdin to avoid placing sensitive input in shell history. `--timeout` is a client wait bound, not a server processing duration.

Each invocation prints a short content-free result. `--report private/reports/run.json` writes an optional JSON report using exclusive creation and mode 0600. The stable top-level fields are `schema_version`, `operation`, `request`, `http`, `elapsed_seconds`, `error`, `response`, `outcome`, `technical_checks`, and `artifact`. `request.input` contains sizes only; response text is not included. `--evidence private/reports/evidence.json` explicitly stores request/response text for STT and text operations; protect and delete it when no longer needed. TTS WAV is inspected in memory and discarded unless `--output` is given. Evidence and WAV outputs must be under an existing `private/` directory and are never overwritten.

All requested output destinations are canonicalized and checked for collisions before an API request. Output creation or writing failures return exit code 3. If a WAV or evidence artifact was successfully written before a later evidence/report write fails, the CLI does not remove that completed artifact; inspect and remove it manually if needed. A partial file from a failed write is removed when possible; if cleanup itself fails, the error states that a partial file may remain.

The CLI checks protocol success and deterministic response properties. It does not score semantic preservation or linguistic quality. Live qualification requires separate authorization and must not be inferred from offline tests.
