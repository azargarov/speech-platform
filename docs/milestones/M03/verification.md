# M03 screening verification

## Earlier resumed review snapshot (superseded by the bounded review below) — 2026-10-21

This section records the earlier state before the operator separately approved
private technical evaluation and production deployment. Its candidate gate
table and “no inference” status are historical. The current decision and
executed-screen evidence are recorded in the following section.

- **OBSERVED:** Refreshed host command on `llm`: Ubuntu kernel 6.8.0-147,
  32 CPUs, 61 GiB RAM, root filesystem 50 GiB available. NVIDIA driver
  580.178.04 / CUDA 13.0 reports Quadro RTX 5000 UUID
  `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`, 15,360 MiB total,
  2,216 MiB used, 12,694 MiB free, and 0% GPU utilization. One process
  occupies 2,212 MiB. This meets the point-in-time 8 GiB VoxCPM2 loading
  threshold but does not reserve memory or establish absence of STT requests.
- **OBSERVED:** `docker ps` showed the canonical Gateway, STT, and TTS
  containers `healthy`, each with restart count zero in a read-only inspect.
  No container was modified. Other listed services were not part of the
  candidate evaluation.
- **OBSERVED:** Upstream current refs observed via official GitHub/Hugging Face
  APIs: VoxCPM source `cce58a5b59303c9bd63d12f23afe6a49a4a80c59`, VoxCPM2
  weights repository `32279effe8c19989596f05d353d1447f51d9e915` (Apache-2.0
  metadata); MOSS TTS source `8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb`,
  TTS model `44502f80dbf9743528fa921cc544d662c685ebec` and audio tokenizer
  `6aa02b01e445cc585582cf0ba480bc3ea6c8dd68` (each Apache-2.0 metadata).
  These are candidate revision observations, not complete license approval.
- **OBSERVED:** Piper voice cards at upstream `main` report English
  `libritts-high` trained from scratch on LibriTTS/train-clean-360 under
  CC BY 4.0; Russian `irina` cites the RHVoice dataset with license `Unknown`,
  Russian `ruslan` cites CC BY-NC-SA 4.0, and Russian `dmitri`/`denis` cite
  CC0 voice-datasets but say they were fine-tuned from the English Lessac
  checkpoint. Lessac's card cites the Blizzard 2013 dataset license. Swedish
  `nst` reports CC0 and scratch training. The Piper collection-level MIT label
  does not resolve those individual asset/lineage terms.
- **INTERPRETATION:** Piper's inspected Russian set has no candidate whose
  checkpoint lineage and applicable terms are clear enough to approve. Piper
  is `BLOCKED`; do not download or execute it. This block does not prevent
  independent VoxCPM2 or MOSS review.
- **NOT ESTABLISHED:** Active STT inference state from an authoritative
  worker-level signal; candidate dependency license inventories; applicable
  dataset/redistribution terms for VoxCPM2/MOSS; MOSS custom-code and
  serialization safety review; asset hashes; candidate runtime provisioning;
  frozen prompts; samples, measurements, and listening manifest.
- **OBSERVED:** The resumed attempt has not downloaded models, installed
  candidate dependencies, or run inference. The local preflight did not alter
  canonical services.

### Candidate gate disposition

| Candidate | Eligibility | Licensing gate | Provisioning gate | Execution gate |
|---|---|---|---|---|
| VoxCPM2 | `BLOCKED` | Apache-2.0 metadata observed for source and model repository; direct/transitive dependency inventory, associated `audiovae.pth` asset/hash and applicable data/output terms are not fully reviewed | `BLOCKED` pending licensing and reviewed dependency lock | `BLOCKED` pending static source/serialization review and fresh no-active-STT check |
| MOSS-TTS-Nano | `BLOCKED` | Apache-2.0 metadata observed for TTS and tokenizer repositories; dependency inventory, reference-audio terms and applicable data/output terms are not fully reviewed | `BLOCKED` pending licensing, reference asset and reviewed dependency lock | `BLOCKED` pending custom-code and pickle serialization review and fresh no-active-STT check |
| Piper | `BLOCKED` | English LibriTTS-high and Swedish NST have clear dataset cards, but no reviewed Russian checkpoint clears the lineage/terms gate | `BLOCKED` because no approved three-language voice set is available | `BLOCKED`; no voice assets provisioned |

No candidate is `FAILED` or rejected. Independent-gate policy allows any
candidate to proceed as soon as its own licensing, provisioning, and execution
gates are approved. This attempt stopped before model acquisition because
none had cleared all required gates at the time of review.

#### Commands and verification

- `hostname; uname -a; nproc; free -h; df -h .; nvidia-smi` — executed on
  `llm`; values summarized above.
- `docker ps --format '{{.Names}} {{.Status}} {{.Image}}'` — executed; the
  canonical three services reported healthy. A broad `docker inspect` over
  every container emitted expected template errors for containers without a
  healthcheck; the canonical three health/restart fields were still returned.
- `git ls-remote https://github.com/OpenBMB/VoxCPM.git HEAD` and
  `git ls-remote https://github.com/OpenMOSS/MOSS-TTS-Nano.git HEAD` — executed;
  returned the source revisions recorded above.
- Hugging Face model metadata APIs for VoxCPM2, MOSS TTS Nano, and the MOSS
  audio tokenizer — executed using `curl` and `python3`; returned the model
  revisions and declared license metadata recorded above. The first parsing
  attempt used unavailable `python`; it was rerun successfully with `python3`.
- `make governance-check PYTHON=.venv/bin/python` — exit 0; governance
  structure/local-reference validator passed and 2 governance unit tests
  passed. This is structural documentation verification, not candidate
  runtime validation.
- `git diff --check` — exit 0 after the documentation changes.

