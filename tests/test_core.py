"""Test instantiation of basic server and client forms."""
# std imports
import asyncio
import os
import sys
import tempfile
import time
import unittest.mock

# local imports
import asynctelnet
from tests.accessories import (
    unused_tcp_port,
    bind_host
)

# 3rd party
import pytest
import pexpect


@pytest.mark.anyio
async def test_create_server(server):
    """Test asynctelnet.create_server basic instantiation."""
    # exercise,
    async with server() as port:
        pass

@pytest.mark.anyio
async def test_open_connection(bind_host, server):
    """Exercise asynctelnet.open_connection with default options."""
    evt = anyio.create_event()
    async def shell(stream):
        await evt.set()
        assert repr(stream) == (
            '<TelnetStream server mode:kludge +lineflow -xon_any +slc_sim '
            'server-will:BINARY,ECHO,SGA '
            'client-will:BINARY,CHARSET,NAWS,NEW_ENVIRON,TTYPE>')
        await anyio.sleep(0.5)

    async with server(shell=shell) as port:
        async with open_connection(host=bind_host, port=port) as client:
            assert repr(client) == (
                '<TelnetStream client mode:kludge +lineflow -xon_any +slc_sim '
                'client-will:BINARY,CHARSET,NAWS,NEW_ENVIRON,TTYPE '
                'server-will:BINARY,ECHO,SGA>')


@pytest.mark.anyio
async def test_create_server_conditionals(server):
    """Test asynctelnet.create_server conditionals."""
    # exercise,
    async with server(
            protocol_factory=lambda: asynctelnet.TelnetServer) as port:
        pass


@pytest.mark.anyio
async def test_create_server_on_connect(bind_host, server):
    """Test on_connect() anonymous function callback of create_server."""
    # given,
    given_pf = unittest.mock.MagicMock()
    async with server(shell=shell, protocol_factory=given_pf) as port:
        async with open_connection(host=bind_host, port=port) as client:
            pass

    # verify
    assert given_pf.called


@pytest.mark.anyio
async def test_telnet_server_open_close(bind_host, server):
    """Test asynctelnet.TelnetServer() instantiation and connection_made()."""
    from asynctelnet.telopt import IAC, WONT, TTYPE
    # given,
    evt = anyio.create_event()
    async def shell(s):
        await evt.set()
        await s.send("Goodbye!")
    async with server(shell=shell) as port:
        async with await anyio.connect_tcp(bind_host, port) as s:
            await s.send(bytes([IAC, WONT, TTYPE]) + b'bye\r')
            await evt.wait()
            result = await s.receive()
            assert result == b'\xff\xfd\x18Goodbye!', result


#@pytest.mark.anyio
#async def test_telnet_client_open_close_by_write(
#        bind_host, unused_tcp_port):
#    """Exercise BaseClient.connection_lost() on writer closed."""
#    await event_loop.create_server(asyncio.Protocol,
#                                        bind_host, unused_tcp_port)
#
#    reader, writer = await asynctelnet.open_connection(
#        host=bind_host, port=unused_tcp_port,
#        connect_minwait=0.05)
#    writer.close()
#    assert (await reader.read()) == ''
#
#
#@pytest.mark.anyio
#async def test_telnet_client_open_closed_by_peer(
#        bind_host, unused_tcp_port):
#    """Exercise BaseClient.connection_lost()."""
#    class DisconnecterProtocol(asyncio.Protocol):
#        def connection_made(self, transport):
#            # disconnect on connect
#            transport.close()
#
#    await event_loop.create_server(DisconnecterProtocol,
#                                        bind_host, unused_tcp_port)
#
#    reader, writer = await asynctelnet.open_connection(
#        host=bind_host, port=unused_tcp_port,
#        connect_minwait=0.05)
#
#    # read until EOF, no data received.
#    data_received = await reader.read()
#    assert data_received == ''
#

