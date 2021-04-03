"""Test accessories for asynctelnet project."""
import pytest
import contextlib
from functools import partial
import anyio
import socket

from asynctelnet.server import server_loop,TelnetServer 
from asynctelnet.accessories import AttrDict

@pytest.fixture(scope="module", params=['127.0.0.1'])
def bind_host(request):
    """ Localhost bind address. """
    return request.param

def _unused_tcp_port():
    """Find an unused localhost TCP port from 1024-65535 and return it."""
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

@pytest.fixture(params=['127.0.0.1'])
def server(bind_host, unused_tcp_port):
    @contextlib.asynccontextmanager
    async def mgr(factory=TestServer, shell=testshell, **kw):
        res = AttrDict()
        res.evt = anyio.Event()

        async def myshell(client):
            res.last = client
            res.evt.set()
            await shell(client)

        async with anyio.create_task_group() as tg:
            evt=anyio.Event()
            await tg.spawn(partial(server_loop, protocol_factory=factory, shell=myshell, evt=evt,host=bind_host,port=unused_tcp_port, **kw))
            await evt.wait()
            res.tcp_port = unused_tcp_port
            yield res
            await tg.cancel_scope.cancel()
    return mgr

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


@contextlib.asynccontextmanager
async def reader(client):
    async with anyio.create_task_group() as tg:
        tg.spawn(testshell, client)
        yield client
        tg.cancel_scope.cancel()

class TestServer(TelnetServer):
    pass

async def testshell(client):
    client.log.debug("R start")
    try:
        while True:
            d = await client.receive()
            client.log.debug("R:%s",d)
    except anyio.EndOfStream:
        pass


__all__ = ('bind_host', 'unused_tcp_port', 'unused_tcp_port_factory', 'server', 'reader', 'TestServer', 'testshell')
