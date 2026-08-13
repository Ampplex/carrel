PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: help setup dev build test check probe seed clean

help:
	@echo "setup   install backend venv and frontend deps"
	@echo "dev     run the API (frontend: cd frontend && npm run dev)"
	@echo "build   build the frontend; the API then serves it on :8000"
	@echo "test    run backend tests (no network, no quota)"
	@echo "check   verify the SDK version and what the service has switched on"
	@echo "probe   run the Phase 0 probes (costs queries)"
	@echo "seed    seed the demo namespace (do this a day before a demo)"

setup:
	python3 -m venv backend/.venv
	$(PIP) install -q -e "backend[dev]"
	cd frontend && npm install
	@test -f backend/.env || (cp .env.example backend/.env && \
		echo "created backend/.env — set REEVE_API_KEY in it")

dev:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

build:
	cd frontend && npm run build

test:
	cd backend && .venv/bin/python -m pytest tests/ -q

# Free. Run it whenever an answer looks wrong: a capability may have been
# switched off on the service side, which degrades silently rather than erroring.
check:
	cd backend/scripts && ../.venv/bin/python probe_config.py

# Each of these costs queries. Read the docstrings before running them.
probe:
	cd backend/scripts && ../.venv/bin/python probe_readafterwrite.py
	cd backend/scripts && ../.venv/bin/python probe_supersession.py

seed:
	cd backend/scripts && ../.venv/bin/python seed_demo.py

clean:
	rm -rf backend/var frontend/dist
	find backend -name __pycache__ -type d -exec rm -rf {} +