@pytest.mark.anyio
async def test_telnet_server_advanced_negotiation(
        bind_host, unused_tcp_port):
    """Test asynctelnet.TelnetServer() advanced negotiation."""
    # given
    from asynctelnet.telopt import (
        IAC, DO, WILL, SB, TTYPE, NEW_ENVIRON, NAWS, SGA, ECHO, CHARSET, BINARY
    )
    _waiter = asyncio.Future()

    class ServerTestAdvanced(asynctelnet.TelnetServer):
        def begin_advanced_negotiation(self):
            super().begin_advanced_negotiation()
            _waiter.set_result(self)

    await asynctelnet.create_server(
        protocol_factory=ServerTestAdvanced,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # exercise,
    writer.write(IAC + WILL + TTYPE)
    server = await asyncio.wait_for(_waiter, 0.5)

    # verify,
    assert server.writer.remote_option[TTYPE] is True
    assert server.writer.pending_option == {
        # server's request to negotiation TTYPE affirmed
        DO + TTYPE: False,
        # server's request for TTYPE value unreplied
        SB + TTYPE: True,
        # remaining unreplied values from begin_advanced_negotiation()
        DO + NEW_ENVIRON: True,
        DO + CHARSET: True,
        DO + NAWS: True,
        WILL + SGA: True,
        WILL + ECHO: True,
        WILL + BINARY: True,
    }


@pytest.mark.anyio
async def test_telnet_server_closed_by_client(
        bind_host, unused_tcp_port):
    """Exercise TelnetServer.connection_lost."""
    # given
    _waiter = asyncio.Future()

    await asynctelnet.create_server(
        _waiter_closed=_waiter,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # exercise,
    writer.close()

    # verify,
    srv_instance = await asyncio.wait_for(_waiter, 0.5)
    assert srv_instance._closing

    # exercise, a 2nd call to .connection_lost() returns early,
    # allowing callbacks the freedom to call it at any time from
    # the server-end to dump the client.
    srv_instance.connection_lost(exc=None)


@pytest.mark.anyio
async def test_telnet_server_eof_by_client(
        bind_host, unused_tcp_port):
    """Exercise TelnetServer.eof_received()."""
    # given
    _waiter = asyncio.Future()

    await asynctelnet.create_server(
        _waiter_closed=_waiter,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # exercise,
    writer.write_eof()

    # verify,
    srv_instance = await asyncio.wait_for(_waiter, 0.5)
    assert srv_instance._closing


@pytest.mark.anyio
async def test_telnet_server_closed_by_server(
        bind_host, unused_tcp_port):
    """Exercise TelnetServer.connection_lost by close()."""
    from asynctelnet.telopt import IAC, DO, WONT, TTYPE

    # given
    _waiter_connected = asyncio.Future()
    _waiter_closed = asyncio.Future()

    await asynctelnet.create_server(
        _waiter_connected=_waiter_connected,
        _waiter_closed=_waiter_closed,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # data received by client, connection is made
    expect_hello = IAC + DO + TTYPE
    hello_reply = IAC + WONT + TTYPE + b'quit' + b'\r\n'

    # exercise,
    hello = await reader.readexactly(len(expect_hello))

    # verify,
    assert hello == expect_hello

    # exercise,
    writer.write(hello_reply)
    server = await asyncio.wait_for(_waiter_connected, 0.5)

    # exercise, by closing.
    server.writer.close()

    # verify
    await asyncio.wait_for(_waiter_closed, 0.5)


@pytest.mark.anyio
async def test_telnet_server_idle_duration(
        bind_host, unused_tcp_port):
    """Exercise TelnetServer.idle property."""
    from asynctelnet.telopt import IAC, WONT, TTYPE

    # given
    _waiter_connected = asyncio.Future()
    _waiter_closed = asyncio.Future()

    await asynctelnet.create_server(
        _waiter_connected=_waiter_connected,
        _waiter_closed=_waiter_closed,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    writer.write(IAC + WONT + TTYPE)
    server = await asyncio.wait_for(_waiter_connected, 0.5)

    # verify
    assert 0 <= server.idle <= 0.5
    assert 0 <= server.duration <= 0.5


@pytest.mark.anyio
async def test_telnet_client_idle_duration_minwait(
        bind_host, unused_tcp_port):
    """Exercise TelnetClient.idle property and minimum connection time."""
    from asynctelnet.telopt import IAC, WONT, TTYPE

    # a server that doesn't care
    await event_loop.create_server(asyncio.Protocol,
                                        bind_host, unused_tcp_port)

    given_minwait = 0.100

    stime = time.time()
    reader, writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port,
        connect_minwait=given_minwait, connect_maxwait=given_minwait)

    elapsed_ms = int((time.time() - stime) * 1e3)
    expected_ms = int(given_minwait * 1e3)
    assert expected_ms <= elapsed_ms <= expected_ms + 50

    # verify
    assert 0 <= writer.protocol.idle <= 0.5
    assert 0 <= writer.protocol.duration <= 0.5


@pytest.mark.anyio
async def test_telnet_server_closed_by_error(
        bind_host, unused_tcp_port):
    """Exercise TelnetServer.connection_lost by exception."""
    from asynctelnet.telopt import IAC, DO, WONT, TTYPE

    # given
    _waiter_connected = asyncio.Future()
    _waiter_closed = asyncio.Future()

    await asynctelnet.create_server(
        _waiter_connected=_waiter_connected,
        _waiter_closed=_waiter_closed,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    writer.write(IAC + WONT + TTYPE)
    server = await asyncio.wait_for(_waiter_connected, 0.5)

    class CustomException(Exception):
        pass

    # exercise, by connection_lost(exc=Exception())..
    server.writer.write('Bye!')
    server.connection_lost(CustomException('blah!'))

    # verify, custom exception is thrown into any yielding reader
    with pytest.raises(CustomException):
        await server.reader.read()


@pytest.mark.anyio
async def test_telnet_client_open_close_by_error(
        bind_host, unused_tcp_port):
    """Exercise BaseClient.connection_lost() on error."""
    await event_loop.create_server(asyncio.Protocol,
                                        bind_host, unused_tcp_port)

    class GivenException(Exception):
        pass

    reader, writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port, connect_minwait=0.05)

    writer.protocol.connection_lost(GivenException("candy corn 4 everyone"))
    with pytest.raises(GivenException):
        await reader.read()


@pytest.mark.anyio
async def test_telnet_server_negotiation_fail(
        bind_host, unused_tcp_port):
    """Test asynctelnet.TelnetServer() negotiation failure with client."""
    from asynctelnet.telopt import DO, TTYPE
    # given
    _waiter_connected = asyncio.Future()

    await asynctelnet.create_server(
        _waiter_connected=_waiter_connected,
        host=bind_host, port=unused_tcp_port,
        connect_maxwait=0.05)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # exercise,
    await reader.readexactly(3)  # IAC DO TTYPE, we ignore it!

    # negotiation then times out, deferring to waiter_connected.
    server = await asyncio.wait_for(_waiter_connected, 1.0)

    # verify,
    assert server.negotiation_should_advance() is False
    assert server.writer.pending_option[DO + TTYPE] == True

    assert repr(server.writer) == ('<TelnetWriter server '
                                   'mode:local +lineflow -xon_any +slc_sim '
                                   'failed-reply:DO TTYPE>')

@pytest.mark.anyio
async def test_telnet_client_negotiation_fail(
        bind_host, unused_tcp_port):
    """Test asynctelnet.TelnetCLient() negotiation failure with server."""

    class ClientNegotiationFail(asynctelnet.TelnetClient):
        def connection_made(self, transport):
            from asynctelnet.telopt import WILL, TTYPE
            super().connection_made(transport)
            # this creates a pending negotiation demand from the client-side.
            self.writer.iac(WILL, TTYPE)

    # a server that never responds with nothing.
    await event_loop.create_server(asyncio.Protocol,
                                        bind_host, unused_tcp_port)

    given_minwait = 0.05
    given_maxwait = 0.100

    stime = time.time()
    reader, writer = await asyncio.wait_for(asynctelnet.open_connection(
        client_factory=ClientNegotiationFail, host=bind_host,
        port=unused_tcp_port,
        connect_minwait=given_minwait,
        connect_maxwait=given_maxwait), 5)

    elapsed_ms = int((time.time() - stime) * 1e3)
    expected_ms = int(given_maxwait * 1e3)
    assert expected_ms <= elapsed_ms <= expected_ms + 50


@pytest.mark.anyio
async def test_telnet_server_as_module():
    """Test __main__ hook, when executing python -m asynctelnet.server --help"""
    prog = sys.executable
    args = [prog, '-m', 'asynctelnet.server', '--help']
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE,
               stderr=asyncio.subprocess.PIPE)

    # we would expect the script to display help output and exit
    help_output, _ = await proc.communicate()
    assert help_output.startswith(b'usage: server.py [-h]')
    await proc.communicate()
    await proc.wait()


@pytest.mark.anyio
async def test_telnet_server_cmdline(bind_host, unused_tcp_port):
    """Test executing asynctelnet/server.py as server"""
    # this code may be reduced when pexpect asyncio is bugfixed ..
    prog = pexpect.which('asynctelnet-server')
    args = [prog, bind_host, str(unused_tcp_port), '--loglevel=info',
            '--connect-maxwait=0.05']
    proc = await asyncio.create_subprocess_exec(
        *args, stderr=asyncio.subprocess.PIPE)

    seen = b''
    while True:
        line = await asyncio.wait_for(proc.stderr.readline(), 0.5)
        if b'Server ready' in line:
            break
        seen += line
        assert line, seen.decode()  # EOF reached

    # client connects,
    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # and closes,
    await reader.readexactly(3)  # IAC DO TTYPE, we ignore it!
    writer.close()

    seen = b''
    while True:
        line = await asyncio.wait_for(proc.stderr.readline(), 0.5)
        if b'Connection closed' in line:
            break
        seen += line
        assert line, seen.decode()  # EOF reached

    # send SIGTERM
    proc.terminate()

    # we would expect the server to gracefully end.
    await proc.communicate()
    await proc.wait()


@pytest.mark.anyio
async def test_telnet_client_as_module():
    """Test __main__ hook, when executing python -m asynctelnet.client --help"""
    prog = sys.executable
    args = [prog, '-m', 'asynctelnet.client', '--help']
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE,
               stderr=asyncio.subprocess.PIPE)

    # we would expect the script to display help output and exit
    help_output, _ = await proc.communicate()
    assert help_output.startswith(b'usage: client.py [-h]')
    await proc.communicate()
    await proc.wait()


@pytest.mark.anyio
async def test_telnet_client_cmdline(bind_host, unused_tcp_port):
    """Test executing asynctelnet/client.py as client"""
    # this code may be reduced when pexpect asyncio is bugfixed ..
    # we especially need pexpect to pass sys.stdin.isatty() test.
    prog = pexpect.which('asynctelnet-client')
    args = [prog, bind_host, str(unused_tcp_port), '--loglevel=info',
            '--connect-minwait=0.05', '--connect-maxwait=0.05']

    class HelloServer(asyncio.Protocol):
        def connection_made(self, transport):
            super().connection_made(transport)
            transport.write(b'hello, space cadet.\r\n')
            # hangup
            event_loop.call_soon(transport.close)

    # start vanilla tcp server
    await event_loop.create_server(HelloServer,
                                        bind_host, unused_tcp_port)

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE)

    line = await asyncio.wait_for(proc.stdout.readline(), 1.5)
    assert line.strip() == b"Escape character is '^]'."

    line = await asyncio.wait_for(proc.stdout.readline(), 1.5)
    assert line.strip() == b'hello, space cadet.'

    # message received, expect the client to gracefully quit.
    out, err = await asyncio.wait_for(proc.communicate(), 1)
    assert out == b'\x1b[m\nConnection closed by foreign host.\n'


@pytest.mark.anyio
async def test_telnet_client_tty_cmdline(bind_host, unused_tcp_port):
    """Test executing asynctelnet/client.py as client using a tty (pexpect)"""
    # this code may be reduced when pexpect asyncio is bugfixed ..
    # we especially need pexpect to pass sys.stdin.isatty() test.
    prog, args = 'asynctelnet-client', [
        bind_host, str(unused_tcp_port), '--loglevel=warning',
        '--connect-minwait=0.05', '--connect-maxwait=0.05']

    class HelloServer(asyncio.Protocol):
        def connection_made(self, transport):
            super().connection_made(transport)
            transport.write(b'hello, space cadet.\r\n')
            event_loop.call_soon(transport.close)

    # start vanilla tcp server
    await event_loop.create_server(HelloServer,
                                        bind_host, unused_tcp_port)
    proc = pexpect.spawn(prog, args)
    await proc.expect(pexpect.EOF, async_=True, timeout=5)
    # our 'space cadet' has \r\n hardcoded, so \r\r\n happens, ignore it
    assert proc.before == (b"Escape character is '^]'.\r\n"
                           b"hello, space cadet.\r\r\n"
                           b"\x1b[m\r\n"
                           b"Connection closed by foreign host.\r\n")

@pytest.mark.anyio
async def test_telnet_client_cmdline_stdin_pipe(bind_host, unused_tcp_port):
    """Test sending data through command-line client (by os PIPE)."""
    # this code may be reduced when pexpect asyncio is bugfixed ..
    # we especially need pexpect to pass sys.stdin.isatty() test.
    prog = pexpect.which('asynctelnet-client')
    fd, logfile = tempfile.mkstemp(prefix='asynctelnet', suffix='.log')
    os.close(fd)

    args = [prog, bind_host, str(unused_tcp_port), '--loglevel=info',
            '--connect-minwait=0.15', '--connect-maxwait=0.15',
            '--logfile={0}'.format(logfile)]

    async def shell(reader, writer):
        writer.write('Press Return to continue:')
        inp = await reader.readline()
        if inp:
            writer.echo(inp)
            writer.write('\ngoodbye.\n')
        await writer.drain()
        writer.close()

    # start server
    await asynctelnet.create_server(
        host=bind_host, port=unused_tcp_port,
        shell=shell,
        connect_maxwait=0.05)

    # start client by way of pipe
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    #line = await asyncio.wait_for(proc.stdout.readline(), 1.5)
    #assert line.strip() == b"Escape character is '^]'."

    # message received, expect the client to gracefully quit.
    stdout, stderr = await asyncio.wait_for(proc.communicate(b'\r'), 2)

    # And finally, analyze the contents of the logfile,
    # - 2016-03-18 20:19:25,227 INFO client_base.py:113 Connected to <Peer 127.0.0.1 51237>
    # - 2016-03-18 20:19:25,286 INFO client_base.py:67 Connection closed to <Peer 127.0.0.1 51237>
    logfile_output = open(logfile).read().splitlines()
    assert stdout == (b"Escape character is '^]'.\n"
                      b"Press Return to continue:\r\ngoodbye.\n"
                      b"\x1b[m\nConnection closed by foreign host.\n")

    # verify,
    assert len(logfile_output) == 2, logfile
    assert 'Connected to <Peer' in logfile_output[0], logfile
    assert 'Connection closed to <Peer' in logfile_output[1], logfile
    os.unlink(logfile)
