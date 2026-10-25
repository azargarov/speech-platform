# D03 — Verification Record

Date: 2026-10-25. Target: private `llm` Docker host. Environment: root checkout
`/home/master/speech-platform`, Docker context `default`.

## Initial state and pre-mutation checks

**OBSERVED — initial Git and production state:**

- Git HEAD was `2bfc0089cf8282b4fad9b20914ac1bc0128a7915` (D02 documentation
  closeout); the tracked and untracked worktree was clean. This differed from
  the requested deployed software revision `2ec766855c5c355bd312c47bb79549cf99c80b1f`.
- `make status` showed Gateway, STT and TTS healthy, zero restarts, and source
  labels at the requested deployed revision `2ec766855c5c355bd312c47bb79549cf99c80b1f`.

| Service | Initial container | Initial image ID | Source revision |
| --- | --- | --- | --- |
| Gateway | `0d529b5e52ba` | `sha256:13199aab05368b1da662057178a89a0688ce17c9e35765d2f88dee242e1d23db` | `2ec766855c5c355bd312c47bb79549cf99c80b1f` |
| STT | `d2fb8e36909e` | `sha256:b8a2c25c853cd76803502509dea2a2e7da952918be2f9fde6dc140f3e4cc9fb87c` | `2ec766855c5c355bd312c47bb79549cf99c80b1f` |
| TTS | `832ea8ab6eb0` | `sha256:c7c10e283fa898ce6a8951bd20d7e3824010e0ffb22cc4bab04c83ca561941d6` | `2ec766855c5c355bd312c47bb79549cf99c80b1f` |

**OBSERVED — retained rollback objects:** all three exact image objects existed
locally and their pre-existing `speech-platform-rollback-<service>:<image-id>`
tags resolved to the full image IDs. Role and source labels were:

| Service | Exact rollback image ID | Source label | Role label |
| --- | --- | --- | --- |
| Gateway | `sha256:105b8ab16496d9160d267fa3ab5a9f1e4250d8eb6231987e92553122aa38c320` | `9329b574bb5a21fa101d830e26202ff6707b4c4e` | `gateway` |
| STT | `sha256:7e89999512a2a2e7da952616cce78a9f252918be2f9fde6dc140f3e4cc9fb87c` | `9329b574bb5a21fa101d830e26202ff6707b4c4e` | `stt-worker` |
| TTS | `sha256:2fe78236c87ea0e3c9b63e565fedfb32cc73fe20a2f596987f41c252ea03a5b7` | `9329b574bb5a21fa101d830e26202ff6707b4c4e` | `tts-worker` |

**OBSERVED — configuration compatibility:** the pre-D02 private `.env`
backup is mode `0600`, but it contains the two obsolete Gateway image pins and
current preflight rejects it. After excluding only those obsolete keys, its
remaining values matched the active `.env`; the API token and cloud settings
were identical. Current tracked configuration/API schemas had no source
differences between the retained image revision and `2ec7668…`. The exact old
Gateway, STT and TTS image config parsers accepted the active Gateway YAML and
tracked worker configurations in disposable, read-only `--network none`
containers. Current `.env` preflight passed.

A fresh protected bundle was created at
`private/deployment-backups/d03-rollback-20261025T110233Z/`. The bundle `.env`
is `0600`, its directory is `0700`, the Gateway YAML copy is byte-identical to
the active file, and preflight validation passed. The API token value was
verified unchanged without displaying it. The bundle's Compose config rendered
with only Gateway/STT/TTS, the fixed project, loopback Gateway publication,
read-only config/model mounts, private worker networks, no named volumes and
the existing external Ollama network. The build definitions remain in the
Compose model, but the rollback invocation uses `--no-build --pull never`.

The pre-mutation `sg stt-model-reader -c 'make preflight PYTHON=.venv/bin/python'`
passed with PASS=34, WARN=1, FAIL=0, SKIP=2; model metadata, local Ollama
eligibility, network and tags checks passed. No inference occurred during
preflight.

