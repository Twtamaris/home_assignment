.PHONY: help setup seed test eval run-backend run-frontend dev advance-order docker-up docker-down

PYTHON ?= python
VENV_PYTHON = backend/.venv/Scripts/python.exe
VENV_PYTHON_UNIX = backend/.venv/bin/python

help:
	@echo "Multi-Tenant Agent Platform - Available Make Commands:"
	@echo "  make setup         Install backend and frontend dependencies"
	@echo "  make seed          Rebuild database and knowledge bases from seed files"
	@echo "  make test          Run pytest tenant isolation assertions"
	@echo "  make eval          Run the 38-scenario eval suite and verify DB state"
	@echo "  make run-backend   Start FastAPI uvicorn server (port 8000)"
	@echo "  make run-frontend  Start Vite development server (port 3000)"
	@echo "  make advance-order Advance order status: make advance-order ID=ORD-1003 STATUS=confirmed"
	@echo "  make docker-up     Start complete platform via Docker Compose"
	@echo "  make docker-down   Stop Docker Compose containers"

setup:
	uv venv backend/.venv
	uv pip install -r backend/requirements.txt --python $(VENV_PYTHON)
	cd frontend && npm install

seed:
	@if exist $(VENV_PYTHON) ($(VENV_PYTHON) backend/scripts/seed.py) else ($(PYTHON) backend/scripts/seed.py)

test:
	@if exist $(VENV_PYTHON) ($(VENV_PYTHON) -m pytest backend/tests/test_tenant_isolation.py -v) else ($(PYTHON) -m pytest backend/tests/test_tenant_isolation.py -v)

eval:
	@if exist $(VENV_PYTHON) ($(VENV_PYTHON) backend/scripts/run_eval.py) else ($(PYTHON) backend/scripts/run_eval.py)

advance-order:
	@if exist $(VENV_PYTHON) ($(VENV_PYTHON) backend/scripts/advance_order.py $(ID) $(STATUS)) else ($(PYTHON) backend/scripts/advance_order.py $(ID) $(STATUS))

run-backend:
	@if exist $(VENV_PYTHON) ($(VENV_PYTHON) -m uvicorn app.main:app --reload --port 8000 --app-dir backend) else ($(PYTHON) -m uvicorn app.main:app --reload --port 8000 --app-dir backend)

run-frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make run-backend' in terminal 1, and 'make run-frontend' in terminal 2."

docker-up:
	docker compose up --build

docker-down:
	docker compose down

