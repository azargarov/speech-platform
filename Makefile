PYTHON ?= python3
COMPOSE = docker compose -f deployments/compose/compose.yaml
IMAGE_SERVICES := gateway stt tts
IMAGE_SERVICE := $(strip $(SERVICE))
IMAGE_SELECTION :=
IMAGE_VARIANT := $(if $(strip $(VARIANT)),$(strip $(VARIANT)),cpu)
IMAGE_COMPOSE_FILE := deployments/compose/compose.stt-cpu.yaml
PUBLISH_SERVICE := $(strip $(SERVICE))
PUBLISH_SELECTION :=
PUBLISH_VERSION := $(strip $(VERSION))
PUBLISH_VARIANT := $(if $(strip $(VARIANT)),$(strip $(VARIANT)),cuda)
PLATFORM_RELEASE ?= releases/voiceservice-v0.1.2.yaml
ENABLED_SERVICES_CONFIG ?= private/deployment/enabled-services.yaml
SERVICES_DEPLOYMENT_CONFIG ?= private/deployment/services.yaml
GATEWAY_DEPLOYMENT_CONFIG ?= private/deployment/gateway.yaml
TTS_DEPLOYMENT_CONFIG ?= private/deployment/tts.yaml
MODEL_STORE ?= /srv/speech-platform/models
MODEL_READ_GID ?= 988
MODEL_READ_GROUP ?= $(shell getent group $(MODEL_READ_GID) | cut -d: -f1)
TTS_MODEL_STORE ?= $(MODEL_STORE)
TTS_MODEL_READ_GID ?= $(MODEL_READ_GID)
TTS_MODEL_READ_GROUP ?= $(shell getent group $(TTS_MODEL_READ_GID) | cut -d: -f1)
TTS_MODEL_OWNER_UID ?= 0
SOURCE_REVISION ?= $(shell git rev-parse HEAD)
LOCK_ROOT ?= $(SPEECH_PLATFORM_LOCK_ROOT)
PROFILE ?= regular
ifneq ($(filter legacy-plan legacy-install,$(MAKECMDGOALS)),)
ifeq ($(PROFILE),regular)
STT_DEPLOYMENT_DIR := private/deployment/stt-cuda
else ifeq ($(PROFILE),experimental)
STT_DEPLOYMENT_DIR := private/deployment/stt-cuda-experimental
else
$(error Unknown deployment PROFILE '$(PROFILE)'; choose regular or experimental)
endif
override STT_DEPLOYMENT_PROFILE := $(STT_DEPLOYMENT_DIR)/profile.yaml
override STT_APPLICATION_CONFIG := $(STT_DEPLOYMENT_DIR)/stt-application.yaml
override STT_DEPLOYMENT_CONFIG := $(STT_DEPLOYMENT_DIR)/stt-deployment.yaml
override STT_WORKER_CONFIG := $(STT_DEPLOYMENT_DIR)/stt.yaml
override STT_COMPOSE_ENV := $(STT_DEPLOYMENT_DIR)/compose.env
endif
ifneq ($(filter image,$(MAKECMDGOALS)),)
ifeq ($(filter $(IMAGE_VARIANT),cpu cuda),)
$(error Unknown image VARIANT '$(IMAGE_VARIANT)'; choose cpu or cuda)
endif
ifneq ($(IMAGE_VARIANT),cpu)
IMAGE_COMPOSE_FILE := deployments/compose/compose.stt-cuda-build.yaml
endif
ifeq ($(IMAGE_SERVICE),)
IMAGE_SELECTION := $(IMAGE_SERVICES)
else ifeq ($(IMAGE_SERVICE),gateway)
IMAGE_SELECTION := gateway
else ifeq ($(IMAGE_SERVICE),stt)
IMAGE_SELECTION := stt
else ifeq ($(IMAGE_SERVICE),tts)
IMAGE_SELECTION := tts
else
$(error Unknown image service '$(SERVICE)'; choose gateway, stt, or tts)
endif
endif
ifneq ($(filter publish,$(MAKECMDGOALS)),)
ifeq ($(filter $(PUBLISH_VARIANT),cpu cuda),)
$(error Unknown publish VARIANT '$(PUBLISH_VARIANT)'; choose cpu or cuda)
endif
ifeq ($(PUBLISH_SERVICE),)
PUBLISH_SELECTION := gateway stt tts
else ifeq ($(PUBLISH_SERVICE),gateway)
PUBLISH_SELECTION := gateway
else ifeq ($(PUBLISH_SERVICE),stt)
PUBLISH_SELECTION := stt
else ifeq ($(PUBLISH_SERVICE),tts)
PUBLISH_SELECTION := tts
else
$(error Unknown publish service '$(SERVICE)'; choose gateway, stt, or tts)
endif
endif
.PHONY: verify fmt lint config test build image publish compose-check bootstrap governance-check stt-lock-check tts-lock-check release-check model-check model-fetch tts-model-check tts-model-fetch tts-warmup tts-state plan install legacy-plan legacy-install status logs test-stt stt-cpu-integration stt-cuda-http-integration
bootstrap:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install --require-hashes -r services/requirements-stt-cpu.lock
	go mod download
