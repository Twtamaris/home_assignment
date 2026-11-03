.PHONY: help setup seed test eval live-eval add-org run-backend run-frontend dev advance-order docker-up docker-down

# Works on macOS, Linux and Windows (GNU make under Git Bash).
ifeq ($(OS),Windows_NT)
  VENV_PY := backend/.venv/Scripts/python.exe
  SYS_PY  := python
else
  VENV_PY := backend/.venv/bin/python
  SYS_PY  := python3
endif
# Use the project virtualenv once `make setup` has created it, otherwise whatever python is on PATH.
PY := $(if $(wildcard $(VENV_PY)),$(VENV_PY),$(SYS_PY))

help:
	@echo "Multi-Tenant Agent Platform"
	@echo "  make setup          Create the virtualenv, install backend and frontend dependencies, create .env"
	@echo "  make seed           Rebuild the database and BOTH knowledge bases from the seed files"
	@echo "  make eval           Run every eval scenario offline and report pass/fail per scenario"
	@echo "  make live-eval      Run a smaller set of scenarios against the real model (needs a key in .env)"
	@echo "  make test           Run the pytest suite (same tests as eval, plain pytest output)"
	@echo "  make add-org        Add the third organisation (Everest Outdoor) from configuration alone"
	@echo "  make run-backend    API on http://localhost:8000  (docs at /docs)"
	@echo "  make run-frontend   Web app on http://localhost:3000"
	@echo "  make advance-order  Admin script: make advance-order ID=ORD-1003 STATUS=confirmed"
	@echo "  make docker-up      Whole stack with Docker Compose;  make docker-down stops it"

setup:
	$(SYS_PY) -m venv backend/.venv
	$(VENV_PY) -m pip install --upgrade pip
	$(VENV_PY) -m pip install -r backend/requirements.txt
	cd frontend && npm install
	$(SYS_PY) -c "import os, shutil; os.path.exists('.env') or shutil.copy('.env.example', '.env')"

seed:
	$(PY) backend/scripts/seed.py

eval:
	$(PY) backend/scripts/run_eval.py

live-eval:
	$(PY) backend/scripts/live_eval.py

test:
	$(PY) -m pytest backend/tests -q

add-org:
	$(PY) backend/scripts/add_third_org.py

advance-order:
	$(PY) backend/scripts/advance_order.py $(ID) $(STATUS)

run-backend:
	$(PY) -m uvicorn app.main:app --reload --port 8000 --app-dir backend

run-frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make run-backend' in one terminal and 'make run-frontend' in another."

docker-up:
	docker compose up --build

docker-down:
	docker compose down