## Rollback rehearsal

**OBSERVED — local rollback aliases:** exact retained IDs were tagged as:

```sh
docker tag sha256:105b8ab16496d9160d267fa3ab5a9f1e4250d8eb6231987e92553122aa38c320 speech-platform-gateway:d03-rollback-20261025T110233Z
docker tag sha256:7e89999512a2a2e7da952616cce78a9f252918be2f9fde6dc140f3e4cc9fb87c speech-platform-stt-cuda:d03-rollback-20261025T110233Z
docker tag sha256:2fe78236c87ea0e3c9b63e565fedfb32cc73fe20a2f596987f41c252ea03a5b7 speech-platform-tts:d03-rollback-20261025T110233Z
```

`docker image inspect` verified each new local alias resolved to its selected
full ID before Compose render and immediately before rollback. The exact
rollback command executed was:

```sh
SOURCE_REVISION=d03-rollback-20261025T110233Z GATEWAY_IMAGE=speech-platform-gateway:d03-rollback-20261025T110233Z docker --context default compose --project-name speech-platform --env-file private/deployment-backups/d03-rollback-20261025T110233Z/.env -f compose.yaml -f deployments/compose/compose.ollama.yaml up -d --no-build --pull never --wait --wait-timeout 240 gateway stt tts
```

**PASS — rollback health and exact identity:** all three services became
healthy. Running image IDs exactly matched the selected objects and source
labels were `9329b574bb5a21fa101d830e26202ff6707b4c4e`; restart counts were
zero. Containers used only canonical Compose files, preserving Make ownership
checks.

| Service | Rollback container | Exact image ID | Restarts | Health |
| --- | --- | --- | ---: | --- |
| Gateway | `80fc4bac6c4a` | `sha256:105b8ab16496d9160d267fa3ab5a9f1e4250d8eb6231987e92553122aa38c320` | 0 | healthy |
| STT | `2ea035688b39` | `sha256:7e89999512a2a2e7da952616cce78a9f252918be2f9fde6dc140f3e4cc9fb87c` | 0 | healthy |
| TTS | `a7fecb9c03ff` | `sha256:2fe78236c87ea0e3c9b63e565fedfb32cc73fe20a2f596987f41c252ea03a5b7` | 0 | healthy |

**PASS — authenticated local API smoke:** one corrected `make test-stt`
evidence capture returned HTTP success and sanitized metadata
`source_language=en`, `output_language=en`, `translated=false`. The transcript
was suppressed and not stored. A preceding capture wrapper expected JSON on
the first output line and reported a wrapper parse failure; its underlying
`make test-stt` subprocess exited 0. The corrected run captured the Make
command's later JSON line. No API error was observed.

One authenticated local `POST /v1/tts/speech` returned HTTP 200, valid
`audio/wav`, 445,484 bytes at 48 kHz, in 96.305 seconds. Audio was held in
memory and not saved. Neither request contacted a cloud provider; active
Gateway config has `allow_cloud=false`.

## Restoration

**OBSERVED — restoration:** D03 documentation was stashed while the clean
committed target was checked out at the intended revision. The following
commands passed:

```sh
git switch --detach 2ec766855c5c355bd312c47bb79549cf99c80b1f
sg stt-model-reader -c 'make preflight PYTHON=.venv/bin/python'
sg stt-model-reader -c 'make install PYTHON=.venv/bin/python'
sg stt-model-reader -c 'make status PYTHON=.venv/bin/python'
```

Make install preflight reported PASS=34, WARN=1, FAIL=0, SKIP=2. All Docker
build layers used the local cache; no model artifacts were downloaded. The
known Dockerfile `InvalidDefaultArgInFrom` lint warning recurred; configured
builds, image identity checks and both disposable CUDA probes succeeded.
Compose recreated only the three SpeechPlatform services and all became
healthy. The final deployment source label is the intended
`2ec766855c5c355bd312c47bb79549cf99c80b1f`.

