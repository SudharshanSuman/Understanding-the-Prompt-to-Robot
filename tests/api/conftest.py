import pytest

from tests.api.helpers import need_live_stack, start_server


@pytest.fixture(scope="session", autouse=True)
def _live_stack():
    need_live_stack()


@pytest.fixture
def make_server(repo_root, tmp_path):
    """Factory: make_server(rate=None, MD_TEST_EXECUTOR='toggle', ...) -> Server; all are stopped at teardown."""
    started = []

    def factory(**kw):
        srv = start_server(repo_root, tmp_path, **kw)
        started.append(srv)
        return srv

    yield factory
    for srv in started:
        srv.stop()


@pytest.fixture(scope="module")
def shared(repo_root, tmp_path_factory):
    """One server per module with generous limits: for tests that do not probe limits."""
    srv = start_server(repo_root, tmp_path_factory.mktemp("shared"), MD_TEST_AUTH_FAILS="100000")
    yield srv
    srv.stop()
