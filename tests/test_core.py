"""Test instantiation of basic server and client forms."""
# std imports
import anyio
import os
import sys
import tempfile
import time
import unittest.mock

# local imports
import asynctelnet
from asynctelnet.client import TelnetClient, open_connection
from tests.accessories import Server, shell
from anyio.streams.buffered import BufferedByteReceiveStream

# 3rd party
import pytest
import pexpect


@pytest.mark.anyio
async def test_create_server(server):
    """Test asynctelnet.create_server basic instantiation."""
    # exercise,
    async with server() as srv:
        pass

@pytest.mark.anyio
async def test_open_connection(bind_host, server):
    """Exercise asynctelnet.open_connection with default options."""
    evt = anyio.Event()
    async def server_shell(stream):
        evt.set()
        assert repr(stream) == "<Server: remote: -TTYPE extra: term='unknown' term_done=False charset='' cols=80 rows=25 timeout=300 mode:local -xon_any +slc_sim>"
        await anyio.sleep(0.5)

    async with server(shell=server_shell) as srv, \
        srv.client() as client:

        assert repr(client) == "<TelnetClient: local: -TTYPE extra: charset='' lang='C' cols=80 rows=25 term=None tspeed='38400,38400' xdisploc='' mode:local -xon_any +slc_sim>"


@pytest.mark.anyio
async def test_create_server_conditionals(server):
    """Test asynctelnet.create_server conditionals."""
    # exercise,
    async with server(factory=asynctelnet.TelnetServer) as port:
        pass


@pytest.mark.anyio
async def test_create_server_on_connect(bind_host, server):
    """Test on_connect() anonymous function callback of create_server."""
    pytest.skip("superfluous")

    # given,
    given_pf = unittest.mock.MagicMock()
    async with server(shell=shell, protocol_factory=given_pf) as port:
        async with open_connection(host=bind_host, port=port) as client:
            pass

    # verify
    assert given_pf.called


@pytest.mark.anyio
async def test_telnet_server_open_close(server):
    """Test asynctelnet.TelnetServer() instantiation and connection_made()."""
    from asynctelnet.telopt import IAC, WONT, TTYPE
    # given,
    evt = anyio.Event()
    async def shell(s):
        evt.set()
        await s.send("Goodbye!")

    async with server(shell=shell) as srv:
        async with await anyio.connect_tcp(srv.host, srv.port) as s:
            await s.send(bytes([IAC, WONT, TTYPE]) + b'bye\r')
            await evt.wait()
            s = BufferedByteReceiveStream(s)
            result = await s.receive_exactly(11)
            assert result == b'\xff\xfd\x18Goodbye!', result


@pytest.mark.anyio
async def test_telnet_client_open_close_by_write(
        bind_host, unused_tcp_port):
    """Exercise BaseClient.connection_lost() on writer closed."""
    pytest.skip("Not implemented")
    await event_loop.create_server(asyncio.Protocol,
                                        bind_host, unused_tcp_port)

    reader, writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port,
        connect_minwait=0.05)
    writer.close()
    assert (await reader.read()) == ''


@pytest.mark.anyio
async def test_telnet_client_open_closed_by_peer(
        bind_host, unused_tcp_port):
    """Exercise BaseClient.connection_lost()."""
    pytest.skip("Superfluous, not ported")

    class DisconnecterProtocol(asyncio.Protocol):
        def connection_made(self, transport):
            # disconnect on connect
            transport.close()

    await event_loop.create_server(DisconnecterProtocol,
                                        bind_host, unused_tcp_port)

    reader, writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port,
        connect_minwait=0.05)

    # read until EOF, no data received.
    data_received = await reader.read()
    assert data_received == ''


@pytest.mark.anyio
async def test_telnet_server_advanced_negotiation(server):
    """Test asynctelnet.TelnetServer() advanced negotiation."""
    # given
    from asynctelnet.telopt import (
        IAC, DO, WILL, SB, TTYPE, NEW_ENVIRON, NAWS, SGA, ECHO, CHARSET, BINARY
    )

    async with server(term="yes", encoding="utf-8") as srv, \
            srv.client(term="yes", encoding="utf-8") as client:
        await srv.evt.wait()

        # verify,
        assert srv.last._local_option == {
            SGA: True,
            ECHO: True,
            BINARY: True,
            CHARSET: True,
        }
        assert srv.last._remote_option == {
            BINARY: True,
            NEW_ENVIRON: True,
            CHARSET: True,
            # server's request to negotiation TTYPE affirmed
            TTYPE: True,
            # remaining unreplied values from begin_advanced_negotiation()
            NAWS: True,
        }