fmt:
	gofmt -w cmd internal
	$(PYTHON) -m ruff format services scripts
lint:
	@test -z "$$(gofmt -l cmd internal)"
	go vet ./...
	$(PYTHON) -m ruff check services scripts
	$(PYTHON) -m ruff format --check services scripts
config:
	go run ./cmd/gateway --config configs/gateway.yaml --check-config
	$(PYTHON) -m services.stt.main --config configs/stt.yaml --check-config
	$(PYTHON) -m services.stt.main --config configs/stt.yaml --application-config configs/stt-product-application.yaml --deployment-config configs/stt-product-deployment.yaml --check-config
	$(PYTHON) -m services.tts.main --config configs/tts.yaml --check-config
compose-check:
	$(COMPOSE) config --quiet
	docker compose --env-file .env.example -f compose.yaml config --quiet
	docker compose --env-file .env.example -f compose.yaml -f deployments/compose/compose.ollama.yaml config --format json | $(PYTHON) -c 'import json,sys; c=json.load(sys.stdin); g=c["services"]["gateway"]; n=c["networks"]["ollama_private"]; assert set(g["networks"]) == {"publish", "stt_private", "tts_private", "ollama_private"}; assert set(c["services"]["stt"]["networks"]) == {"stt_private"}; assert set(c["services"]["tts"]["networks"]) == {"tts_private"}; assert n["external"] is True and n["name"] == "speech-platform_ollama_private"; assert g["ports"][0]["host_ip"] == "127.0.0.1"; print("PASS: optional Ollama network Compose overlay")'
	$(COMPOSE) config --format json | $(PYTHON) scripts/check_compose.py
	STT_CPU_LOCK_SHA256=$$(sha256sum services/requirements-stt-cpu.lock | cut -d' ' -f1) STT_APPLICATION_CONFIG=$(CURDIR)/configs/stt-application-cpu.example.yaml STT_DEPLOYMENT_CONFIG=$(CURDIR)/configs/stt-deployment-cpu.example.yaml STT_MODEL_ROOT=/models docker compose -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cpu.yaml config --format json | $(PYTHON) scripts/check_compose.py
	SOURCE_REVISION=$$(git rev-parse HEAD) STT_CUDA_LOCK_SHA256=$$(sha256sum services/requirements-stt-cuda.lock | cut -d' ' -f1) STT_APPLICATION_CONFIG=$(CURDIR)/configs/stt-application-cpu.example.yaml STT_DEPLOYMENT_CONFIG=$(CURDIR)/configs/stt-deployment-cpu.example.yaml STT_MODEL_ROOT=/models docker compose -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda-build.yaml config --quiet
	# Static-only sentinels for rendering validation; never use this command to start services.
	STT_CUDA_STATIC_CHECK=1 STT_COMPOSE_PROJECT_NAME=speech-platform-static STT_CUDA_IMAGE=registry.example.invalid/static-check@sha256:0000000000000000000000000000000000000000000000000000000000000000 STT_IMAGE_IDENTITY_MODE=registry_digest STT_IMAGE_ID=sha256:0000000000000000000000000000000000000000000000000000000000000000 STT_PLATFORM=linux/amd64 STT_SOURCE_REVISION=0000000000000000000000000000000000000000 STT_CUDA_LOCK_SHA256=68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14 STT_APPLICATION_CONFIG=$(CURDIR)/configs/stt-application-cuda.example.yaml STT_DEPLOYMENT_CONFIG=$(CURDIR)/configs/stt-deployment-cuda.example.yaml STT_WORKER_CONFIG=$(CURDIR)/configs/stt.yaml STT_MODEL_HOST_ROOT=/models STT_ARTIFACT_GID=1000 STT_HOST_GPU_DEVICE_ID=0 STT_MEMORY_LIMIT_BYTES=12884901888 STT_CPU_LIMIT=4 STT_PIDS_LIMIT=128 STT_STOP_GRACE_PERIOD_SECONDS=15 STT_DEPLOYMENT_PROFILE_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_MODEL_MANIFEST_SHA256=86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6 STT_MODEL_REVISION=0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf STT_APPLICATION_CONFIG_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_DEPLOYMENT_CONFIG_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_WORKER_CONFIG_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_CONFIGURATION_SET_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_HEALTHCHECK_INTERVAL_SECONDS=10 STT_HEALTHCHECK_TIMEOUT_SECONDS=3 STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS=2 STT_HEALTHCHECK_RETRIES=3 STT_HEALTHCHECK_START_PERIOD_SECONDS=130 STT_LISTEN_PORT=8081 docker compose -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda.yaml --profile cuda config --format json | $(PYTHON) scripts/check_compose.py
