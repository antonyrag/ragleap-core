import pytest
from http_server import LocalServer


@pytest.fixture
def server():
    s = LocalServer().start()
    yield s
    s.shutdown()
