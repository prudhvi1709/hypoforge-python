.PHONY: test test-unit test-integration test-coverage test-fast install-test clean-test uv-test uv-run help

# Install test dependencies
install-test:
	pip install -e ".[test]"

# Run all tests
test:
	pytest

# Run only unit tests
test-unit:
	pytest -m "unit or not integration" --disable-warnings

# Run only integration tests  
test-integration:
	pytest -m "integration" --disable-warnings

# Run tests with coverage report
test-coverage:
	pytest --cov=app --cov-report=term-missing --cov-report=html:htmlcov

# Run fast tests (exclude slow tests)
test-fast:
	pytest -m "not slow" --disable-warnings

# Run specific test file
test-file:
	@echo "Usage: make test-file FILE=tests/test_endpoints.py"
	@if [ -z "$(FILE)" ]; then echo "Please specify FILE parameter"; exit 1; fi
	pytest $(FILE) -v

# Run tests with specific pattern
test-pattern:
	@echo "Usage: make test-pattern PATTERN=test_load_data"
	@if [ -z "$(PATTERN)" ]; then echo "Please specify PATTERN parameter"; exit 1; fi
	pytest -k "$(PATTERN)" -v

# Clean test artifacts
clean-test:
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Run tests with uv (uses inline requirements)
uv-test:
	uv run pytest

# Run the main app with uv (uses inline requirements)
uv-run:
	uv run app.py

# Run a quick test to verify uv works
uv-verify:
	@echo "Testing uv inline requirements..."
	@uv run python -c "import sys; print(f'✅ uv works with Python {sys.version.split()[0]}')"

# Run tests in verbose mode
test-verbose:
	pytest -v -s

# Run tests with output capture disabled
test-debug:
	pytest -v -s --tb=long

# Check test coverage and open HTML report
coverage-html: test-coverage
	@echo "Opening coverage report in browser..."
	@python -c "import webbrowser; webbrowser.open('htmlcov/index.html')"

# Help
help:
	@echo "Available commands:"
	@echo ""
	@echo "Traditional testing (requires pip install):"
	@echo "  make install-test    - Install test dependencies"
	@echo "  make test           - Run all tests"
	@echo "  make test-unit      - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make test-coverage  - Run tests with coverage report"
	@echo "  make test-fast      - Run tests excluding slow ones"
	@echo "  make test-file FILE=<path> - Run specific test file"
	@echo "  make test-pattern PATTERN=<pattern> - Run tests matching pattern"
	@echo "  make test-verbose   - Run tests in verbose mode"
	@echo "  make test-debug     - Run tests with debug output"
	@echo "  make coverage-html  - Generate and open HTML coverage report"
	@echo ""
	@echo "uv-based commands (uses inline requirements):"
	@echo "  make uv-test        - Run tests with uv (auto-installs dependencies)"
	@echo "  make uv-run         - Run the main app with uv"
	@echo "  make uv-verify      - Test that uv works with inline requirements"
	@echo ""
	@echo "Utility commands:"
	@echo "  make clean-test     - Clean test artifacts"
	@echo "  make help          - Show this help message" 