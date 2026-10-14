import importlib.util

import pytest

from power_engine.contracts import MicrogridConfig
from simulator.scenarios import initial_state


def pytest_collection_modifyitems(items):
    if importlib.util.find_spec("pandapower") is None:
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Real pandapower is not installed; no fake AC fallback"))


@pytest.fixture
def config():
    return MicrogridConfig()


@pytest.fixture
def state(config):
    return initial_state(config)


def pytest_addoption(parser):
    parser.addoption("--require-ac", action="store_true", default=False,
                     help="Require real pandapower and fail if any test is skipped (CI mode)")


def pytest_sessionstart(session):
    if session.config.getoption("--require-ac"):
        try:
            __import__("pandapower")
        except ImportError as exc:
            raise pytest.UsageError("--require-ac needs an importable real pandapower") from exc


def pytest_sessionfinish(session, exitstatus):
    if session.config.getoption("--require-ac") and exitstatus == 0:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None and reporter.stats.get("skipped"):
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
