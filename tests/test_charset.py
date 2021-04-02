"""Test XDISPLOC, rfc-1096_."""
# std imports
import anyio

# local imports
import asynctelnet
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
    """Test Server's callback method on_charset()."""
    # given
    from asynctelnet.telopt import (
        IAC, WILL, WONT, SB, SE, TTYPE, CHARSET, ACCEPTED
    )
    _waiter = anyio.Event()
    given_charset = 'KOI8-U'

    class ServerTestCharset(TestServer):
        def on_charset(self, charset):
            super().on_charset(charset)
            assert self.extra_attributes['charset']() == given_charset
            _waiter.set()

    async with server(factory=ServerTestCharset, encoding=None), \
        asynctelnet.open_connection(encoding=None,
                host=bind_host, port=unused_tcp_port) as client, \
                reader(client):

        await client.send_iac(WILL, CHARSET)
        await client.send_iac(WONT, TTYPE)
        await client.send_subneg(CHARSET, ACCEPTED,
                    *given_charset.encode('ascii'))

        async with anyio.fail_after(2):
            await _waiter.wait()


@pytest.mark.anyio
async def test_telnet_client_send_charset(bind_host, unused_tcp_port):
    """Test Client's callback method send_charset() selection for illegals."""
    # given
    _waiter = anyio.Event()

    class ServerTestCharset(asynctelnet.TelnetServer):
        def on_request_charset(self):
            return ['illegal', 'cp437']

    class ClientTestCharset(asynctelnet.TelnetClient):
        def send_charset(self, offered):
            val = super().send_charset(offered)
            assert val == 'cp437'
            assert writer.get_extra_info('charset') == 'cp437'
            _waiter.set()

    async with server(protocol_factory=ServerTestCharset), \
        asynctelnet.open_connection(
            client_factory=ClientTestCharset,
            host=bind_host, port=unused_tcp_port,
            encoding='latin1'# connect_minwait=0.05)
            )  as client:

        async with anyio.fail_after(2):
            await _waiter.wait()


@pytest.mark.anyio
async def test_telnet_client_no_charset(bind_host, unused_tcp_port):
    """Test Client's callback method send_charset() does not select."""
    # given
    _waiter = anyio.Event()

    class ServerTestCharset(asynctelnet.TelnetServer):
        def on_request_charset(self):
            return ['illegal', 'this-is-no-good-either']

    class ClientTestCharset(asynctelnet.TelnetClient):
        def send_charset(self, offered):
            val = super().send_charset(offered)
            assert val == ''
            assert writer.get_extra_info('charset') == 'latin1'
            _waiter.set()

    async with server(protocol_factory=ServerTestCharset), \
        asynctelnet.open_connection(
        ilient_factory=ClientTestCharset,
        host=bind_host, port=unused_tcp_port,
        encoding='latin1'# connect_minwait=0.05
        ):

        # charset remains latin1
        async with anyio.fail_after(2):
            await _waiter.wait()
