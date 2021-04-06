"""Test Server encoding mixin."""
# std imports
import anyio

# local imports
from asynctelnet.client import TelnetClient
from tests.accessories import NoTtype, Server

# 3rd party
import pytest


class ClientTestTtype(NoTtype, TelnetClient):
    pass

class ServerTestTtype(NoTtype, Server):
    pass


@pytest.mark.anyio
async def test_telnet_server_encoding_default(server):
    """Default encoding US-ASCII unless it can be negotiated/confirmed!"""

    async with server(factory=ServerTestTtype) as srv, \
            srv.client(factory=ClientTestTtype) as client:
        await srv.evt.wait()

        # verify,
        assert srv.last.encoding(incoming=True) == 'US-ASCII'
        assert srv.last.encoding(outgoing=True) == 'US-ASCII'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'US-ASCII'

        assert client.encoding(incoming=True) == 'US-ASCII'
        assert client.encoding(outgoing=True) == 'US-ASCII'
        assert client.encoding(incoming=True, outgoing=True) == 'US-ASCII'

        with pytest.raises(TypeError):
            # at least one direction should be specified
            srv.last.encoding()
        with pytest.raises(TypeError):
            # at least one direction should be specified
            client.encoding()


@pytest.mark.anyio
async def test_telnet_client_encoding_default(server):
    """Default encoding US-ASCII unless it can be negotiated/confirmed!"""

    async with server(factory=ServerTestTtype) as srv, \
            srv.client(factory=ClientTestTtype) as client:
        await srv.evt.wait()

        # verify,
        assert srv.last.encoding(incoming=True) == 'US-ASCII'
        assert srv.last.encoding(outgoing=True) == 'US-ASCII'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'US-ASCII'

        assert client.encoding(incoming=True) == 'US-ASCII'
        assert client.encoding(outgoing=True) == 'US-ASCII'
        assert client.encoding(incoming=True, outgoing=True) == 'US-ASCII'

        with pytest.raises(TypeError):
            # at least one direction should be specified
            srv.last.encoding()
        with pytest.raises(TypeError):
            # at least one direction should be specified
            client.encoding()


@pytest.mark.anyio
async def test_telnet_server_encoding_client_will(server):
    """Server Default encoding (utf8) incoming when client WILL."""
    from asynctelnet.telopt import TTYPE, BINARY

    async with server(factory=ServerTestTtype, encoding="utf8") as srv, \
            srv.client(factory=ClientTestTtype, encoding="utf8") as client:
        await srv.evt.wait()

        await client.local_option(BINARY, True)
        await client.local_option(TTYPE, True)

        # verify,
        assert srv.last.encoding(incoming=True) == 'utf8'
        assert srv.last.encoding(outgoing=True) == 'US-ASCII'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'US-ASCII'

        assert client.encoding(outgoing=True) == 'utf8'
        assert client.encoding(incoming=True) == 'US-ASCII'
        assert client.encoding(incoming=True, outgoing=True) == 'US-ASCII'


@pytest.mark.anyio
async def test_telnet_server_encoding_server_do(server):
    """Server's default encoding."""
    from asynctelnet.telopt import TTYPE, BINARY

    async with server(factory=ServerTestTtype, encoding="utf8") as srv, \
            srv.client(factory=ClientTestTtype, encoding="utf8") as client:
        await srv.evt.wait()

        await client.remote_option(BINARY, True)
        await client.local_option(TTYPE, False)

        assert client.encoding(outgoing=True) == 'US-ASCII'
        assert client.encoding(incoming=True) == 'utf8'
        assert client.encoding(incoming=True, outgoing=True) == 'US-ASCII'

        assert srv.last.encoding(incoming=True) == 'US-ASCII'
        assert srv.last.encoding(outgoing=True) == 'utf8'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'US-ASCII'


@pytest.mark.anyio
async def test_telnet_server_encoding_bidirectional(server):
    """Server's default encoding with bi-directional BINARY negotiation."""
    from asynctelnet.telopt import TTYPE, BINARY

    async with server(factory=ServerTestTtype, encoding="utf8") as srv, \
            srv.client(factory=ClientTestTtype, encoding="utf8") as client:
        await srv.evt.wait()

        await client.remote_option(BINARY, True)
        await client.local_option(BINARY, True)
        await client.local_option(TTYPE, False)

        assert client.encoding(incoming=True) == 'utf8'
        assert client.encoding(outgoing=True) == 'utf8'
        assert client.encoding(incoming=True, outgoing=True) == 'utf8'

        assert srv.last.encoding(incoming=True) == 'utf8'
        assert srv.last.encoding(outgoing=True) == 'utf8'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'utf8'


