"""Test TTYPE, rfc-930_."""
# std imports
import anyio

# local imports
from asynctelnet.telopt import IS, WILL, TTYPE
from tests.accessories import BaseTestClient, Server, NoTtype

# 3rd party
import pytest

class ClientTestTtype(NoTtype, BaseTestClient):
    pass

@pytest.mark.anyio
async def test_telnet_server_on_ttype(server):
    """Test Server's callback method handle_recv_ttype()."""
    # given
    _waiter = anyio.Event()

    class ServerTestTtype(NoTtype, Server):
        async def handle_recv_ttype(self, ttype):
            await super().handle_recv_ttype(ttype)
            if self.extra.term_done:
                _waiter.set()

    async with server(factory=ServerTestTtype, encoding=None) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None) as client:

        # exercise
        await client.send_iac(WILL, TTYPE)
        await client.send_subneg(TTYPE, IS, b'ALPHA')
        await client.send_subneg(TTYPE, IS, b'ALPHA')

        # verify
        with anyio.fail_after(0.5):
            await _waiter.wait()
            await srv.evt.wait()

    assert 'ALPHA' == srv.last.extra.ttype1
    assert 'ALPHA' == srv.last.extra.ttype2
    assert 'ALPHA' == srv.last.extra.TERM


@pytest.mark.anyio
async def test_telnet_server_on_ttype_beyond_max(server):
    """
    Test Server's callback method handle_recv_ttype() with long list.

    After TTYPE_LOOPMAX, we stop requesting and tracking further
    terminal types; something of an error (a warning is emitted),
    and assume the use of the first we've seen.  This is to prevent
    an infinite loop with a distant end that is not conforming.
    """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'GAMMA', 'DELTA',
                    'EPSILON', 'ZETA', 'ETA', 'THETA',
                    'IOTA', 'KAPPA', 'LAMBDA', 'MU')

    assert len(given_ttypes) > Server.TTYPE_LOOPMAX

    class ServerTestTtype(NoTtype, Server):
        async def handle_recv_ttype(self, ttype):
            await super().handle_recv_ttype(ttype)
            if ttype == given_ttypes[-1]:
                _waiter.set()

    async with server(factory=ServerTestTtype, encoding=None) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE)
        for send_ttype in given_ttypes:
            await client.send_subneg(TTYPE, IS, send_ttype.encode('ascii'))

        with anyio.fail_after(0.5):
            await _waiter.wait()
            await srv.evt.wait()

    # verify,
    for idx in range(Server.TTYPE_LOOPMAX):
        key = f'ttype{idx + 1}'
        expected = given_ttypes[idx]
        assert srv.last.extra[key] == expected, (idx, key)

    # ttype{max} gets overwritten continiously, so the last given
    # ttype is the last value.
    key = f'ttype{Server.TTYPE_LOOPMAX + 1}'
    expected = given_ttypes[-1]
    assert srv.last.extra[key] == expected
    assert srv.last.extra.TERM == expected


@pytest.mark.anyio
async def test_telnet_server_on_ttype_empty(server):
    """Test Server's callback method handle_recv_ttype(): empty value is ignored. """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', '', 'BETA')

    class ServerTestTtype(NoTtype, Server):
        async def handle_recv_ttype(self, ttype):
            await super().handle_recv_ttype(ttype)
            if ttype == given_ttypes[-1]:
                _waiter.set()

    async with server(factory=ServerTestTtype, encoding=None) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE)
        for send_ttype in given_ttypes:
            await client.send_subneg(TTYPE, IS, send_ttype.encode('ascii'))

        with anyio.fail_after(0.5):
            await _waiter.wait()
            await srv.evt.wait()

        # verify,
        assert srv.last.extra.ttype1 == 'ALPHA'
        assert srv.last.extra.ttype2 == 'BETA'
        assert srv.last.extra.TERM == 'BETA'


@pytest.mark.anyio
async def test_telnet_server_on_ttype_looped(server):
    """Test Server's callback method handle_recv_ttype() when value looped. """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'GAMMA', 'ALPHA')

    class ServerTestTtype(NoTtype, Server):
        count = 1

        async def handle_recv_ttype(self, ttype):
            await super().handle_recv_ttype(ttype)
            if self.count == len(given_ttypes):
                _waiter.set()
            self.count += 1

    async with server(factory=ServerTestTtype, encoding=None) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE)
        for send_ttype in given_ttypes:
            await client.send_subneg(TTYPE, IS, send_ttype.encode('ascii'))

        with anyio.fail_after(0.5):
            await _waiter.wait()
            await srv.evt.wait()

        assert srv.last.extra.ttype1 == 'ALPHA'
        assert srv.last.extra.ttype2 == 'BETA'
        assert srv.last.extra.ttype3 == 'GAMMA'
        assert srv.last.extra.ttype4 == 'ALPHA'
        assert srv.last.extra.TERM == 'ALPHA'


@pytest.mark.anyio
async def test_telnet_server_on_ttype_repeated(server):
    """Test Server's callback method handle_recv_ttype() when value repeats. """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'GAMMA', 'GAMMA')

    class ServerTestTtype(NoTtype, Server):
        count = 1

        async def handle_recv_ttype(self, ttype):
            await super().handle_recv_ttype(ttype)
            if self.count == len(given_ttypes):
                _waiter.set()
            self.count += 1

    async with server(factory=ServerTestTtype, encoding=None) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE)
        for send_ttype in given_ttypes:
            await client.send_subneg(TTYPE, IS, send_ttype.encode('ascii'))

        with anyio.fail_after(0.5):
            await _waiter.wait()
            await srv.evt.wait()

        # verify,
        assert srv.last.extra.ttype1 == 'ALPHA'
        assert srv.last.extra.ttype2 == 'BETA'
        assert srv.last.extra.ttype3 == 'GAMMA'
        assert srv.last.extra.ttype4 == 'GAMMA'
        assert srv.last.extra.TERM == 'GAMMA'


@pytest.mark.anyio
async def test_telnet_server_on_ttype_mud(server):
    """Test Server's callback method handle_recv_ttype() for MUD clients (MTTS). """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'MTTS 137')

    class ServerTestTtype(NoTtype, Server):
        count = 1

        async def handle_recv_ttype(self, ttype):
            await super().handle_recv_ttype(ttype)
            if self.count == len(given_ttypes):
                _waiter.set()
            self.count += 1

    async with server(factory=ServerTestTtype, encoding=None) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE)
        for send_ttype in given_ttypes:
            await client.send_subneg(TTYPE, IS, send_ttype.encode('ascii'))

        with anyio.fail_after(0.5):
            await _waiter.wait()
            await srv.evt.wait()

        # verify,
        assert srv.last.extra.ttype1 == 'ALPHA'
        assert srv.last.extra.ttype2 == 'BETA'
        assert srv.last.extra.ttype3 == 'MTTS 137'
        assert srv.last.extra.TERM == 'BETA'
