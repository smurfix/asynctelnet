"""Test accessories for asynctelnet project."""
import pytest
from functools import partial
import anyio

from asynctelnet.server import server_loop,TelnetServer 
from asynctelnet.client import BaseClient

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

class BaseTestClient(BaseClient):
    def __init__(self, conn, term=None, cols=None, rows=None, tspeed=None, xdisploc=None, **kw):
        super().__init__(conn, **kw)


__all__ = ('BaseTestClient', 'TestServer', 'testshell')