@pytest.mark.anyio
async def test_telnet_client_and_server_encoding_bidirectional(server):
    """Given a default encoding for client and server, client always wins!"""
    # given
    _waiter = anyio.Event()

    class Srv(Server):
        def on_charset(self,cs):
            super().on_charset(cs)
            _waiter.set()

    async with server(factory=Srv, encoding="latin1", term="duh") as srv, \
            srv.client(encoding="cp437", term="duh") as client:
        await srv.evt.wait()
        await _waiter.wait()

        assert srv.last.encoding(incoming=True) == 'cp437'
        assert srv.last.encoding(outgoing=True) == 'cp437'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'cp437'

        assert client.encoding(incoming=True) == 'cp437'
        assert client.encoding(outgoing=True) == 'cp437'
        assert client.encoding(incoming=True, outgoing=True) == 'cp437'


@pytest.mark.anyio
async def test_telnet_server_encoding_by_LANG(
        bind_host, unused_tcp_port):
    """Server's encoding negotiated by LANG value."""
    from asynctelnet.telopt import (
        IAC, WONT, DO, WILL, TTYPE, BINARY,
        WILL, SB, SE, IS, NEW_ENVIRON)
    from asynctelnet.telopt import TTYPE, BINARY

    async with server(factory=ServerTestTtype, encoding="utf8") as srv, \
            srv.client(factory=ClientTestTtype, encoding="utf8") as client:
        await srv.evt.wait()

        await client.remote_option(BINARY, True)
        await client.local_option(BINARY, True)
        await client.local_option(NEW_ENVIRON, True)
        await client.local_option(TTYPE, False)

    writer.write(IAC + WILL + BINARY)
    writer.write(IAC + WILL + NEW_ENVIRON)
    writer.write(IAC + SB + NEW_ENVIRON + IS +
                 asynctelnet.stream._encode_env_buf({
                     'LANG': 'uk_UA.KOI8-U',
                 }) + IAC + SE)
    writer.write(IAC + WONT + TTYPE)

    # verify,
    srv_instance = await asyncio.wait_for(_waiter, 0.5)
    assert srv_instance.encoding(incoming=True) == 'KOI8-U'
    assert srv_instance.encoding(outgoing=True) == 'KOI8-U'
    assert srv_instance.encoding(incoming=True, outgoing=True) == 'KOI8-U'
    assert srv_instance.extra.LANG == 'uk_UA.KOI8-U'


@pytest.mark.anyio
async def test_telnet_server_binary_mode(
        bind_host, unused_tcp_port):
    """Server's encoding=False creates a binary reader/writer interface."""
    from asynctelnet.telopt import IAC, WONT, DO, TTYPE, BINARY
    # given
    _waiter = anyio.Event()

    async def binary_shell(reader, writer):
        # our reader and writer should provide binary output
        writer.write(b'server_output')

        val = await reader.readexactly(1)
        assert val == b'c'
        val = await reader.readexactly(len(b'lient '))
        assert val == b'lient '
        writer.close()
        val = await reader.read()
        assert val == b'output'

    await asynctelnet.create_server(
        host=bind_host, port=unused_tcp_port,
        shell=binary_shell, _waiter_connected=_waiter, encoding=False)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # exercise, server will binary
    val = await reader.readexactly(len(IAC + DO + TTYPE))
    assert val == IAC + DO + TTYPE

    writer.write(IAC + WONT + TTYPE)
    writer.write(b'client output')

    val = await reader.readexactly(len(b'server_output'))
    assert val == b'server_output'

    eof = await reader.read()
    assert eof == b''


@pytest.mark.anyio
async def test_telnet_client_and_server_escape_iac_encoding(
        bind_host, unused_tcp_port):
    """Ensure that IAC (byte 255) may be sent across the wire by encoding."""
    # given
    _waiter = anyio.Event()
    given_string = ''.join(chr(val) for val in list(range(256))) * 2

    await asynctelnet.create_server(
        host=bind_host, port=unused_tcp_port, _waiter_connected=_waiter,
        encoding='iso8859-1', connect_maxwait=0.05)

    client_reader, client_writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port,
        encoding='iso8859-1', connect_minwait=0.05)

    server = await asyncio.wait_for(_waiter, 0.5)

    server.writer.write(given_string)
    result = await client_reader.readexactly(len(given_string))
    assert result == given_string
    server.writer.close()
    eof = await asyncio.wait_for(client_reader.read(), 0.5)
    assert eof == ''


@pytest.mark.anyio
async def test_telnet_client_and_server_escape_iac_binary(
        bind_host, unused_tcp_port):
    """Ensure that IAC (byte 255) may be sent across the wire in binary."""
    # given
    _waiter = anyio.Event()
    given_string = bytes(range(256)) * 2

    await asynctelnet.create_server(
        host=bind_host, port=unused_tcp_port, _waiter_connected=_waiter,
        encoding=False, connect_maxwait=0.05)

    client_reader, client_writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port,
        encoding=False, connect_minwait=0.05)

    server = await asyncio.wait_for(_waiter, 0.5)

    server.writer.write(given_string)
    result = await client_reader.readexactly(len(given_string))
    assert result == given_string
    server.writer.close()
    eof = await asyncio.wait_for(client_reader.read(), 0.5)
    assert eof == b''
