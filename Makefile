PYTHON ?= python3
COMPOSE = docker compose -f deployments/compose/compose.yaml
.PHONY: verify fmt lint config test build compose-check bootstrap governance-check
bootstrap:
	$(PYTHON) -m pip install -r requirements-dev.txt
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
test:
	go test -race ./...
	$(PYTHON) -m unittest discover -s scripts -p 'test_*.py' -v
build:
	go build ./...
	$(PYTHON) -c 'import ast,pathlib; [ast.parse(p.read_text()) for p in pathlib.Path("services").rglob("*.py")]'
governance-check:
	$(PYTHON) scripts/validate_governance.py
	$(PYTHON) -m unittest discover -s scripts -p 'test_governance.py' -v
verify: lint config compose-check test build governance-check
