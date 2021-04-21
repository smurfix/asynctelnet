"""Test TTYPE, rfc-930_."""
# std imports
import anyio

# local imports
from asynctelnet.telopt import IS, WILL
from asynctelnet.options import TTYPE
from tests.accessories import BaseTestClient, Server, NoTtype, ignore_option

# 3rd party
import pytest

class _NHT:
    async def setup(self, has_tterm):
        await super().setup()

class ServerTestTtype(NoTtype, _NHT, Server):
    pass
class ClientTestTtype(NoTtype, _NHT, BaseTestClient):
    pass

@pytest.mark.anyio
async def test_telnet_server_on_ttype(server):
    """Test Server's callback method handle_recv()."""
    # given
    _waiter = anyio.Event()

    class OptTtype(TTYPE):
        async def handle_recv(self, ttype):
            await super().handle_recv(ttype)
            s=self.stream
            if s.extra.term_done:
                _waiter.set()

    async with server(factory=ServerTestTtype, encoding=None, test_opt = OptTtype) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None, test_opt = ignore_option(TTYPE)) as client:

        # exercise
        await client.send_iac(WILL, TTYPE.value)
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
    Test Server's callback method handle_recv() with long list.

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


    class OptTtype(TTYPE):
        async def handle_recv(self, ttype):
            await super().handle_recv(ttype)
            s=self.stream
            if ttype == given_ttypes[-1]:
                _waiter.set()

    async with server(factory=ServerTestTtype, encoding=None, test_opt = OptTtype) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None, test_opt = ignore_option(TTYPE)) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE.value)
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
    """Test Server's callback method handle_recv(): empty value is ignored. """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', '', 'BETA')

    class OptTtype(TTYPE):
        async def handle_recv(self, ttype):
            await super().handle_recv(ttype)
            if ttype == given_ttypes[-1]:
                _waiter.set()

    async with server(factory=ServerTestTtype, encoding=None, test_opt = OptTtype) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None, test_opt = ignore_option(TTYPE)) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE.value)
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
    """Test Server's callback method handle_recv() when value looped. """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'GAMMA', 'ALPHA')

    class OptTtype(TTYPE):
        count = 1

        async def handle_recv(self, ttype):
            await super().handle_recv(ttype)
            if self.count == len(given_ttypes):
                _waiter.set()
            self.count += 1

    async with server(factory=ServerTestTtype, encoding=None, test_opt = OptTtype) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None, test_opt = ignore_option(TTYPE)) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE.value)
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
    """Test Server's callback method handle_recv() when value repeats. """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'GAMMA', 'GAMMA')

    class OptTtype(TTYPE):
        count = 1

        async def handle_recv(self, ttype):
            await super().handle_recv(ttype)
            if self.count == len(given_ttypes):
                _waiter.set()
            self.count += 1

    async with server(factory=ServerTestTtype, encoding=None, test_opt = OptTtype) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None, test_opt = ignore_option(TTYPE)) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE.value)
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
    """Test Server's callback method handle_recv() for MUD clients (MTTS). """
    # given
    _waiter = anyio.Event()
    given_ttypes = ('ALPHA', 'BETA', 'MTTS 137')

    class OptTtype(TTYPE):
        count = 1

        async def handle_recv(self, ttype):
            await super().handle_recv(ttype)
            if self.count == len(given_ttypes):
                _waiter.set()
            self.count += 1

    async with server(factory=ServerTestTtype, encoding=None, test_opt = OptTtype) as srv, \
            srv.client(factory=ClientTestTtype, encoding=None, test_opt = ignore_option(TTYPE)) as client:

        # exercise,
        await client.send_iac(WILL, TTYPE.value)
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