Upstream evidence reviewed on 2026-10-21: [VoxCPM source and dependency
metadata](https://github.com/OpenBMB/VoxCPM/tree/cce58a5b59303c9bd63d12f23afe6a49a4a80c59),
[VoxCPM2 model card](https://huggingface.co/openbmb/VoxCPM2), [MOSS TTS
source](https://github.com/OpenMOSS/MOSS-TTS-Nano/tree/8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb),
[MOSS TTS model card](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M),
[MOSS tokenizer card](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano),
and individual Piper [English](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/libritts/high/MODEL_CARD),
[Russian irina](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/irina/medium/MODEL_CARD),
[Russian ruslan](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/ruslan/medium/MODEL_CARD),
[Russian dmitri](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/dmitri/medium/MODEL_CARD),
[Russian denis](https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/denis/medium/MODEL_CARD),
[English Lessac](https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD),
and [Swedish NST](https://huggingface.co/rhasspy/piper-voices/blob/main/sv/sv_SE/nst/medium/MODEL_CARD).

Historical status at that review snapshot: no candidate had cleared its gates, so screening had not run. This status was superseded by the later bounded review and screening recorded below.

## Evidence

- **OBSERVED:** M03 planning artifacts and roadmap/readiness references were
  updated on 2026-10-21. No runtime, deployment or model operation was
  performed.
- **OBSERVED:** `make governance-check PYTHON=.venv/bin/python` exited 0 on
  2026-10-21. The governance validator reported PASS for seven skill
  structures/frontmatter and local references; its two governance unit tests
  passed. The validator describes its scope as structural and says it does not
  prove semantic consistency or Codex discovery.
- **OBSERVED:** `git diff --check` exited 0 on 2026-10-21.
- **OBSERVED:** `git check-ignore -v private/m03a/example/models/voxcpm2`
  matched `.gitignore:2:/private/`; the proposed private experiment path is
  ignored by Git.
- **INTERPRETATION:** Manual review found the M03 planning status and the
  roadmap/readiness references consistent with the accepted decisions. This is
  a documentation review, not runtime verification.
- **NOT ESTABLISHED:** Candidate model/voice licenses at pinned revisions,
  downloaded artifact sizes on the target filesystem, and host resource
  availability. The plan's sizes are upstream page reports, not local
  measurements.
- **NOT ESTABLISHED:** M03A quality, pronunciation, latency, resource usage or
  candidate selection. No model download or benchmark has been authorized.

## Executed checks

- `make governance-check PYTHON=.venv/bin/python` — exit 0; validator and 2
  unit tests passed.
- `git diff --check` — exit 0.
- `git check-ignore -v private/m03a/example/models/voxcpm2` — matched root
  private ignore rule.
- Manual link and status consistency review across M03 records, `PLANS.md`,
  and affected architecture documents — completed; semantic consistency is
  interpreted, not established by the structural validator.


## Revised M03A preflight and license gate — 2026-10-21

- **OBSERVED:** Repository HEAD was `f410fa7b46b5f0414f16c08f0509367771703179` and the worktree was clean before the plan update. The preflight ran on host `llm`, Ubuntu kernel `6.8.0-147-generic`, with 32 CPUs and 61 GiB RAM (56 GiB available).
- **OBSERVED:** `df -B1 --output=source,size,used,avail,target /home/master/speech-platform` reported 53,111,037,952 bytes available, above the 20 GB storage gate.
- **OBSERVED:** GPU 0 was Quadro RTX 5000 UUID `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`, 15,360 MiB total. Seven samples from 11:46:48 to 11:47:25 UTC showed 12,694 MiB free, 0% utilization, and the resident STT compute process at 2,212 MiB. STT parent/worker process snapshots each showed about 0.5% CPU. This satisfies the revised observation-window check; resident memory alone is not treated as active inference.
- **OBSERVED:** Repeated `docker inspect` snapshots showed canonical Gateway, STT, and TTS all `running/healthy`, restart count 0. No service was restarted or modified.
- **OBSERVED:** Official model pages declare Apache-2.0 for VoxCPM2 and both MOSS model/tokenizer repositories. Piper engine `OHF-Voice/piper1-gpl` declares GPL-3.0-or-later. Hugging Face repository metadata for `rhasspy/piper-voices` declares MIT, but the approved `en_US-ryan` medium voice model card names RyanSpeech dataset terms CC BY-NC-SA 4.0.
- **INTERPRETATION:** The difference between Piper voice repository metadata and the Ryan voice's source-dataset terms leaves permitted use of the checkpoint and generated samples unclear for this evaluation's intended downstream context. The explicit stop condition applies. Screening stopped before pinning revisions, acquisition, prompt freezing, or audio generation.
- **NOT ESTABLISHED:** Exact candidate revisions and file hashes, candidate runtime safety, prompt/license compatibility, all audio quality and resource measurements, and model selection.
- **OBSERVED:** Detailed private record is at `private/m03a/20261021-screening-01/results/preflight-license-report.md` (ignored by Git).

### Executed preflight commands

- `uname -a`, `nproc`, `free -h`, `df -B1 --output=source,size,used,avail,target /home/master/speech-platform` — executed; outputs summarized above.
- `nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory --format=csv,noheader` and `nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader`, sampled seven times at about five-second intervals — executed; outputs summarized above.
- `docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}} {{.RestartCount}}' speech-platform-gateway-1 speech-platform-stt-1 speech-platform-tts-1`, sampled seven times — executed; all remained healthy with zero restarts.
- `git diff --check` — exit 0 after documentation edits.
- `git check-ignore -v private/m03a/20261021-screening-01/results/preflight-license-report.md` — matched root `/private/` ignore rule; attempt and results directories are mode 700.

## Bounded licensing decisions and executed private screening — 2026-10-21

### Independent candidate decisions

| Candidate | Private technical evaluation | Production / redistribution decision |
|---|---|---|
| VoxCPM2 | **CLEARED; screen executed.** Exact pinned source and model revisions were inspected; required model and VAE hashes matched upstream LFS SHA-256. The pinned README states Apache-2.0 and says commercial use is permitted. The bounded screen used synthetic neutral voice descriptions and no reference recording. | Apache-2.0 terms and notices apply to covered source/weights when distributed. The pinned README prohibits impersonation, fraud, and disinformation and recommends labeling generated content. It reports large-scale training data without detailed dataset lineage and does not grant a separate output license. No specific restriction on this private neutral screen or a categorical commercial-use prohibition was identified. Production review still needs the intended product/use, required notices, training-data provenance questions, and any desired output-rights assurance resolved. |
| MOSS-TTS-Nano | **CLEARED only for bounded private local evaluation; screen executed.** No specific restriction on private inference was identified. The pinned source is Apache-2.0; the maintainer confirms the HF weight-card Apache metadata. The pinned HF card also says to treat the repository as not licensed for redistribution until a root LICENSE is published. No weights or generated files were redistributed. | **BLOCKED for production approval and redistribution.** The exact weight-card Apache metadata conflicts with its redistribution notice, and the maintainer response confirms metadata without reconciling that notice. The pinned model repo has no LICENSE; its executable custom TTS `.py` files have no per-file license header. The upstream answer addresses weights, not explicit coverage of these model-code files. This is the concrete unresolved permission question. No broader output rights were inferred; output distribution terms also need clarification for a production use case. |
| Piper | **BLOCKED by operator direction; not provisioned or run.** | Not reviewed further; no production or private-evaluation decision is implied. |

The source-code and artifact terms above were checked at exact revisions: VoxCPM source `cce58a5b59303c9bd63d12f23afe6a49a4a80c59`, model `32279effe8c19989596f05d353d1447f51d9e915`; MOSS source `8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb`, TTS model `44502f80dbf9743528fa921cc544d662c685ebec`, and audio tokenizer `6aa02b01e445cc585582cf0ba480bc3ea6c8dd68`. Hashes and the fuller bounded review are recorded in the private `results/license-security-review.md`.

### Custom code, serialized weights, and reference audio

- **OBSERVED:** Static inspection covered the exact MOSS TTS model code and tokenizer code before `trust_remote_code=True` was used. The selected files showed local model construction/inference and file handling; no subprocess/network client, `eval`, or `exec` path was found. Runtime was network-disabled, used local-only model files, and mounted the inspected code and artifacts read-only.
- **OBSERVED:** The MOSS `.bin` is pickle-based. The archive and pickle opcodes were parsed as data only; global references were `collections.OrderedDict`, `torch.BFloat16Storage`, and `torch._utils._rebuild_tensor_v2`, with no `STACK_GLOBAL`. No `pickle.load`, `weights_only=False`, or other unrestricted deserialization was invoked. Transformers 4.57.1's pinned state-dict loading path uses `torch.load(..., weights_only=True)`.
- **OBSERVED:** VoxCPM2 `from_local` used primary safetensors weights and the pinned VAE safe-loading path with `weights_only=True`; the optional denoiser was disabled. No LoRA, external speaker sample, or reference recording was loaded.
- **OBSERVED:** MOSS `voice_clone` requires reference audio, and default voice choices point to bundled recordings whose separate rights were not established. The pinned code supports text-only `continuation`; the screen used that mode and did not load built-in demo voices or audio samples.
- **INTERPRETATION:** These controls were sufficient for the bounded private screen, while the remaining custom-code license question prevents production redistribution approval for MOSS. Container isolation does not eliminate risk in PyTorch, native CUDA libraries, or inspected custom code.
- **NOT ESTABLISHED:** Comprehensive transitive dependency license/SBOM review, dependency vulnerability audit, dataset-level permission lineage, any separate generated-output license, or candidate listening quality. Those are not represented as passed.

### Runtime results and safeguards

- **OBSERVED:** VoxCPM2 produced 9/9 outputs. Model-load time was 60.139 s; generation totaled 99.451 s for 46.56 s audio (weighted RTF 2.136). Peak process RSS was 11,151.7 MiB; cgroup memory peak 10,612.1 MiB; output format 48 kHz mono.
- **OBSERVED:** MOSS produced 9/9 outputs. Model-load time was 0.917 s; generation totaled 116.682 s for 62.72 s audio (weighted RTF 1.860). Peak process RSS was 1,659.4 MiB; cgroup memory peak 1,334.2 MiB; output format 48 kHz stereo.
- **OBSERVED:** Canonical Gateway, STT, and TTS remained healthy with restart count zero. The STT in-flight gauge remained zero during both screens. VoxCPM2's seven-point preflight had 12,694 MiB free VRAM; during generation the candidate used 6,132 MiB and minimum free VRAM was 6,562 MiB. Only the known STT worker and candidate process appeared in GPU compute process observations.
- **OBSERVED:** The private blind listening manifest contains 18 WAV files and does not expose candidate identity; the answer key is a separate private file. No listening judgment has been recorded.
- **OBSERVED:** First MOSS invocation stopped after generating one unrecorded WAV because its CSV writer field list omitted `cgroup_peak_mib`; the partial artifact and reason are preserved under private `aborted/`. After fixing that private runner metadata, the complete nine-sample run exited 0. First VoxCPM2 launch stopped before model load because `PYTHONPATH` omitted the source `src/` directory; the corrected isolated run exited 0.
- **INTERPRETATION:** Successful screen completion establishes inference and resource observations for these exact prompts, revisions, and runtime conditions only. It does not establish speech quality, production throughput, or production suitability.

### Executed commands and outcomes

- `docker buildx build --network=host -f private/m03a/M03A-20261021-01/provisioning/Dockerfile --output type=oci,dest=private/m03a/M03A-20261021-01/provisioning/m03a-eval.oci.tar,compression=gzip,compression-level=1 private/m03a/M03A-20261021-01/provisioning` — exit 0. OCI archive loaded locally with `docker load`; temporary archive was removed. The earlier Docker image exporter stalled during a large layer diff and was stopped; no service was affected.
- Disposable runtime import check for Torch, torchaudio, Transformers and CUDA — exit 0; versions `2.7.0+cu128`, `2.7.0+cu128`, and `4.57.1`; Quadro RTX 5000 visible when passed through.
- `sha256sum` on the four required large model/auxiliary artifacts — exit 0; values matched the pinned API LFS hashes recorded in the private report.
- Successful isolated screening: `docker start --attach m03a-moss-nano-screen` — exit 0 (9/9); `docker start --attach m03a-voxcpm2-screen` — exit 0 (9/9). Both were created with network disabled, non-root user, read-only root, dropped capabilities, no-new-privileges, resource limits and private output mounts. The live monitor was `python3 private/m03a/M03A-20261021-01/runner/monitor.py` with each candidate name; VoxCPM2 used `--gpu --baseline-pids 2639811`.
- Seven-observation VoxCPM2 preflight loop — completed; each observation recorded healthy canonical services, zero restarts, STT inflight 0, 12,694 MiB free VRAM and the known resident STT compute process.
- `git diff --check` and private-ignore check are recorded after the documentation update below.

### Evidence limits and current status

- **NOT ESTABLISHED:** blind operator listening feedback; pronunciation, intelligibility, naturalness or artifact scores; acceptable production latency; production voice selection; MOSS redistribution/custom-code permission; full dependency SBOM/license/vulnerability results; dataset-level lineage or separate output license for either candidate.
- **OBSERVED:** no candidate was selected for production; M03B, deployment, pushes, and tags were not performed. No running Speech Platform service was modified. Existing Ollama, Dify and M00 experiment were not touched.

## M03A Round 2 private listening experiment — 2026-10-21

### Scope and control review

- **OBSERVED:** Used the exact pinned revisions and already staged model artifacts from `private/m03a/M03A-20261021-01/`. Recomputed SHA-256 values for VoxCPM2 model/VAE and MOSS TTS/tokenizer artifacts; all four matched the Round 1 hashes. No new model checkpoint, reference recording, speaker sample, or voice asset was downloaded.
- **OBSERVED:** Frozen exact texts for English, Russian, and Swedish are in `private/m03a/M03A-20261021-02/inputs/prompts.json` and repeated in every sample metadata record.
- **OBSERVED:** Pinned VoxCPM2 README and source describe reference-free voice design through a natural-language voice description and style suggestions in the text prefix. The selected `generate()` call exposes no structured speaker, emotion, intonation, or speaking-rate parameter. Pace/emotion/style are prompt suggestions; reference-audio cloning is separately supported but excluded.
- **OBSERVED:** Pinned MOSS `inference()` accepts text-only `continuation` and reference-audio `voice_clone` modes. It has no text-only speaker, voice-design, style, emotion, prosody, or speaking-rate argument. Sampling parameters affect generation but do not select a semantic voice/style. Reference cloning was excluded.
- **INTERPRETATION:** The valid comparison therefore used three VoxCPM2 natural-language designs (`neutral_baseline`, `warm_unhurried`, `bright_lively`) and one MOSS default text-only configuration (`default_continuation`). No unsupported MOSS style variation was fabricated.

### Execution and measurements

- **OBSERVED:** 12/12 samples completed: nine VoxCPM2 samples (three configurations for each language) and three MOSS samples (one configuration for each language). Each language/model/configuration combination was generated once. Generation was sequential within each candidate; no sample retries occurred.
- **OBSERVED:** VoxCPM2 source revision `cce58a5b59303c9bd63d12f23afe6a49a4a80c59`; weight revision `32279effe8c19989596f05d353d1447f51d9e915`; model load 64.040 s; generation 195.631 s for 91.840 s audio; weighted RTF 2.130; peak RSS 11,150.2 MiB; cgroup memory peak 10,611.3 MiB; WAV 48 kHz mono.
- **OBSERVED:** MOSS source revision `8b7bcc9341b3b4ef3a3a58ba1338a7d85ff133eb`; TTS weight revision `44502f80dbf9743528fa921cc544d662c685ebec`; tokenizer revision `6aa02b01e445cc585582cf0ba480bc3ea6c8dd68`; model load 7.964 s; generation 87.652 s for 44.640 s audio; weighted RTF 1.964; peak RSS 2,038.4 MiB; cgroup memory peak 1,705.9 MiB; WAV 48 kHz stereo. MOSS ran CPU-only at four threads. VoxCPM2 ran on CUDA 0.
- **OBSERVED:** Seven preflight samples from 14:00:06 to 14:00:40 UTC each recorded 12,694 MiB free on the 15,360 MiB Quadro RTX 5000, 0% utilization, only the known 2,212 MiB STT process, STT in-flight 0, and Gateway/STT/TTS `running healthy` with restart count 0. The VoxCPM2 monitor recorded 99 observations; minimum free GPU memory was 6,148 MiB, maximum total GPU memory used 8,762 MiB, and the only compute processes were the resident STT process and VoxCPM2. STT in-flight remained 0. The monitor did not stop the candidate. Afterward GPU memory returned to 12,694 MiB free and 0% utilization; all canonical services remained healthy with restart count 0.
- **OBSERVED:** The blind flat manifest contains 12 IDs and 12 WAV files. The separate key maps those IDs to model/configuration. The six required language/model directories each contain the actual supported configuration subdirectories; every audio file has adjacent JSON metadata with exact text, revisions, configuration, generation timestamps, duration, format, warnings and errors. No Round 2 subjective scores were added.
- **INTERPRETATION:** MOSS rendered longer audio than every VoxCPM2 configuration for each fixed text. This is an objective duration observation only; no naturalness, pronunciation, or quality conclusion is established before listening.

### Failures and warnings

- **OBSERVED:** The first MOSS launch stopped before model load when Transformers attempted to create a cache under the read-only home directory (`OSError: [Errno 30] Read-only file system`). It generated no sample. A fresh invocation directed Transformers caches to `/tmp` tmpfs and completed the three requested samples once each. No sample was automatically retried.
- **OBSERVED:** VoxCPM2 completed with exit code 0 and logged a tokenizer-class mismatch warning (`VoxCPM2Tokenizer` versus `LlamaTokenizerFast`) and a PyTorch `weight_norm` deprecation warning. These warnings are copied to each Vox sample metadata record; there were no sample-generation errors. MOSS produced no sample-level warning or error.
- **OBSERVED:** The same approved isolation requirements were used: network disabled, UID 1000, read-only root and code/model mounts, dropped capabilities, `no-new-privileges`, bounded CPU/memory/PIDs, private mode-0700 writable attempt output, no credentials, and temporary model caches in a container tmpfs. The disposable candidate containers and temporary evaluation image were removed after completion. The image was rebuilt from the existing pinned Dockerfile and requirements; BuildKit reported the dependency-install layers cached.
- **OBSERVED:** Two local packaging checks were corrected before final validation: an initial assertion incorrectly expected 30 rather than 12 samples; a host-only `wave` parser did not accept IEEE-float WAV encoding. Neither altered model outputs. Final checks used the correct expected count and a RIFF metadata parser and passed for all 12 generated WAVs.
- **NOT ESTABLISHED:** Round 2 operator ratings; comparative listening judgments; production latency, deployment suitability, or production rights. The existing MOSS production/redistribution blocker remains.

### Commands and outcomes

- `sha256sum` on the four pinned large artifacts — exit 0; all values matched the private Round 1 license/security record.
- `docker build --network=host -f private/m03a/M03A-20261021-01/provisioning/Dockerfile -t m03a-eval-round2:local private/m03a/M03A-20261021-01/provisioning` — completed; BuildKit reused cached base/dependency layers. Image manifest digest `sha256:0476d600a929fcec6985f712b8f6a3d5dff063b35ad3f2a3e538d47905fac562`.
- `python3 -m py_compile private/m03a/M03A-20261021-02/runner/round2.py private/m03a/M03A-20261021-02/runner/monitor.py` — exit 0.
- Private sequential candidate runs used `docker run` with `--network none`, read-only root, private output bind mount, read-only pinned model/review mounts, and resource limits. MOSS exit 0 (3/3); VoxCPM2 exit 0 (9/9). Live monitor: `python3 private/m03a/M03A-20261021-02/runner/monitor.py m03a-r2-voxcpm2 voxcpm2 --gpu --baseline-pids 2639811` — exit 0, no stop reason.
- Final local metadata, sample count, required text, audio existence/RIFF metadata, configuration directory, flat manifest/key correspondence, and Round 1 ID/rating assertions — executed with Python 3.12; exit 0. Output confirmed 6 categories, 12 samples/metadata records, and 12 flat listening entries.
- `git check-ignore -v private/m03a/M03A-20261021-02/listening/audio/sample-00bddad1.wav` — matched the root `/private/` ignore rule. No private audio or evaluation artifact is tracked.
- `git diff --check` — executed after the milestone record edits; result recorded in the final task report.

The complete run report, per-sample records, flat listening pack, output hierarchy, measurements, and Round 1 rating breakdown are under `private/m03a/M03A-20261021-02/`. Existing Round 1 evidence remains under `private/m03a/M03A-20261021-01/` and was not modified.


## M03A focused performance and language follow-up — 2026-10-21

### OBSERVED — VoxCPM2 performance

- Pinned revisions were VoxCPM source `cce58a5b59303c9bd63d12f23afe6a49a4a80c59` and weights `32279effe8c19989596f05d353d1447f51d9e915`; runtime was Python 3.12, PyTorch/torchaudio 2.7.0+cu128, Transformers 4.57.1, on Quadro RTX 5000 16 GiB.
- Baseline (`optimize=False`, 10 diffusion steps): model load 62.748 s; nine warm measurements took 182.045 s for 90.240 s of audio; weighted RTF 2.0173; peak process RSS 11,151.7 MiB; cgroup peak 10,612.6 MiB; peak CUDA allocated/reserved 5,549.7/5,694.0 MiB. Host monitor peak total GPU use was 8,060 MiB (resident STT included).
- Candidate (`optimize=False`, 8 diffusion steps): model load 62.125 s; nine warm measurements took 168.407 s for 94.080 s of audio; weighted RTF 1.7900; peak process RSS 11,151.7 MiB; cgroup peak 10,612.0 MiB; peak CUDA allocated/reserved 5,591.3/5,966.0 MiB. Host monitor peak total GPU use was 8,332 MiB (resident STT included).
- Generation wall time fell 7.5% and weighted RTF fell 11.3%. Total rendered duration rose 4.3%; per-sample English/Russian duration was unchanged and Swedish averaged 11.52 s vs 10.24 s. Listening is pending; no quality conclusion follows from timing.
- Pinned generation code already uses BF16 and PyTorch scaled dot product attention internally. The pinned wrapper documents `optimize=True` as `torch.compile`. It produced no timed samples: (1) Triton cache initially attempted to write under read-only `/home/ubuntu`; (2) after moving caches to `/tmp` and adding disposable compiler, it lacked C standard headers; (3) after adding disposable `build-essential`, compilation failed due to missing Python `Python.h`, while PyTorch warned that Quadro RTX 5000 does not natively support BF16 compilation.

### OBSERVED — language APIs and outputs

- VoxCPM2 `generate()` exposes no language-code input or detector in the pinned path. CLI timestamp alignment has a language option, which is not synthesis language detection/selection. MOSS checkpoint `inference()` exposes no language argument or detected-code output. Its surrounding text-normalization helper heuristically chooses only `zh` or `en`; that Python preprocessing is not a native multilingual detector and was bypassed in this direct reference-free continuation run.
- VoxCPM2 direct-text generation completed 11/11; model load was 62.049 s. MOSS reference-free text-only continuation completed 11/11 on CPU; model load was 0.896 s. No explicit language field or voice/reference audio was supplied.
- All 22 cases and exact input are captured in private `language-cases.csv` and JSONL; WAVs are under `private/m03a/M03A-20261021-03/language/audio/`. All rows say native detected code: none and observed spoken language: pending listening.

### OBSERVED — isolation and service preservation

- GPU monitor recorded 96 baseline and 91 eight-step observations. STT in-flight remained zero; canonical Gateway/STT/TTS remained running and healthy with restart count 0. Minimum free VRAM was 6,850 MiB baseline and 6,578 MiB at eight steps; no unexpected compute PID appeared. After GPU runs VRAM returned to 12,694 MiB free; final GPU use was 2,216 MiB, 0% utilization.
- VoxCPM2 language run also completed under GPU monitoring with STT in-flight zero and services healthy. MOSS CPU run used the same canonical/STT activity monitor. Final post-run inspection confirmed Gateway/STT/TTS healthy with zero restarts, STT in-flight zero, and no candidate container or evaluation image left.
- All outputs are within the root `private/` ignore boundary; no private audio/transcript artifact is tracked. Production deployment, M00, Ollama, and Dify were not changed.

### Executed commands and outcomes

- `docker build --network=host -f private/m03a/M03A-20261021-03/runner/Dockerfile -t m03a-followup-eval:local private/m03a/M03A-20261021-03/runner` — dependency installation completed; default exporter was stopped after a long layer export.
- `docker buildx build --network=host -f private/m03a/M03A-20261021-03/runner/Dockerfile --output type=oci,dest=private/m03a/M03A-20261021-03/results/eval.oci.tar,compression=gzip,compression-level=1 private/m03a/M03A-20261021-03/runner` — exit 0 after 694.7 s; archive loaded then removed.
- `docker build --network=host -f private/m03a/M03A-20261021-03/runner/Dockerfile.compile -t m03a-followup-compile:local private/m03a/M03A-20261021-03/runner` — exit 0; temporary compiler-only image used for `torch.compile` investigation and later removed.
- Monitored disposable inference containers: baseline VoxCPM2 exit 0 (9/9); 8-step VoxCPM2 exit 0 (9/9); VoxCPM2 language exit 0 (11/11); MOSS language exit 0 (11/11). `optimize=True` attempts exited nonzero before benchmark samples, as described above.
- `PYTHONPYCACHEPREFIX=/tmp/m03a-pycache python3 -m py_compile private/m03a/M03A-20261021-03/runner/followup.py` — exit 0.
- Structural output check observed 18 VoxCPM2 performance WAVs (nine/config), 22 language WAVs, and 22 successful per-case records.
- Final GPU/STT/service check — exit 0; free VRAM 12,694 MiB, GPU used 2,216 MiB, utilization 0%; STT in-flight 0; canonical services `running healthy`, restart count 0.
- `git check-ignore -v private/m03a/M03A-20261021-03/language/audio/voxcpm2/en_normal.wav` — matched root `/private/` ignore rule. `git diff --check` — executed after documentation edits.

### INTERPRETATION and NOT ESTABLISHED

The 8-step setting is a measurable latency candidate, with duration change and reduced diffusion work that could affect naturalness or pronunciation. Do not call it quality-preserving until listening. `torch.compile` is not demonstrated usable with the pinned BF16 model on this GPU/runtime. Neither model's automatic spoken-language correctness is established until audio is reviewed. No explicit detected code was exposed. Production latency, suitability, and routing policy remain unestablished.

## M03A final operator decision — 2026-10-21

- **OBSERVED (operator-reported):** final listening found VoxCPM2 good for
  English, Russian, Swedish and mixed-language inputs. MOSS-TTS-Nano was
  acceptable for pure English and unsatisfactory for Russian, Swedish and
  mixed-language speech.
- **OBSERVED (operator decision):** VoxCPM2 is selected as the primary M03B
  integration candidate. MOSS is not selected for initial integration. This
  records candidate selection, not production acceptance.
- **OBSERVED (operator decision):** retain the 10-step configuration as the
  quality baseline. Keep the 8-step configuration as a faster inference
  candidate subject to quality acceptance.
- **OBSERVED (prior pinned-API inspection):** neither VoxCPM2 nor MOSS exposes
  a native detected-language-code API. VoxCPM2 completed multilingual text
  synthesis without explicit language metadata in the 11-case focused run.
  Those generated outputs alone do not determine spoken language; the
  operator's final listening assessment supplies the qualitative evidence.
- **INTERPRETATION:** the operator's results justify integrating VoxCPM2
  behind the existing TTS boundary. They do not establish production legal
  approval, target operation under live STT load, or quality parity for eight
  steps.
- **NOT ESTABLISHED:** production license/notice review for intended use,
  full transitive dependency license/SBOM review, live M03B API behavior,
  fast-mode acceptance, or sustained shared-GPU capacity.

M03A is closed for its bounded evaluation and candidate-selection scope under
the user's explicit request. M03B implementation and validation proceed under
the separate plan and remain incomplete until operator validation and explicit
closeout.

## M03B automated verification and live deployment attempt — 2026-10-21

- **OBSERVED:** `make verify PYTHON=.venv/bin/python` exited 0. It ran 436
  repository Python tests, 64 STT runtime tests, Go vet/build/race checks,
  strict Gateway/STT/TTS config checks, both Compose validation paths, OpenAPI
  validation through `scripts.test_acceptance`, lock checks, Ruff and
  governance checks. The VoxCPM2 lock check reported 68 exact hash-pinned
  packages. A focused repeat of TTS lifecycle, API, artifact, Compose, and
  product-deployment tests ran 23 tests and exited 0.
- **OBSERVED:** `make image SERVICE=tts PYTHON=.venv/bin/python` resolved the
  pinned CUDA base, requirements lock, VoxCPM source commit, and completed the
  cached build steps, but remained in the Docker image export step. After
  275.8 seconds it was canceled. A direct `docker buildx build --load` also
  remained in export for over five minutes. A `type=docker` archive export to
  `/dev/shm` remained in export for over five minutes without creating an
  archive. A `type=local` export copied about 1.8 GiB before stalling; that
  temporary output was removed. No TTS candidate image tag was produced.
- **OBSERVED:** root filesystem free space remained about 9.5–11 GiB after
  canceling incomplete builds. No Docker image/build cache was pruned. The
  configured Gateway, STT, and existing health-only TTS container IDs remained
  `fd9c1879d531`, `02110b11d58c`, and `0cf0cfdf1ff4`; all reported `running
  healthy`. No Compose service was started, replaced, or restarted, and STT
  remained untouched.
- **NOT ESTABLISHED:** candidate image startup, actual RTX 5000 inference,
  cold/warm loading, output audio, language behavior through the live Gateway,
  idle unload/reload, coexistence, cancellation under native inference, or
  final live health after TTS integration. No TTS model was staged into the
  canonical store and no operator listening occurred on M03B outputs.
- **INTERPRETATION:** repository-level automated checks validate the code
  paths under test doubles, but they do not substitute for the requested
  pinned image export, live hardware checks, or operator listening. M03B
  remains incomplete; production acceptance is not claimed.

The live gate is blocked on Docker BuildKit's local image export not returning
the built TTS image. The failed export attempts did not change running
services. Resume live validation after the Docker image exporter returns a
loadable candidate image; preserve the current STT and other projects.

## M03B image-export recovery investigation — 2026-10-21

- **OBSERVED:** Docker client and server were both 29.1.3; Buildx was v0.38.0;
  the selected `default` builder uses the Docker driver with BuildKit v0.26.2
  and the overlayfs snapshotter. Its GC policy reports a 54.95 GiB minimum
  free-space target. The Docker root is `/var/lib/docker` on `/`.
- **OBSERVED:** `df -hT` reported a 295 GiB root filesystem with 11 GiB free
  (97% used). `docker system df` reported 113.9 GB of images and 67.67 GB of
  BuildKit cache; 75.73 GB of image data and 59.8 GB of BuildKit cache were
  reported reclaimable. No prune or cleanup was run. The M03B cached VoxCPM2
  dependency-install layer was 7.572 GB in `docker buildx du`.
- **OBSERVED:** A cache-reusing OCI export to `/dev/shm` with gzip level 1
  stayed at `exporting layers`; `dockerd` consumed 27.6 CPU seconds during a
  30-second sample while root free space fell from 11 GiB to 8.5 GiB. The
  archive had not appeared. The attempt was canceled; root free space returned
  to 11 GiB and BuildKit cache totals were unchanged.
- **OBSERVED:** An OCI export to `/dev/shm` with uncompressed layers used the
  same cached build steps and did not create an archive before layer export
  completed. Two attempts reported `exporting layers` complete after 106.8
  and 143.0 seconds respectively; a third reported completion after 197.2
  seconds. During the last attempt root free space fell to 5.7 GiB. Each was
  canceled before archive finalization and restored root free space; no
  candidate tag or archive was produced. The repeated CPU activity and
  changing layer-export durations establish ongoing work, not a completely
  idle BuildKit export.
- **OBSERVED:** The existing build cache was reused; neither requirements nor
  model artifacts were downloaded. No image, cache, volume, or container was
  pruned. Canonical Gateway, STT, and health-only TTS remained healthy with
  their original container IDs; no service was started, replaced, or
  restarted. Ollama, Dify, and M00 resources were not modified.
- **OBSERVED:** Buildx history continued to list an earlier M03B Dockerfile
  build, started at 17:28 UTC, as `Running` more than 30 minutes later. Its
  recorded log ended at `exporting layers`; Buildx exposed no per-build CPU or
  I/O metrics. The investigation did not stop the shared default builder or
  remove this record.
- **INTERPRETATION:** The blocker is host storage headroom during large-layer
  export and local image storage. Layer export is slow and consumes temporary
  root capacity; BuildKit's configured free-space target is far above current
  availability. Compression raises CPU use, while uncompressed export still
  materializes a large layer on the host filesystem. The current investigation
  attempts were actively progressing, but the older 30-minute Buildx record
  appears stalled relative to measured layer-export durations; its exact
  resource activity is not established. The candidate could not be safely
  finalized and loaded with current headroom. The snapshots do not establish
  a defect in VoxCPM2 or the TTS Dockerfile.
- **NOT ESTABLISHED:** A loadable candidate image, image startup, pinned model
  staging for M03B, live TTS behavior, language samples, lifecycle/cancellation,
  GPU memory, STT/TTS coexistence, the documented `fast` error, or operator
  listening. Resume after additional safe storage capacity is available or a
  separately reviewed, scope-safe storage recovery is approved. Do not prune
  unrelated Docker data to make this build pass.

### Recovery commands and outcomes

- `docker version`, `docker buildx version`, `docker buildx ls`,
  `docker buildx inspect --bootstrap` — executed; versions and builder settings
  summarized above.
- `df -hT`, `docker info`, `docker system df`, `docker buildx du` — executed;
  storage values summarized above.
- `docker buildx build --progress=plain --file deployments/compose/worker-tts-cuda.Dockerfile ... --output type=oci,dest=/dev/shm/m03b-tts.oci.tar,compression=uncompressed .`
  — executed three times with the same pinned source revision and lock digest;
  cached build stages completed, layer export took 106.8–197.2 seconds, and
  each attempt was canceled before archive finalization to preserve root
  headroom. No OCI archive was retained.
- `docker ps --format '{{.Names}} {{.Status}} {{.Image}}'` — executed after
  attempts; canonical services remained healthy, with no restart or replacement.
- `git diff --check` — exit 0 after this record update.

## M03B resumed live validation — storage recovery and new blockers — 2026-10-21

### Storage recovery

- **OBSERVED (operator-reported):** The operator expanded the root LVM logical
  volume from 300 GiB to 500 GiB and resized the ext4 filesystem online. The
  operator reported `df -hT /`: ext4, 492G total, 271G used, 200G available,
  58% used. This resolves the previously recorded root-capacity constraint;
  the storage change itself is attributed to the operator, not independently
  observed by this validation session.
- **OBSERVED (this session):** `df -hT /` returned
  `/dev/mapper/ubuntu--vg-ubuntu--lv ext4 492G 271G 200G 58% /` before the
  resumed build. Near the end of the build attempt it returned 492G total,
  274G used, 198G available, 59% used. No Docker prune or cache cleanup was
  run.

### Resumed image build and blockers

- **OBSERVED:** `make image SERVICE=tts PYTHON=.venv/bin/python` selected the
  canonical root `compose.yaml`, source revision
  `f410fa7b46b5f0414f16c08f0509367771703179`, and pinned VoxCPM2 Dockerfile.
  Docker reused the pinned CUDA base and cached build steps, then remained at
  `#8 exporting to image / #8 exporting layers`. After more than ten minutes,
  the command was interrupted with Ctrl-C (exit 130) to stop the stalled
  export. A 10-second `/proc/1366/stat` sample during export recorded 956
  dockerd CPU ticks, and a later sample recorded 980 ticks; root availability
  remained 198–199 GiB. `docker image inspect
  speech-platform-tts:f410fa7b46b5f0414f16c08f0509367771703179` returned
  `No such image`. No candidate image was loadable.
- **OBSERVED:** The canonical check
  `make tts-model-check TTS_MODEL_STORE=/srv/speech-platform/models
  PYTHON=.venv/bin/python` failed with `Permission denied` while accessing
  `/srv/speech-platform/models/260dfb1d5d96b401c2a1a958abf676656cc59f830417ed0c0c5c6fe538155e76`.
  `namei -l` showed `/srv/speech-platform` mode `0711` and the `models`
  directory mode `2710`, owned by `root:stt-model-reader`; the pinned digest
  directory was not traversable by this session. The repository's fetch target
  uses noninteractive sudo for the default root-owned model store, but
  `sudo -n` returned `a password is required`. No permissions, group
  membership, or model-store contents were changed.
- **OBSERVED (2026-10-21):** A later independent HTTPS retrieval of
  `https://huggingface.co/openbmb/VoxCPM2/resolve/32279effe8c19989596f05d353d1447f51d9e915/tokenizer.json`
  returned 3,676,772 bytes with SHA-256
  `f8984687e4a92a3503d521396d454b7d68e9fdaab2a0288eb3536c7c1aa4bc20`, matching
  the operator's observed digest. The earlier manifest entry had
  `f8984687e7a92a3503d521396d454b7d68e9fdaab2a0288eb3536c7c1aa4bc20`.
  Correcting this entry changes the canonical manifest identity to
  `04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41`, so new
  fetches use
  `/srv/speech-platform/models/04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41`.
  The prior path above records the earlier failed check and remains historical
  evidence. The manifest is currently untracked in Git, so the original
  recording process and provenance of the expected nibble are not established.
- **OBSERVED:** Before and after the build attempt, `docker ps` showed
  `speech-platform-gateway-1`, `speech-platform-stt-1`, and
  `speech-platform-tts-1` healthy. The existing canonical container images
  and running state were not changed. Other projects and services were not
  changed.
- **INTERPRETATION:** The larger ext4 filesystem resolves the specific
  capacity shortfall documented in the prior investigation. The canonical
  Docker image exporter remains unable to produce a local image within the
  observed ten-minute interval despite ample free space and active dockerd
  CPU use; a loadable image is still a hard prerequisite. Independently, the
  current session cannot validate or stage the model through the protected
  store because privileged access is unavailable.
- **NOT ESTABLISHED:** Successful image export/load, local model hash
  verification, model staging, canonical Compose deployment, live language
  synthesis or Gateway integration, warm-up/unload/reload, cancellation,
  inference modes, GPU usage during inference, STT/TTS coexistence, and the
  operator listening pack. M03B remains open for operator listening and final
  acceptance; no production acceptance or milestone closeout is claimed.

### Commands and outcomes

- `df -hT /` — executed before and during the resumed build; ext4 reported
  492G total and 200G, then 198G, available.
- `docker ps --format '{{.Names}} {{.Status}} {{.Image}}'` and
  `docker compose --env-file .env -f compose.yaml ps` — executed before the
  build; canonical Gateway, STT, and TTS were healthy.
- `nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader`
  — executed before the build; Quadro RTX 5000 UUID
  `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`, 15,360 MiB total, 2,216 MiB
  used, 12,694 MiB free, 0% utilization. This is pre-build state only, not
  an inference observation.
- `make tts-model-check TTS_MODEL_STORE=/srv/speech-platform/models
  PYTHON=.venv/bin/python` — exit 2 due to permission denied.
- `sudo -n .venv/bin/python -m scripts.tts_model check --store
  /srv/speech-platform/models` — unavailable; sudo reported that a password
  is required.
- `make image SERVICE=tts PYTHON=.venv/bin/python` — interrupted after more
  than ten minutes at image layer export (exit 130); no local image tag.
- `git diff --check` — exit 0 after this record update.

## M03B export diagnostics and protected model-store staging — 2026-10-21

### Docker export diagnosis

- **OBSERVED (operator-reported):** the default Buildx driver is `docker`,
  BuildKit is v0.26.2, Docker uses overlayfs at `/var/lib/docker`, the root
  filesystem has approximately 200 GiB available, BuildKit cache is 67.67 GB,
  and the model store is protected as `root:stt-model-reader` with setgid.
- **OBSERVED (this session):** `docker buildx inspect --bootstrap` confirmed
  the default Docker driver, BuildKit v0.26.2 and overlayfs snapshotter.
  `docker info` reported Docker 29.1.3 and root `/var/lib/docker`;
  `df -hT /` reported ext4 with 200 GiB available; `docker system df` reported
  67.67 GB of BuildKit cache. No prune was run.
- **OBSERVED:** Buildx history record
  `rv0uew40h8es77lwjyxheuqb0`, created at 17:28:43 UTC for source revision
  `f410fa7b46b5f0414f16c08f0509367771703179`, remained `Running` for more than
  165 minutes. Its plain-progress log ends at `#11 exporting to client
  directory` / `#11 copying files 1.90GB 9.3s`. Three bounded log snapshots
  over 26 seconds showed the same 1.90 GB / 9.3 second status. During those
  snapshots available filesystem bytes changed from 214,541,205,504 to
  214,541,201,408, and dockerd CPU counters increased by 44 ticks (about
  0.44 CPU seconds at the observed 100 Hz tick rate). The history record
  remains running, but this sample establishes no measurable export progress.
- **OBSERVED:** no image tag
  `speech-platform-tts:f410fa7b46b5f0414f16c08f0509367771703179` exists.
  Canonical Gateway, STT and TTS containers remained healthy. No service was
  restarted or replaced.
- **INTERPRETATION:** the long-running operation is BuildKit's local
  client-directory exporter copying the built filesystem, not dependency
  installation. It reached a reported 1.90 GB and then produced no measurable
  change in the bounded sample. The old Buildx record's `Running` state alone
  does not establish active forward progress. This evidence does not identify
  whether the exporter is blocked in its client-side stream or another I/O
  wait.

### Bounded OCI probe

- **OBSERVED:** after confirming the existing lock digest and pinned source
  revision, a single OCI export probe to the ignored path
  `private/m03b-export-probe.oci.tar` was started with the default Docker
  builder, plain progress, and uncompressed layers. It unexpectedly reran the
  Dockerfile's `apt-get update` / apt install step rather than reusing its
  cache. The probe was interrupted after 41 seconds while that dependency
  installation step was still running. It produced no archive or image tag;
  no model download occurred. Root free space remained 200 GiB at displayed
  precision. No cache prune or cleanup was run.
- **INTERPRETATION:** an OCI archive export has not been established as a safe
  working path under the constraint against rebuilding dependencies. Do not
  retry this build until the cache miss is understood and an export plan can
  avoid dependency work; leave the original running history record untouched.

### Protected model store

- **OBSERVED:** `namei -l` and `stat` confirmed
  `/srv/speech-platform/models` is `root:stt-model-reader`, mode `2710`
  (`drwx--s---`), with the setgid bit. The current unprivileged process could
  not traverse the pinned digest directory. The store's mode was not changed.
- **OBSERVED:** the existing provisioner accepted only a `2750` protected
  store root, so its fetch path would reject this valid `2710` store before
  staging. The focused correction now accepts either `2710` or `2750` and
  leaves the existing root mode untouched; the content-addressed artifact
  directory remains `2750`, and files remain `0640`, owned by root and the
  reader group.
- **NOT ESTABLISHED:** whether the pinned model digest is already fully staged
  and hash-valid. Run the operator `check`, `fetch`, `check` sequence in
  [TTS operations](../../operations/tts.md) with the reader group as the
  primary group. No privileged model check or download was performed here.

### Commands and outcomes

- `docker buildx inspect --bootstrap`, `docker buildx history ls`,
  `docker buildx history inspect rv0uew40h8es77lwjyxheuqb0`, and bounded
  `docker buildx history logs --progress plain` snapshots — executed; exporter
  status and unchanged progress recorded above.
- `df -hT /`, `docker info`, `docker system df`, `ps`, and `/proc/1366/stat`
  samples — executed; storage and daemon observations recorded above.
- `docker buildx build --builder default --network=host --file
  deployments/compose/worker-tts-cuda.Dockerfile --build-arg
  SOURCE_REVISION=f410fa7b46b5f0414f16c08f0509367771703179 --build-arg
  TTS_LOCK_SHA256=618629a53f3a04cd395227ef3721a5cc1b36e9353fb26eec7bd1869a70c6a408
  --output type=oci,dest=private/m03b-export-probe.oci.tar,compression=uncompressed .`
  — interrupted after 41 seconds at apt installation when the cache miss was
  observed; no archive produced.
- `namei -l /srv/speech-platform/models/<pinned-digest>` and `stat` — executed;
  protected store ownership and `2710` mode confirmed, digest contents
  inaccessible to this session.
- `docker ps --format '{{.Names}} {{.Status}} {{.Image}}'` — executed after
  the probe; canonical services remained healthy with their existing images.
- `.venv/bin/python -m unittest scripts.test_model_artifacts -v` — exit 0;
  13 model-artifact tests passed, including the `2710` mode regression test.
- `make governance-check PYTHON=.venv/bin/python` — exit 0; governance
  structure/local-reference validation and 2 governance tests passed.
- `git diff --check` — exit 0 after the documentation and code edits.

## M03B verified model staging and export-cache comparison — 2026-10-21

### VoxCPM2 model provisioning

- **OBSERVED (operator-reported, actual host):** VoxCPM2 model staging and
  verification both passed for model-store identity
  `04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41`.
  This records the operator's host verification; command output and individual
  artifact hashes were not supplied in this session.
- **INTERPRETATION:** The M03B model provisioning gate is **PASS** for this
  identity. This does not establish image export, runtime model loading or
  live TTS behavior.

### Build export diagnosis

- **OBSERVED:** The cached Buildx record
  `rv0uew40h8es77lwjyxheuqb0` reports all six Dockerfile vertices `CACHED`,
  including apt installation, the hash-locked Python/VoxCPM install, and the
  service copy. Its history log stops at `exporting to client directory`,
  copying a reported 1.90 GB. Buildx history identifies this as
  `Image Resolve Mode: local`; the records show it is the Docker driver's
  local-image export path, which transfers the built image through the client
  side before it is available in the local Docker image store.
- **OBSERVED:** The OCI probe used the same Dockerfile, context, source
  revision and lock digest, but added `--network=host`. Its history explicitly
  records `Network: host`; the prior cached build record has no network
  override. The apt `RUN` vertex includes network mode in its cache key, so
  the override invalidated that vertex and all dependent layers; probe logs
  show apt updating package indexes and fetching 26.6 MB before it was
  interrupted. The OCI output format itself does not require that network
  override and was not the cause of this dependency cache miss.
- **INTERPRETATION:** The smallest evidence-based export attempt is to keep the
  cached build's default network mode and pinned build arguments, change only
  the output to an OCI archive on the host filesystem, then load that archive
  into Docker. The cache hit must be confirmed from plain progress before
  allowing export to proceed. This avoids dependency installation/downloads
  and does not change the builder or running services.
- **OBSERVED:** The proposed command was run after it was reported. Plain
  progress showed the base, apt, lockfile, pip/VoxCPM, and work-directory
  vertices cached; only the service source copy ran. OCI layer export completed
  in 240.1 seconds and tarball transfer completed in 471.8 seconds, for 712.1
  seconds total. It produced
  `private/m03b-tts.oci.tar` (7,650,189,312 bytes), which `docker load`
  loaded as `speech-platform-tts:f410fa7b46b5f0414f16c08f0509367771703179`.
- **OBSERVED:** `docker image inspect` reported image ID
  `sha256:ec23b15e21fe266fcfdd64bf762f5643ea8c6323a70495735458029f542d1854`,
  `linux/amd64`, user `65532:65532`, entrypoint `python -m`, and the expected
  TTS service role, CUDA variant, model revision, source revision and repository
  revision labels. The canonical Gateway, STT and existing TTS containers
  remained healthy with their prior image tags; no service was started,
  replaced or restarted. No dependencies or model artifacts were downloaded,
  no caches were pruned, and no builder was changed.
- **INTERPRETATION:** The OCI archive followed by `docker load` is a successful
  locally loadable image-export path when the cached build's network mode is
  preserved. This resolves the image-export blocker for the pinned candidate.
- **NOT ESTABLISHED:** Candidate image startup, live TTS synthesis, Gateway
  integration, model loading from the verified store, and operator listening.
  M03B remains open pending live TTS validation and operator acceptance.

The proposed command is reported for execution before it is run:

```sh
docker buildx build --builder default --progress=plain \
  --file deployments/compose/worker-tts-cuda.Dockerfile \
  --build-arg SOURCE_REVISION=f410fa7b46b5f0414f16c08f0509367771703179 \
  --build-arg TTS_LOCK_SHA256=618629a53f3a04cd395227ef3721a5cc1b36e9353fb26eec7bd1869a70c6a408 \
  --build-arg TTS_MODEL_REVISION=32279effe8c19989596f05d353d1447f51d9e915 \
  --build-arg TTS_SOURCE_REVISION=cce58a5b59303c9bd63d12f23afe6a49a4a80c59 \
  --tag speech-platform-tts:f410fa7b46b5f0414f16c08f0509367771703179 \
  --output type=oci,dest=private/m03b-tts.oci.tar,compression=uncompressed .
docker load --input private/m03b-tts.oci.tar
```

The run followed the cache guard: every install vertex was reported `CACHED`.
After `docker load`, the image identity and pinned labels were inspected. No
live TTS work was started.

### Executed export and local-load commands

- The exact `docker buildx build` command above — exit 0. All install vertices
  were `CACHED`; OCI layer export and tarball transfer completed in 712.1
  seconds total.
- `docker load --input private/m03b-tts.oci.tar` — exit 0; loaded the tagged
  TTS image listed above.
- `docker image inspect speech-platform-tts:f410fa7b46b5f0414f16c08f0509367771703179`
  — exit 0; image ID, platform, user, entrypoint and pinned labels matched the
  build inputs.
- `docker ps --format '{{.Names}} {{.Status}} {{.Image}}'` — executed after
  load; canonical Gateway, STT and TTS remained healthy on their previous
  image tags. No service lifecycle command was issued.

## M03B live RTX 5000 validation — 2026-10-22 (before operator closeout)

### Preflight and deployment identity

- **OBSERVED (host llm, 2026-10-22 UTC):** The candidate image
  speech-platform-tts:f410fa7b46b5f0414f16c08f0509367771703179 resolves to
  sha256:ec23b15e21fe266fcfdd64bf762f5643ea8c6323a70495735458029f542d1854,
  linux/amd64. Labels identify service tts, role tts-worker, CUDA variant,
  VoxCPM2 model revision 32279effe8c19989596f05d353d1447f51d9e915 and source
  revision cce58a5b59303c9bd63d12f23afe6a49a4a80c59. The TTS image was not
  rebuilt.
- **OBSERVED:** GPU 0 is Quadro RTX 5000 UUID
  GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a, 15,360 MiB. Before inference it
  reported 2,216 MiB used, 12,694 MiB free and 0% utilization. The only
  compute process was the resident STT process (2,212 MiB). STT metrics
  reported speech_stt_inflight_requests 0 and speech_ready 1.
- **OBSERVED:** Before deployment the canonical Gateway, STT and TTS
  containers were healthy with restart count zero. Gateway and STT used
  revision 3aa5f68c1d9a058ed2714b7b257c5b258a23c00a. The old TTS placeholder
  image remains available as speech-platform-tts:3aa5f68c1d9a058ed2714b7b257c5b258a23c00a,
  image ID sha256:3ad045ab9473069f4f184a3d05a66b4abadbb7a1204faa7632e8342eb8efae0f.
- **OBSERVED (preflight blocker resolved):** The old Gateway returned
  structured 404 with code not_found and message endpoint unavailable for
  GET /v1/tts/voices and POST /v1/tts/speech, and was not attached to
  tts_private. No Gateway image
  existed for the current repository revision. To permit the requested
  Gateway path, only the Gateway image was built from current source; its Go
  dependency download layer was cached. Build output produced
  speech-platform-gateway:f410fa7b46b5f0414f16c08f0509367771703179,
  sha256:7fe9c76282bb13106218c5a0696d0581262c05fd30bf1c34417e67ef57e59e55,
  linux/amd64. No STT or TTS image was rebuilt.
- **OBSERVED:** The protected host-side model checker failed with permission
  denied while traversing the root-owned 2710 model-store root. No permission
  was changed. A read-only candidate-image container running as worker
  UID/GID 65532:988 traversed the staged directory (mode 2750) and read all
  seven artifacts. Sizes and hashes matched
  releases/artifacts/voxcpm2.yaml:

  | Artifact | Bytes | SHA-256 |
  |---|---:|---|
  | audiovae.pth | 376,951,122 | 94b5d51e107e0507d4acc976cfdadb64edd6fd06d1f751dadbf2fd1594274bf1 |
  | config.json | 4,336 | 405f0dcd92f7feba6011ed4eac5c8d4f74cba9712f07fd5cfa3063bbdd95402c |
  | model.safetensors | 4,580,080,592 | f7f964cfa9da23653baec6e6f7750719977ad944ed9f95fe52fe3a620506891d |
  | special_tokens_map.json | 1,632 | 068594063e37662c02b21acf42ebb334ef6a74fb810e68a2368f88f08351de76 |
  | tokenization_voxcpm2.py | 2,895 | 84489ea32b6ee0cae22ed5480cacb6df85c46624c3119be9a2021c3649a12729 |
  | tokenizer.json | 3,676,772 | f8984687e4a92a3503d521396d454b7d68e9fdaab2a0288eb3536c7c1aa4bc20 |
  | tokenizer_config.json | 5,059 | e78a3ebb48a0b9437efd1823b6b726c823da89e49dd8bcc90c02419d9baa772b |

- **OBSERVED:** The ignored private .env initially pointed
  TTS_MODEL_MANIFEST_SHA256 at an obsolete digest. Candidate Compose rendering
  with the requested digest resolved the model mount to
  /srv/speech-platform/models/04d6e05b69b22568030ac21f494e406ffdf2d06efeeab43cfdb4c21ba8c9bd41.
  That single digest value was updated in ignored .env. SOURCE_REVISION was
  supplied only to per-service Compose commands because setting it globally
  would also retarget STT, whose image was to remain unchanged.
- **INTERPRETATION:** Image identity, worker-readable model integrity,
  point-in-time GPU capacity, current service health and canonical model
  mount passed preflight. The old Gateway incompatibility required the
  Gateway-only build. Its prior image remains available.

### Deployment and Gateway API behavior

- **OBSERVED:** The candidate TTS worker was deployed with
  up -d --no-deps tts; only the canonical TTS container was replaced. Gateway
  was then updated with up -d --no-deps gateway so it could serve TTS routes
  and join tts_private. STT was never recreated or restarted. TTS used the
  supplied image ID and a read-only model mount. Gateway, TTS and STT became
  healthy with zero restarts.
- **OBSERVED:** Through http://127.0.0.1:8080, GET /healthz, GET /readyz and
  GET /v1/tts/voices returned 200. Voice metadata returned the single default
  voice with en, ru, sv and streaming false. Before first inference, the
  TTS state endpoint reported unloaded.
- **OBSERVED:** Four mode=quality requests through POST /v1/tts/speech
  returned HTTP 200 and audio/wav. Every result parsed as mono PCM16 WAV at
  48,000 Hz. Timings include cold model loading for the first request:

  | Case | Language hint | Audio duration | Wall latency | RTF | Bytes |
  |---|---|---:|---:|---:|---:|
  | English | en | 3.84 s | 78.17 s | 20.36 | 368,684 |
  | Russian | ru | 5.12 s | 12.10 s | 2.36 | 491,564 |
  | Swedish | sv | 4.00 s | 8.11 s | 2.03 | 384,044 |
  | Mixed English/Russian/Swedish | auto | 4.48 s | 9.13 s | 2.04 | 430,124 |

- **OBSERVED:** The GPU monitor took 103 samples during these requests;
  peak nvidia-smi memory use was 8,054 MiB. Startup logs showed model load on
  CUDA. Load and synthesis completed without worker restart or GPU OOM.
- **OBSERVED:** The disabled fast request returned 422 with structured
  code mode_unavailable. Invalid language returned structured 400
  invalid_language; an unknown request field returned structured 400
  invalid_request. Invalid requests did not prevent a later successful
  synthesis.
- **OBSERVED:** VoxCPM2 startup emitted a tokenizer-class warning
  (VoxCPM2Tokenizer versus LlamaTokenizerFast) and a PyTorch weight_norm
  deprecation warning. Model load and synthesis completed. This validation
  did not independently assess voice quality.

### Lifecycle, cancellation and service coexistence

- **OBSERVED:** Initial synthesis automatically loaded the model and state
  reported loaded. An explicit private /internal/v1/warmup returned 200 with
  loaded. After the configured 60-second idle interval, state changed to
  unloaded and GPU use returned to 2,386 MiB. A warm-up from unloaded returned
  200 after 59.85 seconds and reported loaded. After the next idle interval,
  a Gateway quality request automatically reloaded the model and returned
  valid WAV in 69.66 seconds (4.96 seconds audio, RTF 14.04).
- **OBSERVED:** A 690-character quality request was sent through Gateway,
  then its client connection was closed after 0.5 seconds. The worker reported
  inference_active true; it remained active three seconds after disconnect
  and continued without termination. It returned to idle after 169.95 seconds
  total with the worker healthy and zero restarts. A subsequent Gateway
  synthesis returned 200, valid mono PCM16 48 kHz WAV, in 7.62 seconds.
- **OBSERVED:** A short STT request using the private English listening sample
  and a short TTS request were launched together through Gateway. Both
  returned 200. STT completed in 0.68 seconds; TTS completed in 9.15 seconds.
  Their measured overlap was 0.69 seconds. Seventeen GPU samples recorded
  maximum use of 7,928 MiB during the pair. STT returned to
  speech_stt_inflight_requests 0 and speech_ready 1; both workers remained
  healthy with zero restarts. The STT response body/transcript was not retained.
- **OBSERVED:** Graceful docker compose stop -t 240 tts exited successfully.
  TTS exited with code 0, OOMKilled false and zero restarts; its final log
  event was tts_worker_stopped with active_inference_drained true. Gateway
  and STT remained healthy. The same candidate TTS container was started
  again; Gateway health/readiness and voice listing returned 200, TTS was
  healthy with zero restarts, and GPU use returned to 2,216 MiB.
- **INTERPRETATION:** Lazy load, explicit warm-up, idle unload, automatic
  reload, post-cancellation completion, later request recovery, bounded
  concurrent STT/TTS requests and normal shutdown/restart all worked in this
  observed run. This does not establish broad load capacity or quality.

### Operator listening pack and rollback

- **OBSERVED:** Four quality-mode recordings, an HTML index and JSON metadata
  are prepared under ignored private path private/m03b/listening/. Metadata
  records exact input strings, language hints, TTS configuration, model/image
  identities, WAV properties, response sizes, hashes, latency, RTF and GPU
  samples. The HTML assigns no subjective ratings.
- **OBSERVED:** A private rollback Compose/config snapshot was prepared from
  pre-deployment HEAD. Static rendering resolves the previous Gateway,
  TTS-placeholder and STT image tags. The previous images remain present.
  If rollback is needed, the prepared command is:
  SOURCE_REVISION=3aa5f68c1d9a058ed2714b7b257c5b258a23c00a docker compose
  --project-directory /home/master/speech-platform --env-file .env -f
  private/m03b/rollback/compose.yaml up -d --no-deps gateway tts.
  This restores the prior Gateway/TTS placeholder while leaving STT running.
  Rollback was not executed because no serious problem occurred.
- **NOT ESTABLISHED AT THIS STAGE:** Operator listening and acceptance,
  production licensing approval, and behavior under broad or sustained
  concurrent load. The listening status was pending when this live validation
  record was first written; the subsequent operator PASS and current M03B
  status are recorded in the [closeout evidence update](#m03b-closeout-evidence-update--2026-10-22).

### Executed commands and outcomes

- docker image inspect for the pinned TTS tag — exit 0; expected image ID,
  architecture and labels.
- Read-only docker run as 65532:988 against the staged model directory —
  exit 0; all seven artifact sizes and hashes matched the pinned manifest.
  The unprivileged host-side scripts.tts_model check failed with permission
  denied; no host permission was changed.
- docker compose --env-file .env -f compose.yaml config --quiet — exit 0.
  Candidate rendering with pinned SOURCE_REVISION and model digest resolved
  the expected image, GPU device and staged model path.
- SOURCE_REVISION=f410fa7b46b5f0414f16c08f0509367771703179 docker compose
  --env-file .env -f compose.yaml build gateway — exit 0; Go builds passed
  and Go module download was cached. No TTS/STT image build was run.
- Per-service Compose up commands with --no-deps for tts, then gateway —
  executed; candidate worker and current Gateway became healthy. STT was
  untouched.
- Gateway urllib requests for four fixed texts, voice listing, fast mode,
  invalid language and unknown field — executed with outcomes above. Private
  state/warm-up requests, cancellation, simultaneous STT/TTS and recovery
  request — executed with outcomes above.
- An initial host-side warm-up request to 127.0.0.1:8082 was refused because
  the worker port is private and not published. The warm-up was then invoked
  with docker exec inside the TTS worker and succeeded.
- Compose stop -t 240 tts followed by compose start tts — executed; clean
  exit and healthy restart recorded above.
- Static rendering of private/m03b/rollback/compose.yaml with
  SOURCE_REVISION=3aa5f68c1d9a058ed2714b7b257c5b258a23c00a — exit 0; prior
  image tags and historical TTS config resolved. This was not a rollback.
- git diff --check — exit 0 after the live evidence and milestone record edits.

## M03B closeout evidence update — 2026-10-22

- **OBSERVED (operator-reported):** The operator listened to all four
  quality-mode recordings in the private M03B listening pack—English, Russian,
  Swedish and mixed-language—and confirmed that all sound good. This is a
  PASS for listening acceptance of the tested quality-mode baseline. It is
  recorded in [user-validation.md](user-validation.md); no subjective result
  is inferred from file metadata.
- **OBSERVED (local verification, 2026-10-22):** `make verify
  PYTHON=.venv/bin/python` exited 0. This included Go vet, Ruff lint and format
  checks, tracked configuration and Compose validation, release checks, Go
  race tests, Python unit tests (64 passed), Go build, Python syntax parsing,
  governance validation, and STT/TTS dependency-lock checks (68 exact hashed
  TTS package pins).
- **OBSERVED (local verification, 2026-10-22):** `git diff --check` exited 0
  after the closeout record updates.
- **INTERPRETATION:** M03B meets the agreed implementation and technical
  validation scope, and the operator has accepted the four tested quality-mode
  samples. The prior live technical measurements remain accurately bounded:
  one short STT/TTS overlap is observed, but sustained concurrent-load behavior
  is not established; cold model loading remains significant.
- **NOT ESTABLISHED / OPEN LIMITATIONS:** Fast mode remains unavailable.
  Production licensing is not fully cleared. Sustained concurrent-load
  behavior remains unestablished. Cold-model loading latency remains
  significant. These limits do not reverse the bounded M03B completion and do
  not establish unrestricted production readiness.
