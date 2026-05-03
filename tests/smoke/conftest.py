# Phase 10.2 W-FIX-C: smoke conftest.
#
# Single CLI option (--target) + a fixture that returns the target URL.
# Tests consume the fixture and use httpx (already in backend/.venv) to
# hit the target. No fixtures beyond this. No shared setup. No mocking.
#
# Usage:
#   pytest tests/smoke/ -v --target=https://www.liquiddemocracy.us
#   pytest tests/smoke/ -v --target=http://localhost:8000

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--target",
        action="store",
        default="https://www.liquiddemocracy.us",
        help="Base URL to run smoke checks against (no trailing slash).",
    )


@pytest.fixture(scope="session")
def target_url(request):
    raw = request.config.getoption("--target")
    return raw.rstrip("/")