test:
	go test -race ./...
	$(PYTHON) -m unittest discover -s scripts -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s services/stt/tests -p 'test_*.py' -v
build:
	go build ./...
	$(PYTHON) -c 'import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path("services").rglob("*.py")]'
image:
	@if [ "$(IMAGE_SERVICE)" = "tts" ]; then SOURCE_REVISION="$(SOURCE_REVISION)" docker compose --env-file .env.example -f compose.yaml build tts; else SOURCE_REVISION="$(SOURCE_REVISION)" STT_CPU_LOCK_SHA256="$$(sha256sum services/requirements-stt-cpu.lock | cut -d' ' -f1)" STT_CUDA_LOCK_SHA256="$$(sha256sum services/requirements-stt-cuda.lock | cut -d' ' -f1)" STT_APPLICATION_CONFIG="$(CURDIR)/configs/stt-application-cpu.example.yaml" STT_DEPLOYMENT_CONFIG="$(CURDIR)/configs/stt-deployment-cpu.example.yaml" STT_MODEL_ROOT=/models $(COMPOSE) -f $(IMAGE_COMPOSE_FILE) build $(IMAGE_SELECTION); fi
	@if [ -z "$(IMAGE_SERVICE)" ]; then SOURCE_REVISION="$(SOURCE_REVISION)" docker compose --env-file .env.example -f compose.yaml build tts; fi
publish:
	$(PYTHON) scripts/publish_images.py --version "$(PUBLISH_VERSION)" --services "$(PUBLISH_SELECTION)" --variant "$(PUBLISH_VARIANT)"
release-check:
	$(PYTHON) -m scripts.check_release --release "$(PLATFORM_RELEASE)"
model-check:
	$(PYTHON) -m scripts.provision_models check --release "$(PLATFORM_RELEASE)" --store "$(MODEL_STORE)"
