# Batch STT and text-transformation qualification

The command inventory is in the [CLI reference](../cli/reference.md); this
document describes the batch operation's fixture flow and quality interpretation.

The batch CLI exercises existing WAV fixtures through the public Gateway. It
transcribes each WAV once using local STT with cloud audio consent disabled,
then sends that exact transcription to Written, Polite and Diplomatic modes.
Each mode is requested in `normal` format for `none` (same language) and both
other supported target languages. Calls are sequential; there is no cloud
authorization or fallback request.

The batch client omits the optional `model` field so Gateway chooses its
configured default. It does not pin or override a model alias; the JSON summary
records the model and provider returned for each successful transformation.

Run all discovered fixtures:

```bash
.venv/bin/python -m scripts.transform_samples
```

Run one case or explicitly regenerate its expected outputs:

```bash
.venv/bin/python -m scripts.transform_samples --case en-rude
.venv/bin/python -m scripts.transform_samples --case en-rude --regenerate
```

By default, output files are created beneath
`samples/transformed/<case-id>/`. The directory is Git-ignored. Existing output
files cause the run to stop before requests; `--regenerate` replaces only the
expected files, after each replacement has been fully written. It does not
remove unrelated files. If an operation fails, its output is not reported as
successful; files completed by earlier operations remain available for review.
New text files have mode `0600`.

Progress is written to stderr without source text, transcripts, transformed
text or credentials. A JSON summary is written to stdout with operation
statuses, HTTP status, serving provider/model when returned, duration, routing
settings, the Gateway prompt SHA-256 fingerprint, errors and missing output
paths. Exit status is nonzero when any
operation fails. The text results are evaluation artifacts, not quality
verdicts: inspect information, uncertainty, criticism, technical terms, numbers
and intent manually. No semantic equivalence is inferred from HTTP success.

Run offline coverage with:

```bash
.venv/bin/python -m unittest scripts.test_transform_samples -v
make verify PYTHON=.venv/bin/python
```

Live use requires the configured Gateway URL and API token in the existing
private configuration. This tool makes no direct calls to workers or Ollama.

## Manual text-fixture matrix

`test-transformation.sh` runs the nine checked-in text fixtures through
Written, Polite and Diplomatic modes using `local-qwen` (27 requests). To
include `groq-qwen` and `groq-gpt-oss` as well (81 requests total, including 54
cloud requests), pass the explicit cloud opt-in:

```bash
./test-transformation.sh
./test-transformation.sh --allow-cloud
```

It uses `scripts.qualify` for every request and stores reports/evidence under
`samples/out/`, which is Git-ignored. Generated text is printed to the
terminal; handle terminal output and artifacts as sensitive. This is a
technical matrix runner, not a semantic quality verdict.
