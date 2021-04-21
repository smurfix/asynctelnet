"""Test XDISPLOC, rfc-1096_."""
# std imports
import anyio

# local imports
import asynctelnet

from asynctelnet.telopt import CHARSET

# 3rd party
import pytest
from tests.accessories import Server

import logging
logger = logging.getLogger(__name__)

@pytest.mark.anyio
async def test_telnet_server_on_charset(server):
    """Server selects a charset"""
    _waiter = anyio.Event()
    _waiter2 = anyio.Event()
    given_charset = 'KOI8-U'

    class ServerTestCharset(Server):
        async def setup(self, tg):
            await super().setup(tg)
            tg.start_soon(self.local_option,CHARSET,True)

        def on_charset(self, charset):
            super().on_charset(charset)
            assert self.extra_attributes['charset']() == given_charset
            _waiter.set()

    class ClientTestCharset(asynctelnet.TelnetClient):
        def on_charset(self, charset):
            super().on_charset(charset)
            assert self.extra_attributes['charset']() == given_charset
            _waiter2.set()

    # term=None stops autonegotiation
    async with server(factory=ServerTestCharset, encoding=given_charset) as srv, \
            srv.client(encoding="", factory=ClientTestCharset):

        with anyio.fail_after(2):
            await _waiter.wait()
            await _waiter2.wait()


@pytest.mark.anyio
async def test_telnet_client_on_charset(server):
    """Client selects a charset"""
    _waiter = anyio.Event()
    _waiter2 = anyio.Event()
    given_charset = 'KOI8-U'

    class ServerTestCharset(Server):
        async def setup(self, tg):
            await super().setup(tg)
            tg.start_soon(self.remote_option,CHARSET,True)

        def on_charset(self, charset):
            super().on_charset(charset)
            assert self.extra_attributes['charset']() == given_charset
            _waiter.set()

    class ClientTestCharset(asynctelnet.TelnetClient):
        def on_charset(self, charset):
            super().on_charset(charset)
            assert self.extra_attributes['charset']() == given_charset
            _waiter2.set()

    # term=None stops autonegotiation
    async with server(factory=ServerTestCharset, encoding="") as srv, \
            srv.client(encoding=given_charset, factory=ClientTestCharset):

        with anyio.fail_after(2):
            await _waiter.wait()
            await _waiter2.wait()


@pytest.mark.anyio
async def test_telnet_client_select_charset(server):
    """Test Client's callback method select_charset() selection for illegals."""
    # given
    _waiter = anyio.Event()

    class ServerTestCharset(Server):
        async def setup(self, tg):
            await super().setup(tg)
            tg.start_soon(self.local_option,CHARSET,True)

        def get_supported_charsets(self):
            return ['illegal', 'cp437']

    class ClientTestCharset(asynctelnet.TelnetClient):
        def select_charset(self, offered):
            val = super().select_charset(offered)
            assert val == 'cp437'
            assert self.extra_attributes['charset']() == 'cp437'
            _waiter.set()
            return val

    async with server(factory=ServerTestCharset,encoding="") as srv, \
            srv.client(factory=ClientTestCharset, encoding=''):

        with anyio.fail_after(2):
            await _waiter.wait()


@pytest.mark.anyio
async def test_telnet_client_no_charset(server):
    """Test Client's callback method select_charset() does not select."""
    # given
    _waiter = anyio.Event()

    class ServerTestCharset(asynctelnet.TelnetServer):
        async def setup(self, tg):
            await super().setup(tg)
            tg.start_soon(self.local_option,CHARSET,True)

        def get_supported_charsets(self):
            return ['illegal', 'this-is-no-good-either']

    class ClientTestCharset(asynctelnet.TelnetClient):
        def select_charset(self, offered):
            val = super().select_charset(offered)
            assert val is None
            assert self.extra_attributes['charset']() == 'latin1'
            _waiter.set()
            return val

    async with server(factory=ServerTestCharset,encoding="") as srv, \
        srv.client(factory=ClientTestCharset, encoding='latin1'):

        # charset remains latin1
        with anyio.fail_after(2):
            await _waiter.wait()
