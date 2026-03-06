"""pytest fixtures for evaluation harness."""

import sys
from pathlib import Path

import pytest

# Ensure agent-project root is on path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


@pytest.fixture
def mock_pool():
    """Fresh MockMCPPool for each test."""
    from evaluation.mocks import MockMCPPool
    fixtures = Path(__file__).parent / "mocks" / "fixtures"
    return MockMCPPool(fixtures)


@pytest.fixture
def mock_configs():
    return [{"id": "mock", "url": "http://mock"}]
