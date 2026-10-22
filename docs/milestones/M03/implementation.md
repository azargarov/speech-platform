# M03 implementation and evaluation record

Status: **M03A closed for bounded evaluation and selection. M03B PASS and COMPLETE for its agreed implementation and technical-validation scope on 2026-10-22. Operator acceptance covers fast (8 steps), quality (10 steps, default), high_quality (16 steps), and auto (quality mapping). Production licensing, cold-start latency, and sustained-load limitations remain; see [result.md](result.md).**

## Work recorded

- Preserved the M03A/M03B boundary and the existing Gateway, STT, and TTS service responsibilities.
- Reviewed the exact pinned VoxCPM2 and MOSS-TTS-Nano source, model, tokenizer, and auxiliary asset revisions for private local evaluation. Candidate decisions and production blockers are recorded in [verification.md](verification.md) and in the ignored private record.
- Built a disposable offline evaluation image with pinned PyTorch 2.7.0+cu128 and Transformers 4.57.1. The candidate containers ran as UID 1000 with no network, read-only root and model/source mounts, dropped capabilities, no-new-privileges, bounded CPU/memory/processes, and only private output mounts writable.
- Generated nine samples per cleared candidate from the frozen synthetic prompts. VoxCPM2 used reference-free voice design and MOSS used reference-free continuation; no built-in demo recording or personal reference audio was used.
- Recorded model-load time, generation time, audio duration, CPU time, peak RSS, cgroup memory peak, sample format, file size, and guarded host GPU state. Prepared a randomized blind listening manifest with a separately stored candidate key.
- Kept Piper blocked. No M03B code, public contracts, deployment configuration, running services, production model selection, commit, tag, or push was changed or created.

## Aborted setup attempts

- The first MOSS run generated one WAV, then stopped before recording a screening row because the private runner's CSV field list omitted `cgroup_peak_mib`. The artifact and reason are preserved under `private/m03a/M03A-20261021-01/aborted/moss-runner-metadata-error/`. The runner metadata list was fixed and the full nine-sample run then completed.
- The first VoxCPM2 container launch used the repository root rather than its `src/` directory as `PYTHONPATH`; it stopped before model load or GPU inference. The launch path was corrected and the full screen completed. The failed launch record is in the private results directory.

## Boundaries and deviations

Only ignored private evaluation artifacts and milestone documentation were changed. No Speech Platform service source, contract, deployment, or live container was changed. No untrusted serialized object was directly unpickled; MOSS used the pinned Transformers safe state-dict loader in the isolated offline container. MOSS production licensing remains blocked, and neither candidate has an operator listening verdict or production selection. See [verification.md](verification.md) for evidence classification and [result.md](result.md) for current milestone state.

## Round 2 work — 2026-10-21

- Used only the Round 1 pinned artifacts and rechecked the four required large artifact hashes; no checkpoint or voice asset was acquired.
- Built the same disposable evaluation image from the already approved pinned recipe; build dependency layers were cached. Ran MOSS first on CPU, then VoxCPM2 on GPU after a seven-observation preflight. Both candidates used fresh disposable, network-disabled containers and private attempt outputs.
- Generated 3/3 MOSS reference-free continuation samples and 9/9 VoxCPM2 reference-free voice-design samples. VoxCPM2 used neutral, warm/unhurried, and bright/lively natural-language instructions. Other model parameters stayed fixed within each candidate.
- Created the six requested language/model output categories with configuration subdirectories, adjacent JSON metadata, a flat blinded listening manifest, and a separate mapping key. Round 1 ratings are summarized by language/model; the original blind IDs and unrated sample were preserved.
- A MOSS startup initially stopped before model load because the Transformers cache defaulted to a read-only home. The next fresh invocation used `/tmp` tmpfs for its cache and generated each requested MOSS sample once. No automatic sample retries occurred. VoxCPM2 startup emitted tokenizer-class and `weight_norm` deprecation warnings; all samples completed successfully.
- No model was selected. No M03B, production use, service deployment, push, or tag was performed. Full record: `private/m03a/M03A-20261021-02/results/run-report.md`.


## M03A focused performance and language follow-up — 2026-10-21

