"""Test Server encoding mixin."""
# std imports
import anyio

# local imports
from tests.accessories import NoTtype, Server, Client
from asynctelnet.options import stdBINARY, stdTTYPE, stdNEW_ENVIRON, BaseOption
from asynctelnet.options.basic import _encode_env_buf,StdOption,FullOption

# 3rd party
import pytest


class ClientTestTtype(NoTtype, Client):
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

    async with server(factory=ServerTestTtype, encoding="utf8",
            test_opt=(stdBINARY,stdTTYPE)) as srv, \
            srv.client(factory=ClientTestTtype, encoding="utf8") as client:
        await srv.evt.wait()

        assert await client.local_option(BINARY, True)
        assert await client.local_option(TTYPE, True)

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
async def test_telnet_server_encoding_by_LANG(server):
    """Server's encoding negotiated by LANG value."""
    from asynctelnet.telopt import (
        IAC, WONT, DO, WILL, TTYPE, BINARY,
        WILL, SB, SE, IS, NEW_ENVIRON)
    from asynctelnet.telopt import TTYPE, BINARY
    _waiter = anyio.Event()

    class Srv(Server):
        def on_charset(self,cs):
            super().on_charset(cs)
            _waiter.set()

    async with server(factory=Srv, encoding="utf8", test_opt=stdNEW_ENVIRON) as srv, \
            srv.client(factory=ClientTestTtype, encoding="utf8",test_opt=StdOption.NEW_ENVIRON) as client:
        await srv.evt.wait()

        await client.remote_option(BINARY, True)
        await client.local_option(BINARY, True)
        await client.local_option(NEW_ENVIRON, True)
        await client.local_option(TTYPE, False)

        print("XA")
        await client.send_subneg(NEW_ENVIRON, IS,
                 _encode_env_buf({
                     'LANG': 'uk_UA.KOI8-U',
                 }))

        print("XB")
        with anyio.fail_after(0.5):
            await _waiter.wait()
        print("XC")

        assert srv.last.encoding(incoming=True) == 'KOI8-U'
        assert srv.last.encoding(outgoing=True) == 'KOI8-U'
        assert srv.last.encoding(incoming=True, outgoing=True) == 'KOI8-U'
        assert srv.last.extra.LANG == 'uk_UA.KOI8-U'


@pytest.mark.anyio
async def test_telnet_server_binary_mode(server):
    """Server's encoding=False creates a binary reader/writer interface."""

    from asynctelnet.telopt import IAC, WONT, DO, TTYPE, BINARY
    # given
    _waiter = anyio.Event()

    async def binary_shell(stream):
        # our reader and writer should provide binary output
        await stream.send(b'server_output')

        val = await stream.read_exactly(1)
        assert val == b'c'
        val = await stream.read_exactly(len(b'lient '))
        assert val == b'lient '
        val = await stream.receive()
        assert val == b'output'

    async with server(factory=Server, encoding=False, shell=binary_shell) as srv, \
            srv.client(factory=Client, encoding=False,test_opt=BaseOption.TTYPE, with_reader=False) as client:

        # yeah, very funny.
        #val = await reader.readexactly(len(IAC + DO + TTYPE))
        #assert val == IAC + DO + TTYPE

        #client.send(IAC + WONT + TTYPE)
        await client.send(b'client output')

        val = await client.read_exactly(len(b'server_output'))
        assert val == b'server_output'

        with pytest.raises(anyio.EndOfStream):
            await client.receive()


@pytest.mark.anyio
async def test_telnet_client_and_server_escape_iac_encoding(server):
    """Ensure that IAC (byte 255) may be sent across the wire by encoding."""
    # given
    given_string = ''.join(chr(val) for val in list(range(256))) * 2

    async with server(factory=Server, encoding='iso8859-1', test_opt=(FullOption.BINARY,stdTTYPE)) as srv, \
            srv.client(factory=Client, encoding='iso8859-1', term="foo", test_opt=(FullOption.BINARY,stdTTYPE), with_reader=False) as client:

        await srv.evt.wait()
        await srv.last.send(given_string)
        result = await client.read_exactly(len(given_string))
        assert result == given_string


@pytest.mark.anyio
async def test_telnet_client_and_server_escape_iac_binary(server):
    """Ensure that IAC (byte 255) may be sent across the wire in binary."""
    # given
    _waiter = anyio.Event()
    given_string = bytes(range(256)) * 2

    async with server(factory=Server, encoding=False, test_opt=FullOption.BINARY) as srv, \
            srv.client(factory=Client, encoding=False,
                    test_opt=FullOption.BINARY, with_reader=False) as client:

        await srv.evt.wait()
        await srv.last.send(given_string)
        result = await client.read_exactly(len(given_string))
        assert result == given_string
