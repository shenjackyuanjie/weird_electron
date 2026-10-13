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
