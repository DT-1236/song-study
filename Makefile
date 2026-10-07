.PHONY: test format format-check lint test-backend test-frontend frontend-install

# Read-only: checks formatting and lint, then runs both test suites.
# `make format` rewrites files to fix what format-check reports.
test: format-check lint test-backend test-frontend

format:
	$(MAKE) -C backend format
	cd frontend && npm run format

format-check:
	$(MAKE) -C backend format-check
	cd frontend && npm run format:check

lint:
	$(MAKE) -C backend lint
	cd frontend && npm run lint

test-backend:
	$(MAKE) -C backend test

test-frontend: frontend-install
	cd frontend && npm test

# Reinstalls only when package-lock.json is newer than the last install.
frontend-install: frontend/node_modules/.package-lock.json

frontend/node_modules/.package-lock.json: frontend/package-lock.json
	cd frontend && npm ci
