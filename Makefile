PYTHON ?= python3
COMPOSE = docker compose -f deployments/compose/compose.yaml
.PHONY: verify fmt lint config test build compose-check bootstrap governance-check stt-lock-check stt-cpu-integration stt-cuda-http-integration
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
	$(PYTHON) -m services.tts.main --config configs/tts.yaml --check-config
compose-check:
	$(COMPOSE) config --quiet
	$(COMPOSE) config --format json | $(PYTHON) scripts/check_compose.py
	STT_APPLICATION_CONFIG=$(CURDIR)/configs/stt-application-cpu.example.yaml STT_DEPLOYMENT_CONFIG=$(CURDIR)/configs/stt-deployment-cpu.example.yaml STT_MODEL_ROOT=/models docker compose -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cpu.yaml config --format json | $(PYTHON) scripts/check_compose.py
	# Static-only sentinels for rendering validation; never use this command to start services.
	STT_CUDA_STATIC_CHECK=1 STT_COMPOSE_PROJECT_NAME=speech-platform-static STT_CUDA_IMAGE=registry.example.invalid/static-check@sha256:0000000000000000000000000000000000000000000000000000000000000000 STT_IMAGE_IDENTITY_MODE=registry_digest STT_IMAGE_ID=sha256:0000000000000000000000000000000000000000000000000000000000000000 STT_PLATFORM=linux/amd64 STT_SOURCE_REVISION=0000000000000000000000000000000000000000 STT_CUDA_LOCK_SHA256=68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14 STT_APPLICATION_CONFIG=$(CURDIR)/configs/stt-application-cuda.example.yaml STT_DEPLOYMENT_CONFIG=$(CURDIR)/configs/stt-deployment-cuda.example.yaml STT_WORKER_CONFIG=$(CURDIR)/configs/stt.yaml STT_MODEL_HOST_ROOT=/models STT_ARTIFACT_GID=1000 STT_HOST_GPU_DEVICE_ID=0 STT_MEMORY_LIMIT_BYTES=12884901888 STT_CPU_LIMIT=4 STT_PIDS_LIMIT=128 STT_STOP_GRACE_PERIOD_SECONDS=15 STT_DEPLOYMENT_PROFILE_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_MODEL_MANIFEST_SHA256=86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6 STT_MODEL_REVISION=0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf STT_APPLICATION_CONFIG_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_DEPLOYMENT_CONFIG_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_WORKER_CONFIG_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_CONFIGURATION_SET_SHA256=0000000000000000000000000000000000000000000000000000000000000000 STT_HEALTHCHECK_INTERVAL_SECONDS=10 STT_HEALTHCHECK_TIMEOUT_SECONDS=3 STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS=2 STT_HEALTHCHECK_RETRIES=3 STT_HEALTHCHECK_START_PERIOD_SECONDS=130 STT_LISTEN_PORT=8081 docker compose -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda.yaml --profile cuda config --format json | $(PYTHON) scripts/check_compose.py
test:
	go test -race ./...
	$(PYTHON) -m unittest discover -s scripts -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s services/stt/tests -p 'test_*.py' -v
build:
	go build ./...
	$(PYTHON) -c 'import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path("services").rglob("*.py")]'
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
verify: lint config compose-check test build governance-check stt-lock-check
