"""Test accessories for asynctelnet project."""
import pytest
import contextlib

@pytest.fixture(scope="module", params=['127.0.0.1'])
def bind_host(request):
    """ Localhost bind address. """
    return request.param

def _unused_tcp_port():
    """Find an unused localhost TCP port from 1024-65535 and return it."""
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

@pytest.fixture
def unused_tcp_port():
    return _unused_tcp_port()

@pytest.fixture
def unused_tcp_port_factory():
    """A factory function, producing different unused TCP ports."""
    produced = set()

    def factory():
        """Return an unused port."""
        port = _unused_tcp_port()

        while port in produced:
            port = _unused_tcp_port()

        produced.add(port)

        return port
    return factory


__all__ = ('bind_host', 'unused_tcp_port', 'unused_tcp_port_factory',)
