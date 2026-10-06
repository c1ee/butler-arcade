import pytest

from tests import privacy, states


@pytest.fixture(autouse=True)
def no_leaks():
    """The privacy checks are always on (D12): after every test, each World it built must show no leak."""
    states.WORLDS.clear()
    yield
    for world in states.WORLDS:
        assert privacy.check(world.store, world.gateway, world.secrets) == []
