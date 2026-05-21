import pytest

from app.cache import cache


@pytest.fixture(autouse=True)
def _reset_cache():
    cache.clear()
    yield
    cache.clear()
