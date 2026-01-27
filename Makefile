.PHONY: default setup setup-dev build test lint lint-fix typecheck clean

PYTHON ?= python3
VENV = venv
BIN = $(VENV)/bin

default: module.tar.gz

# Setup for production
setup:
	./setup.sh

# Setup for development (includes dev dependencies)
setup-dev: setup
	$(BIN)/pip install -r requirements-dev.txt

# Run tests
test: setup-dev
	$(BIN)/pytest tests/ -v

# Lint code
lint: setup-dev
	$(BIN)/ruff check src/

# Fix lint issues
lint-fix: setup-dev
	$(BIN)/ruff check --fix src/
	$(BIN)/ruff format src/

# Type checking
typecheck: setup-dev
	$(BIN)/mypy src/ --ignore-missing-imports

# Build the module tarball
build: setup
	./build.sh

# Copy built module to project root
module.tar.gz: build
	cp dist/archive.tar.gz module.tar.gz

# Clean build artifacts
clean:
	rm -rf $(VENV) dist build __pycache__ .mypy_cache .pytest_cache .ruff_cache
	rm -rf src/__pycache__ src/*.pyc
	rm -f module.tar.gz

# Run locally for testing
run: setup
	./exec.sh