- Reused only the previously pinned VoxCPM2/MOSS source and staged model artifacts. No model or reference audio was downloaded. Added a private attempt record at `private/m03a/M03A-20261021-03/`.
- Built a disposable network-disabled inference image with the existing pinned PyTorch 2.7.0+cu128 and Transformers 4.57.1 recipe. Runtime mounts were read-only except private attempt output and temporary `/tmp`; containers ran non-root with dropped capabilities, no-new-privileges, resource limits, and candidate-only stop monitoring. Images and stopped containers were removed after the run; private audio/logs/reports remain ignored.
- Compared VoxCPM2 baseline (`optimize=False`, 10 inference timesteps) with one generation-parameter candidate (`optimize=False`, 8 timesteps): one excluded warm generation and three timed repetitions for each fixed English, Russian, and Swedish text/configuration. Exact input, generic neutral voice description, seed, precision, CFG, and other settings were held fixed.
- Investigated the wrapper's documented `optimize=True`/`torch.compile` option. It did not yield a timed sample: initial disposable cache setup failed, then Triton reported unsupported native BF16 compilation on the Quadro RTX 5000 and a missing `Python.h` header. Attempt outcomes and the retained final traceback are recorded under the private follow-up results; two intermediate container logs were overwritten on retry. No checkpoint precision or model dependency was changed.
- Generated 11 text-only language cases for each model: normal, short ambiguous, and proper-name/borrowed-word case for English, Russian, Swedish, plus two mixed-language diagnostics. VoxCPM2 received direct text with no voice description; MOSS used reference-free continuation and the existing fixed sampling settings. All 22 requests completed.
- Did not assign automatic speech-quality or language judgments. Each generated-language observation remains pending operator listening. No subjective quality score, model selection, M03B implementation, production deployment, commit, push, or tag was made.
- Detailed reports, sample rows, and audio are in `private/m03a/M03A-20261021-03/results/performance-report.md`, `language-report.md`, `performance-samples.csv`, and `language-cases.csv`.

## M03A operator closeout — 2026-10-21

- Recorded the operator's final listening assessment and selected VoxCPM2 for
  initial M03B integration. MOSS-TTS-Nano is not selected; the operator found
  pure English acceptable and Russian, Swedish, and mixed-language speech
  unsatisfactory.
- Retained the 10-step measured configuration as quality baseline. The
  8-step configuration remains a speed candidate only; it reduced measured
  wall time 7.5% and weighted RTF 11.3% while rendered audio duration rose
  4.3%, and quality parity was not established.
- Recorded that neither pinned model API exposes a native detected language
  code and that VoxCPM2 synthesized multilingual text without explicit
  language metadata.
- M03A closeout is limited to bounded evaluation and candidate selection. It
  does not imply production licensing acceptance, production quality
  acceptance, deployment, or M03B completion.

## M03B implementation and live validation state — 2026-10-22

The Gateway contract/proxy, Python VoxCPM2 worker, pinned model artifact
manifest, content-addressed model provisioning, dedicated CUDA image, canonical
Compose wiring, Make targets, operational notes, and automated regression
coverage are implemented. `make verify PYTHON=.venv/bin/python` passed.

The pre-fast Gateway and TTS images lacked the approved mode implementation.
For final validation, Gateway was rebuilt from current source and TTS was
created as a thin source overlay on the existing pinned CUDA image, reusing its
locked PyTorch/CUDA/VoxCPM runtime and model. Only Gateway and TTS were updated
with Compose `--no-deps`; the running STT container and unrelated projects were
preserved. The new live request samples and a rollback image/config overlay are
under ignored `private/m03b/live-final-20261022/`. Detailed commands and
observations are in [verification.md](verification.md).

M03B implementation and technical live validation pass. The operator's final
live high_quality listening acceptance and explicit closeout approval are
recorded in [user-validation.md](user-validation.md). Production licensing is
not fully cleared; this bounded validation does not imply unrestricted
production readiness.

## M03B fast-mode enablement — 2026-10-22

- Enabled the accepted eight-step `fast` path and removed the obsolete
  `mode_unavailable` gate and `fast_mode_enabled` configuration field.
- Kept `quality` as the public and worker default at 10 steps; `auto` remains
  mapped to 10 steps. Updated public/internal API specifications and TTS
  operations documentation without changing response formats.
- Added worker coverage for timestep selection, supported-mode WAV responses,
  response content type, invalid-mode errors, and Gateway default/fast-mode
  forwarding.
- No STT, model provisioning, images, deployments, or unrelated services were
  changed. At the time of this implementation entry, verification and closeout
  review were pending; subsequent completion is recorded below.

## M03B high_quality live validation — 2026-10-22

- Rebuilt Gateway and a TTS source overlay on the existing pinned CUDA/runtime
  image, then deployed only Gateway and TTS with Compose `--no-deps`.
- Kept the exact prior Gateway/TTS image references and a copy of the prior
  TTS config in an ignored private rollback set. STT and unrelated projects
  were not recreated or modified.
- Sent one real `mode=high_quality` request through the canonical Gateway;
  the worker mapping selected 16 inference steps and produced a valid 48 kHz
  PCM16 WAV. Full response, health, GPU and rollback evidence is in
  [verification.md](verification.md).
- No SSML was implemented.

## M03B final acceptance and closeout — 2026-10-22

- Recorded the operator's acceptance of the final live `high_quality` sample:
  “Audio sounds good. Accepted.”
- Recorded explicit approval to close M03B for the agreed implementation and
  technical-validation scope. All supported configurations are accepted:
  fast=8 steps, quality=10 steps (default), high_quality=16 steps, and
  auto=quality.
- No implementation scope was extended. Production licensing remains
  unresolved; cold-start latency remains significant; sustained-load behavior
  remains unestablished. No SSML implementation was started.
