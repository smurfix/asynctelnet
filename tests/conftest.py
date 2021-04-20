import pytest
import socket
import anyio

from tests.accessories import shell as shell_, Server, Client
from contextlib import asynccontextmanager, closing
from asynctelnet.accessories import AttrDict
from asynctelnet.server import server_loop
from asynctelnet.client import open_connection
from functools import partial

@pytest.fixture
def anyio_backend():
    return  "trio"

@pytest.fixture(scope="module", params=['127.0.0.1'])
def bind_host(request):
    """ Localhost bind address. """
    return request.param

def _unused_tcp_port():
    """Find an unused localhost TCP port from 1024-65535 and return it."""
    with closing(socket.socket()) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]

@pytest.fixture(params=['127.0.0.1'])
def server(bind_host, unused_tcp_port):
    @asynccontextmanager
    async def mgr(factory=Server, shell=shell_, with_client=True, with_reader=True, **kw):
        res = AttrDict()
        res.evt = anyio.Event()
        res.host = bind_host
        res.port = unused_tcp_port

        async def myshell(client):
            res.last = client
            res.evt.set()
            await shell(client)

        @asynccontextmanager
        async def gen_client(*, factory=Client, with_reader=True, **kw):
            if "host" not in kw:
                kw["host"] = bind_host
            if "port" not in kw:
                kw["port"] = unused_tcp_port
            if "encoding" not in kw:
                kw["encoding"] = ""
            if "term" not in kw:
                kw["term"] = None
            async with open_connection(client_factory=factory, **kw) as client:
                if with_reader:
                    res.tg.start_soon(shell_, client)
                yield client

        async with anyio.create_task_group() as tg:
            evt=anyio.Event()
            tg.start_soon(partial(server_loop, protocol_factory=factory, shell=myshell, evt=evt,host=bind_host,port=unused_tcp_port, **kw))
            res.tcp_port = unused_tcp_port
            res.client = gen_client
            res.tg = tg
            await evt.wait()
            yield res
            tg.cancel_scope.cancel()
    return mgr


@pytest.fixture
def unused_tcp_port():
    return _unused_tcp_port()

@pytest.fixture(params=[
    pytest.param(('asyncio', {}), id='asyncio'),
    pytest.param(('trio', {}), id='trio'),
])
def anyio_backend(request):
    return request.param