model-fetch:
	$(PYTHON) -m scripts.provision_models fetch --release "$(PLATFORM_RELEASE)" --store "$(MODEL_STORE)"
tts-model-check:
	$(PYTHON) -m scripts.tts_model check --store "$(TTS_MODEL_STORE)"
tts-model-fetch:
	@if [ "$(TTS_MODEL_OWNER_UID)" = "0" ]; then sudo -n -g "$(TTS_MODEL_READ_GROUP)" $(PYTHON) -m scripts.tts_model fetch --store "$(TTS_MODEL_STORE)" --reader-gid "$(TTS_MODEL_READ_GID)" --owner-uid "$(TTS_MODEL_OWNER_UID)"; else $(PYTHON) -m scripts.tts_model fetch --store "$(TTS_MODEL_STORE)" --reader-gid "$(TTS_MODEL_READ_GID)" --owner-uid "$(TTS_MODEL_OWNER_UID)"; fi
tts-lock-check:
	$(PYTHON) scripts/check_tts_lock.py
tts-warmup:
	docker compose --env-file .env -f compose.yaml exec -T tts python -c 'import urllib.request; print(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8082/internal/v1/warmup", data=b"", method="POST"), timeout=600).read().decode())'
tts-state:
	docker compose --env-file .env -f compose.yaml exec -T tts python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8082/internal/v1/state", timeout=3).read().decode())'
plan:
	$(PYTHON) scripts/product_deployment.py plan
install:
	$(PYTHON) scripts/product_deployment.py install $(if $(SERVICE),--service "$(SERVICE)")
status:
	$(PYTHON) scripts/product_deployment.py status
logs:
	$(PYTHON) scripts/product_deployment.py logs
test-stt:
	$(PYTHON) scripts/product_deployment.py test-stt $(if $(AUDIO),--audio "$(AUDIO)") $(if $(SOURCE_LANGUAGE),--source-language "$(SOURCE_LANGUAGE)") $(if $(OUTPUT_LANGUAGE),--output-language "$(OUTPUT_LANGUAGE)")
legacy-plan:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.stt_deployment plan --service "$(SERVICE)" --enabled-services "$(ENABLED_SERVICES_CONFIG)" --services-profile "$(SERVICES_DEPLOYMENT_CONFIG)" --gateway-config "$(GATEWAY_DEPLOYMENT_CONFIG)" --tts-config "$(TTS_DEPLOYMENT_CONFIG)" --profile "$(STT_DEPLOYMENT_PROFILE)" --application-config "$(STT_APPLICATION_CONFIG)" --deployment-config "$(STT_DEPLOYMENT_CONFIG)" --worker-config "$(STT_WORKER_CONFIG)" --release "$(PLATFORM_RELEASE)" --env-file "$(STT_COMPOSE_ENV)"
legacy-install:
	SPEECH_PLATFORM_LOCK_ROOT="$(LOCK_ROOT)" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m scripts.stt_deployment install --service "$(SERVICE)" --enabled-services "$(ENABLED_SERVICES_CONFIG)" --services-profile "$(SERVICES_DEPLOYMENT_CONFIG)" --gateway-config "$(GATEWAY_DEPLOYMENT_CONFIG)" --tts-config "$(TTS_DEPLOYMENT_CONFIG)" --profile "$(STT_DEPLOYMENT_PROFILE)" --application-config "$(STT_APPLICATION_CONFIG)" --deployment-config "$(STT_DEPLOYMENT_CONFIG)" --worker-config "$(STT_WORKER_CONFIG)" --release "$(PLATFORM_RELEASE)" --env-file "$(STT_COMPOSE_ENV)"
governance-check:
	$(PYTHON) scripts/validate_governance.py
	$(PYTHON) -m unittest discover -s scripts -p 'test_governance.py' -v
stt-lock-check:
	$(PYTHON) scripts/check_stt_locks.py
