.PHONY: install test run clean docker-build docker-up docker-down health-check

PYTHON := python3
PIP := $(PYTHON) -m pip
VENV := .venv

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install -r requirements.txt

test:
	pytest tests/ -v

run:
	$(PYTHON) -m uvicorn app.main:app --reload

clean:
	rm -rf __pycache__ *.pyc .pytest_cache
	rm -f *.db *.sqlite
	rm -rf $(VENV)

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

health-check:
	@echo "Checking service health..." && curl -sf http://localhost:8000/health || echo "Service not ready"
