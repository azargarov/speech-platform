PYTHON ?= python3
COMPOSE = docker compose -f deployments/compose/compose.yaml
.PHONY: verify fmt lint config test build compose-check bootstrap governance-check stt-lock-check stt-cpu-integration
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
	STT_APPLICATION_CONFIG=$(CURDIR)/configs/stt-application-cpu.example.yaml STT_DEPLOYMENT_CONFIG=$(CURDIR)/configs/stt-deployment-cuda.example.yaml STT_MODEL_ROOT=/models docker compose -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda.yaml config --format json | $(PYTHON) scripts/check_compose.py
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
verify: lint config compose-check test build governance-check stt-lock-check
