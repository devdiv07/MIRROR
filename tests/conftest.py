import pytest

from tests.support import TEST_USER_AGENT


@pytest.fixture(autouse=True)
def sec_user_agent(monkeypatch):
    """SEC_USER_AGENT is required for any SEC request; tests use a placeholder, never a real contact."""
    monkeypatch.setenv('SEC_USER_AGENT', TEST_USER_AGENT)
