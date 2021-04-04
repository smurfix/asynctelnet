"""Test accessories for asynctelnet project."""
import pytest
from functools import partial
import anyio

from asynctelnet.server import server_loop,TelnetServer 
from asynctelnet.client import BaseClient

class Server(TelnetServer):
    pass

async def testshell(client):
    client.log.debug("R start")
    try:
        while True:
            d = await client.receive()
            client.log.debug("R:%s",d)
    except anyio.EndOfStream:
        pass

class BaseTestClient(BaseClient):
    def __init__(self, conn, term=None, cols=None, rows=None, tspeed=None, xdisploc=None, **kw):
        super().__init__(conn, **kw)

@pytest.fixture(params=['127.0.0.1'])
def server(bind_host, unused_tcp_port):
    @contextlib.asynccontextmanager
    async def mgr(**kw):
        async with anyio.create_task_group() as tg:
            evt = anyio.Event()
            tg.spawn(partial(server_loop,evt=evt,host=bind_host,port=unused_tcp_port, **kw))
            await evt.wait()
            yield unused_tcp_port
            tg.cancel_scope.cancel()
    return mgr


__all__ = ('BaseTestClient', 'Server', 'testshell')
