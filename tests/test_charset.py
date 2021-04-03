"""Test XDISPLOC, rfc-1096_."""
# std imports
import anyio

# local imports
import asynctelnet

from asynctelnet.telopt import CHARSET
from tests.accessories import (
    unused_tcp_port,
    bind_host, server, reader, TestServer
)

# 3rd party
import pytest

import logging
logger = logging.getLogger(__name__)

@pytest.mark.anyio
async def test_telnet_server_on_charset(server, bind_host, unused_tcp_port):
    """Server selects a charset"""
    _waiter = anyio.Event()
    _waiter2 = anyio.Event()
    given_charset = 'KOI8-U'

    class ServerTestCharset(TestServer):
        async def setup(self):
            await super().setup()
            await self.local_option(CHARSET,True)

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
    async with server(factory=ServerTestCharset, encoding=given_charset), \
        asynctelnet.open_connection(encoding="",
            client_factory=ClientTestCharset,
                host=bind_host, port=unused_tcp_port, term=None) as client, \
                reader(client):

        async with anyio.fail_after(2):
            await _waiter.wait()
            await _waiter2.wait()


@pytest.mark.anyio
async def test_telnet_client_on_charset(server, bind_host, unused_tcp_port):
    """Client selects a charset"""
    _waiter = anyio.Event()
    _waiter2 = anyio.Event()
    given_charset = 'KOI8-U'

    class ServerTestCharset(TestServer):
        async def setup(self):
            await super().setup()
            await self.remote_option(CHARSET,True)

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
    async with server(factory=ServerTestCharset, encoding=""), \
        asynctelnet.open_connection(encoding=given_charset,
            client_factory=ClientTestCharset,
                host=bind_host, port=unused_tcp_port, term=None) as client, \
                reader(client):

        async with anyio.fail_after(2):
            await _waiter.wait()
            await _waiter2.wait()


@pytest.mark.anyio
async def test_telnet_client_select_charset(bind_host, unused_tcp_port, server):
    """Test Client's callback method select_charset() selection for illegals."""
    # given
    _waiter = anyio.Event()

    class ServerTestCharset(TestServer):
        async def setup(self):
            await super().setup()
            await self.local_option(CHARSET,True)

        def get_supported_charsets(self):
            return ['illegal', 'cp437']

    class ClientTestCharset(asynctelnet.TelnetClient):
        def select_charset(self, offered):
            val = super().select_charset(offered)
            assert val == 'cp437'
            assert self.extra_attributes['charset']() == 'cp437'
            _waiter.set()
            return val

    async with server(factory=ServerTestCharset,encoding="latin1"), \
        asynctelnet.open_connection(
            client_factory=ClientTestCharset,
            host=bind_host, port=unused_tcp_port, term=None,
            encoding='latin1' # connect_minwait=0.05)
            ) as client, reader(client):

        async with anyio.fail_after(2):
            await _waiter.wait()


@pytest.mark.anyio
async def test_telnet_client_no_charset(bind_host, unused_tcp_port, server):
    """Test Client's callback method select_charset() does not select."""
    # given
    _waiter = anyio.Event()

    class ServerTestCharset(asynctelnet.TelnetServer):
        async def setup(self):
            await super().setup()
            await self.local_option(CHARSET,True)

        def get_supported_charsets(self):
            return ['illegal', 'this-is-no-good-either']

    class ClientTestCharset(asynctelnet.TelnetClient):
        def select_charset(self, offered):
            val = super().select_charset(offered)
            assert val == ''
            assert self.extra_attributes['charset']() == 'latin1'
            _waiter.set()
            return val

    async with server(factory=ServerTestCharset,encoding=""), \
        asynctelnet.open_connection(
        client_factory=ClientTestCharset,
        host=bind_host, port=unused_tcp_port, term=None,
        encoding='latin1'# connect_minwait=0.05
        ) as client, reader(client):

        # charset remains latin1
        async with anyio.fail_after(2):
            await _waiter.wait()