@pytest.mark.anyio
async def test_telnet_server_end_by_client(server):
    """Client terminates"""

    # given
    _waiter = anyio.Event()

    async def shell(s):
        await s.send(b"One")
        _buf = bytearray()
        try:
            while True:
                b = await s.receive()
                _buf.extend(b)
        except anyio.EndOfStream:
            assert _buf == b"Two"
        _waiter.set()

    _buf = bytearray()
    with anyio.fail_after(1):
        async with server(shell=shell,encoding=False) as srv:
            async with srv.client(encoding=False, with_reader=False) as client:

                await client.send(b"Two")
                while _buf != b"One":
                    b = await client.receive(3)
                    _buf.extend(b)

            # client is now closed
            await _waiter.wait()


@pytest.mark.anyio
async def test_telnet_server_end_by_server(server):
    """Server terminates"""

    # given
    _waiter = anyio.Event()

    async def shell(s):
        await s.send(b"tWo")
        _buf = bytearray()
        while _buf != b"oNe":
            b = await s.receive(3)
            _buf.extend(b)
        _waiter.set()

    _buf = bytearray()
    with anyio.fail_after(1):
        async with server(shell=shell,encoding=False) as srv:
            async with srv.client(encoding=False, with_reader=False) as client:
                await client.send(b"oNe")
                print("QS")
                try:
                    while True:
                        b = await client.receive()
                        print("QR",b)
                        _buf.extend(b)
                except anyio.EndOfStream:
                    print("QE")
                    assert _buf == b"tWo"
                # server is now closed
                print("QW")
                await _waiter.wait()



@pytest.mark.anyio
async def test_telnet_server_idle_duration(server):
    """Exercise TelnetServer.idle property."""
    pytest.skip("Not implemented")

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
async def test_telnet_client_idle_duration_minwait(server):
    """Exercise TelnetClient.idle property and minimum connection time."""
    pytest.skip("Not implemented")

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
async def test_telnet_server_closed_by_error(server):
    """Exercise a client raising an error."""

    class CustomException(Exception):
        pass

    async def NoOp(client):
        raise CustomException

    with pytest.raises(CustomException):

        async with server(shell=NoOp) as srv, \
            srv.client() as client:

            pass


@pytest.mark.anyio
async def test_telnet_client_open_close_by_error(server):
    """Exercise a server raising an error."""

    class CustomException(Exception):
        pass


    with pytest.raises(CustomException):

        async with server() as srv, \
            srv.client() as client:

            raise CustomException


@pytest.mark.anyio
async def test_telnet_server_negotiation_fail(server):
    """Test asynctelnet.TelnetServer() negotiation failure with client."""
    from asynctelnet.telopt import TTYPE

    # given
    _waiter = anyio.Event()

    class TimeoutServer(Server):
        async def setup(self):
            with pytest.raises(TimeoutError):
                await super().setup(has_tterm=0.05)

            # Failed, so another request will imediately fail again
            with pytest.raises(TimeoutError):
                await self.remote_option(TTYPE)
            _waiter.set()

    async with server(factory=TimeoutServer) as srv, \
            await anyio.connect_tcp(srv.host, srv.port) as conn:

        with anyio.fail_after(0.5):
            b = await conn.receive(3)  # IAC DO TTYPE from the server
            assert b == b'\xff\xfd\x18'
            await _waiter.wait()

    assert repr(srv.last) == "<TimeoutServer: remote: !+TTYPE extra: term='unknown' term_done=False charset='' cols=80 rows=25 timeout=300 mode:local -xon_any +slc_sim>"

@pytest.mark.anyio
async def test_telnet_client_negotiation_fail(bind_host, unused_tcp_port):
    """Test asynctelnet.TelnetCLient() negotiation failure with server."""
    from asynctelnet.telopt import TTYPE

    class TimeoutClient(TelnetClient):
        async def setup(self):
            with pytest.raises(TimeoutError):
                await super().setup(has_tterm=0.1)

            # Failed, so another request will imediately fail again
            with pytest.raises(TimeoutError):
                await self.local_option(TTYPE)

    async def server(s):
        b = await s.receive(3)
        assert b == b'\xff\xfb\x18'
        await anyio.sleep(2)
        assert False

    async with await anyio.create_tcp_listener(local_host=bind_host, local_port=unused_tcp_port) as s, \
        anyio.create_task_group() as tg:
        tg.start_soon(s.serve, server)
        async with open_connection(client_factory=TimeoutClient, host=bind_host, port=unused_tcp_port) as client:
            tg.cancel_scope.cancel()

    assert repr(client) == "<TimeoutClient: local: !+TTYPE extra: charset='UTF-8' lang='C.UTF-8' cols=80 rows=25 term='unknown' tspeed='38400,38400' xdisploc='' mode:local -xon_any +slc_sim>"

@pytest.mark.anyio
async def test_telnet_server_as_module():
    """Test __main__ hook, when executing python -m asynctelnet.server --help"""
    pytest.skip("Doesn't work when testing without tox")

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
    pytest.skip("Doesn't work when testing without tox")

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
    pytest.skip("Doesn't work when testing without tox")

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
    pytest.skip("Doesn't work when testing without tox")

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
    pytest.skip("Doesn't work when testing without tox")

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
    pytest.skip("Doesn't work when testing without tox")

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
