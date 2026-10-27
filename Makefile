PY := .venv/bin/python
PIP := .venv/bin/pip
BACKEND_PORT := 8010
FRONTEND_PORT := 5173

.PHONY: venv install-backend install-frontend install backend frontend \
        build-frontend test test-backend test-frontend sample-zip flowgate-zip \
        docker-image seed seed-flowgate

venv:
	python3 -m venv .venv

install-backend: venv
	$(PIP) install -r backend/requirements.txt

install-frontend:
	cd frontend && npm install

install: install-backend install-frontend

backend:
	$(PY) -m uvicorn app.main:app --host 127.0.0.1 --port $(BACKEND_PORT) --app-dir backend

frontend:
	cd frontend && npm run dev -- --port $(FRONTEND_PORT)

build-frontend:
	cd frontend && npm run build

test: test-backend test-frontend

test-backend:
	$(PY) -m pytest backend/tests -q

test-frontend:
	cd frontend && npm run build

sample-zip:
	@mkdir -p data/uploads
	cd examples/sample_repo && zip -qr ../../data/uploads/sample_repo.zip . -x '*.pyc' -x '*/__pycache__/*'
	@echo "data/uploads/sample_repo.zip ready"

flowgate-zip:
	@mkdir -p data/uploads
	cd examples/flowgate && zip -qr ../../data/uploads/flowgate_repo.zip . -x '*.pyc' -x '*/__pycache__/*'
	@echo "data/uploads/flowgate_repo.zip ready"

docker-image:
	docker build -t graphagent-runner:latest docker

seed: sample-zip
	@echo "Uploading sample repo..."
	@REPO=$$(curl -s -F "file=@data/uploads/sample_repo.zip" http://127.0.0.1:$(BACKEND_PORT)/api/repos/upload | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])") && \
	echo "repo_id=$$REPO  -> building graph..." && \
	curl -s -X POST http://127.0.0.1:$(BACKEND_PORT)/api/repos/$$REPO/graph && echo && \
	for i in 1 2 3 4 5 6 7 8 9 10; do \
	  sleep 1; \
	  STATUS=$$(curl -s http://127.0.0.1:$(BACKEND_PORT)/api/repos/$$REPO/graph); \
	  echo "$$STATUS" | grep -q '"ready"' && { echo "graph ready"; exit 0; }; \
	  echo "$$STATUS" | grep -q '"error"' && { echo "$$STATUS"; exit 1; }; \
	done; echo "still building (retry: curl -s http://127.0.0.1:$(BACKEND_PORT)/api/repos/$$REPO/graph)"

seed-flowgate: flowgate-zip
	@echo "Uploading flowgate repo..."
	@REPO=$$(curl -s -F "file=@data/uploads/flowgate_repo.zip" http://127.0.0.1:$(BACKEND_PORT)/api/repos/upload | python3 -c "import json,sys;print(json.load(sys.stdin)['id'])") && \
	echo "repo_id=$$REPO  -> building graph..." && \
	curl -s -X POST http://127.0.0.1:$(BACKEND_PORT)/api/repos/$$REPO/graph && echo && \
	for i in 1 2 3 4 5 6 7 8 9 10; do \
	  sleep 1; \
	  STATUS=$$(curl -s http://127.0.0.1:$(BACKEND_PORT)/api/repos/$$REPO/graph); \
	  echo "$$STATUS" | grep -q '"ready"' && { echo "graph ready"; exit 0; }; \
	  echo "$$STATUS" | grep -q '"error"' && { echo "$$STATUS"; exit 1; }; \
	done; echo "still building (retry: curl -s http://127.0.0.1:$(BACKEND_PORT)/api/repos/$$REPO/graph)"