| Service | Restored container | Restored image ID | Restarts | Health | Source |
| --- | --- | --- | ---: | --- | --- |
| Gateway | `a78d0bec26b6` | `sha256:dd7e62e8f84ecd1c68d19b84f75afc91fdc6b8d16c41f68a596d0d327ce9533d` | 0 | healthy | `2ec766855c5c355bd312c47bb79549cf99c80b1f` |
| STT | `54aec1e0839a` | `sha256:6cd42f66f173a9c212015c94746dacbd966d1ce62b98b5a569160810b8a09e47` | 0 | healthy | `2ec766855c5c355bd312c47bb79549cf99c80b1f` |
| TTS | `8867bcbb3d3f` | `sha256:a63ef5ac449b9a6def2ef33a0a0e68b05ddf6506c0fc8c98ec34b009309ecd94` | 0 | healthy | `2ec766855c5c355bd312c47bb79549cf99c80b1f` |

**PASS — restored local API smoke:** authenticated STT returned HTTP success
and sanitized English metadata. One authenticated TTS synthesis returned HTTP
200 with a valid 445,484-byte 48 kHz WAV in 95.325 seconds. No transcript or
audio was saved. Cloud remained disabled.

After restoration, Git was returned to `main` at the D02 documentation closeout
commit `2bfc0089cf8282b4fad9b20914ac1bc0128a7915`; D03 documentation was
reapplied. The running services remain at software source `2ec7668…` as
intended.

**PASS — preservation comparison:** the active `.env`, original D02 backup and
active Gateway config hashes were unchanged from pre-rollback. The D03 private
bundle validates and remains mode-restricted. STT/TTS model-store metadata tree
fingerprints matched pre-rollback; current containers mount model stores
read-only. All 13 tracked network IDs were unchanged; no named SpeechPlatform
volumes existed before or after. The shared Ollama ID, image, start time and
restart count were unchanged. All unrelated container IDs, images, start times,
states and restart counts matched the pre-rollback snapshot. No cloud call,
network change, Docker prune or model-store write occurred.

## Offline validation

**OBSERVED — after documentation changes:**

- `make verify PYTHON=.venv/bin/python` — PASS (exit 0). Included Go vet,
  Ruff check/format, configuration and Compose checks, release and lock checks,
  race-enabled Go tests, 92 script tests, 63 dedicated TTS/SSML tests, AST
  parsing and governance validation (including local documentation references).
- `git diff --check` — PASS (exit 0).
- Final `sg stt-model-reader -c 'make status PYTHON=.venv/bin/python'` — PASS.
  Gateway, STT and TTS are running and healthy on image IDs
  `sha256:dd7e62e8f84ecd1c68d19b84f75afc91fdc6b8d16c41f68a596d0d327ce9533d`,
  `sha256:6cd42f66f173a9c212015c94746dacbd966d1ce62b98b5a569160810b8a09e47`,
  and
  `sha256:a63ef5ac449b9a6def2ef33a0a0e68b05ddf6506c0fc8c98ec34b009309ecd94`,
  respectively, each with source label
  `2ec766855c5c355bd312c47bb79549cf99c80b1f`.

Final Git HEAD is `2bfc0089cf8282b4fad9b20914ac1bc0128a7915` on `main`;
this is the D02 documentation closeout commit, while deployed service images
were rebuilt from the intended `2ec766855c5c355bd312c47bb79549cf99c80b1f`
source revision. The worktree contains only the D03 documentation changes
listed in the qualification report; no commit was made.

## NOT ESTABLISHED

- Exact rollback selection is verified via local aliases mapped to full IDs;
  Docker tags are mutable and must be reinspected before each rollback.
- The original pre-D02 `.env` backup remains rejected by current preflight due
  obsolete image pins. This rehearsal used the validated D03 snapshot of the
  active configuration instead.
- Concurrent local LLM inference and TTS cold-loading remains unqualified.
- Operator D03 closeout was accepted on 2026-10-25. D04 is now authorized and
  in progress; its deployment regression is recorded separately.
