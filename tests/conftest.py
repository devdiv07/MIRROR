import pytest

from src import cli
from tests.support import TEST_USER_AGENT


@pytest.fixture(autouse=True)
def sec_user_agent(monkeypatch):
    """SEC_USER_AGENT is required for any SEC request; tests use a placeholder, never a real contact."""
    monkeypatch.setenv('SEC_USER_AGENT', TEST_USER_AGENT)


@pytest.fixture(autouse=True)
def cli_data_defaults(monkeypatch, tmp_path):
    """The CLI's default input files live in the repo's data/ folder, which may hold the owner's own
    files. Point them into this test's empty temp dir, so a test reads only what it passes."""
    monkeypatch.setattr(cli, 'DEFAULT_MANUAL_EVENTS', str(tmp_path / 'defaults' / 'manual_events.csv'))
    monkeypatch.setattr(cli, 'DEFAULT_CORPORATE_ACTIONS', str(tmp_path / 'defaults' / 'corporate_actions.csv'))
    monkeypatch.setattr(cli, 'DEFAULT_PRICES_DIR', str(tmp_path / 'defaults' / 'prices'))
