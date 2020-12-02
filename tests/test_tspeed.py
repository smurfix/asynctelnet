"""Test TSPEED, rfc-1079_."""
# std imports
import asyncio

# local imports
import asynctelnet
from asynctelnet.tests.accessories import (
    unused_tcp_port,
    bind_host
)

# 3rd party
import pytest


@pytest.mark.anyio
async def test_telnet_server_on_tspeed(bind_host, unused_tcp_port):
    """Test Server's callback method on_tspeed()."""
    # given
    from asynctelnet.telopt import IAC, WILL, SB, SE, IS, TSPEED
    _waiter = asyncio.Future()

    class ServerTestTspeed(asynctelnet.TelnetServer):
        def on_tspeed(self, rx, tx):
            super().on_tspeed(rx, tx)
            _waiter.set_result(self)

    await asynctelnet.create_server(
        protocol_factory=ServerTestTspeed,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asyncio.open_connection(
        host=bind_host, port=unused_tcp_port)

    # exercise,
    writer.write(IAC + WILL + TSPEED)
    writer.write(IAC + SB + TSPEED + IS + b'123,456' + IAC + SE)

    # verify,
    srv_instance = await asyncio.wait_for(_waiter, 0.5)
    assert srv_instance.get_extra_info('tspeed') == '123,456'


@pytest.mark.anyio
async def test_telnet_client_send_tspeed(bind_host, unused_tcp_port):
    """Test Client's callback method send_tspeed()."""
    # given
    _waiter = asyncio.Future()
    given_rx, given_tx = 1337, 1919

    class ServerTestTspeed(asynctelnet.TelnetServer):
        def on_tspeed(self, rx, tx):
            super().on_tspeed(rx, tx)
            _waiter.set_result((rx, tx))

        def begin_advanced_negotiation(self):
            from asynctelnet.telopt import DO, TSPEED
            super().begin_advanced_negotiation()
            self.writer.iac(DO, TSPEED)

    await asynctelnet.create_server(
        protocol_factory=ServerTestTspeed,
        host=bind_host, port=unused_tcp_port)

    reader, writer = await asynctelnet.open_connection(
        host=bind_host, port=unused_tcp_port,
        tspeed=(given_rx, given_tx), connect_minwait=0.05)

    recv_rx, recv_tx = await asyncio.wait_for(_waiter, 0.5)
    assert recv_rx == given_rx
    assert recv_tx == given_tx