stt-cpu-integration:
	@test -n "$(STT_APPLICATION_CONFIG)" -a -n "$(STT_DEPLOYMENT_CONFIG)" -a -n "$(STT_SMOKE_AUDIO)" || (echo "set STT_APPLICATION_CONFIG, STT_DEPLOYMENT_CONFIG and STT_SMOKE_AUDIO to local provisioned files" >&2; exit 2)
	PYTHONPATH=. $(PYTHON) scripts/stt_cpu_smoke.py
stt-cuda-http-integration:
	@test -n "$(STT_CUDA_INPUT_DIR)" -a -n "$(STT_SMOKE_AUDIO)" -a -n "$(STT_CUDA_AUDIO_MEDIA_TYPE)" -a -n "$(STT_AUDIO_CHECKSUM_FILE)" -a -n "$(STT_MODEL_HOST_ROOT)" -a -n "$(STT_CUDA_ATTEMPT_ROOT)" -a -n "$(STT_CUDA_ATTEMPT_ID)" -a -n "$(STT_CUDA_IMAGE_ID)" -a -n "$(STT_CUDA_LOCK_SHA256)" -a -n "$(STT_CUDA_MODEL_REVISION)" -a -n "$(STT_CUDA_MODEL_MANIFEST_SHA256)" -a -n "$(STT_CUDA_SHARED_GID)" -a -n "$(STT_CUDA_PLATFORM)" -a -n "$(STT_CUDA_HTTP_CPU_LIMIT)" -a -n "$(STT_CUDA_HTTP_MEMORY_BYTES)" -a -n "$(STT_CUDA_HTTP_PIDS_LIMIT)" -a -n "$(STT_CUDA_HTTP_DEADLINE_SECONDS)" -a -n "$(STT_CUDA_HTTP_GRACE_SECONDS)" || (echo "provide the C.3 experiment inputs, image, approved artifact identities, attempt settings and resource limits; see docs/operations/stt-cuda-http-integration.md" >&2; exit 2)
	@test -f "$(STT_CUDA_INPUT_DIR)/stt-application.yaml" -a -f "$(STT_CUDA_INPUT_DIR)/stt-deployment.yaml" -a -e "$(STT_CUDA_INPUT_DIR)/smoke-audio" -a -e "$(STT_CUDA_INPUT_DIR)/smoke-audio.sha256" -a -d "$(STT_MODEL_HOST_ROOT)" || (echo "C.3 inputs, nested audio mount placeholders and model root must be present" >&2; exit 2)
	@set -eu; \
	device_index=$$(PYTHONPATH=. $(PYTHON) -c 'import sys; from services.stt.config import load_deployment_config; print(load_deployment_config(sys.argv[1]).cuda_device_index)' "$(STT_CUDA_INPUT_DIR)/stt-deployment.yaml"); \
	PYTHONPATH=. $(PYTHON) scripts/launch_stt_cuda_diagnostic.py \
	  --cuda-http-profile \
	  --attempt-root "$(STT_CUDA_ATTEMPT_ROOT)" \
	  --shared-gid "$(STT_CUDA_SHARED_GID)" \
	  --attempt-id "$(STT_CUDA_ATTEMPT_ID)" \
	  --container-name "$(STT_CUDA_ATTEMPT_ID)" \
	  --image-id "$(STT_CUDA_IMAGE_ID)" \
	  --platform "$(STT_CUDA_PLATFORM)" \
	  --application-config "$(STT_CUDA_INPUT_DIR)/stt-application.yaml" \
	  --deployment-config "$(STT_CUDA_INPUT_DIR)/stt-deployment.yaml" \
	  --lock-file "$(CURDIR)/services/requirements-stt-cuda.lock" \
	  --lock-sha256 "$(STT_CUDA_LOCK_SHA256)" \
	  --model-revision "$(STT_CUDA_MODEL_REVISION)" \
	  --model-manifest-sha256 "$(STT_CUDA_MODEL_MANIFEST_SHA256)" \
	  --audio-file "$(STT_SMOKE_AUDIO)" \
	  --audio-checksum-file "$(STT_AUDIO_CHECKSUM_FILE)" \
	  --timeout-seconds "$(STT_CUDA_HTTP_DEADLINE_SECONDS)" \
	  --grace-seconds "$(STT_CUDA_HTTP_GRACE_SECONDS)" \
	  -- docker run --rm --network none --platform "$(STT_CUDA_PLATFORM)" --pull never --read-only \
	    --name "$(STT_CUDA_ATTEMPT_ID)" --cidfile '{attempt_dir}/container.id' \
	    --user 65532:65532 --group-add "$(STT_CUDA_SHARED_GID)" --entrypoint python \
	    --gpus "device=$$device_index" --memory "$(STT_CUDA_HTTP_MEMORY_BYTES)" --cpus "$(STT_CUDA_HTTP_CPU_LIMIT)" --pids-limit "$(STT_CUDA_HTTP_PIDS_LIMIT)" \
	    --mount "type=bind,src={harness_dir},dst=/results" \
	    --mount "type=bind,src=$(STT_CUDA_INPUT_DIR),dst=/input,readonly" \
	    --mount "type=bind,src=$(STT_SMOKE_AUDIO),dst=/input/smoke-audio,readonly" \
	    --mount "type=bind,src=$(STT_AUDIO_CHECKSUM_FILE),dst=/input/smoke-audio.sha256,readonly" \
	    --mount "type=bind,src=$(STT_MODEL_HOST_ROOT),dst=/models,readonly" \
	    --mount "type=bind,src=$(CURDIR)/scripts,dst=/opt/validation/scripts,readonly" \
	    --mount "type=bind,src=$(CURDIR)/services,dst=/opt/validation/services,readonly" \
	    --mount "type=bind,src=$(CURDIR)/configs,dst=/opt/validation/configs,readonly" \
	    --workdir /opt/validation --env HF_HUB_OFFLINE=1 --env TRANSFORMERS_OFFLINE=1 --env PYTHONPATH=/opt/validation \
	    "$(STT_CUDA_IMAGE_ID)" scripts/stt_cuda_http_smoke.py \
	      --application-config /input/stt-application.yaml \
	      --deployment-config /input/stt-deployment.yaml \
	      --worker-config /opt/validation/configs/stt.yaml \
	      --audio /input/smoke-audio \
	      --audio-media-type "$(STT_CUDA_AUDIO_MEDIA_TYPE)" \
	      --audio-checksum-file /input/smoke-audio.sha256 \
	      --lock /opt/validation/services/requirements-stt-cuda.lock \
	      --approved-lock-sha256 "$(STT_CUDA_LOCK_SHA256)" \
	      --model-revision "$(STT_CUDA_MODEL_REVISION)" \
	      --model-manifest-sha256 "$(STT_CUDA_MODEL_MANIFEST_SHA256)" \
	      --report /results/harness-report.json \
	      --request-count "$(if $(STT_CUDA_HTTP_REQUEST_COUNT),$(STT_CUDA_HTTP_REQUEST_COUNT),1)" \
	      --maximum-request-count "$(if $(STT_CUDA_HTTP_MAX_REQUEST_COUNT),$(STT_CUDA_HTTP_MAX_REQUEST_COUNT),1)" \
	      --overall-deadline-seconds "$(STT_CUDA_HTTP_DEADLINE_SECONDS)" \
	      --resource-sample-interval-seconds "$(if $(STT_CUDA_RESOURCE_SAMPLE_INTERVAL_SECONDS),$(STT_CUDA_RESOURCE_SAMPLE_INTERVAL_SECONDS),disabled)"
verify: lint config compose-check release-check test build governance-check stt-lock-check tts-lock-check
