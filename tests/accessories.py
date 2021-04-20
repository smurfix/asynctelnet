"""Test accessories for asynctelnet project."""
import pytest
from functools import partial
import anyio

from asynctelnet.server import server_loop,TelnetServer, BaseServer
from asynctelnet.client import BaseClient, TelnetClient
from asynctelnet.options import BaseOption, HalfOption, Forced

class Test_Opt:
    test_opt = None

    async def setup(self, **kw):
        if self.test_opt is not None:
            if isinstance(self.test_opt,(list,tuple)):
                for opt in self.test_opt:
                    self.opt.add(opt)
            else:
                self.opt.add(self.test_opt)
        await super().setup(**kw)

    def _unref(self):
        # don't clean up, tests need the data
        pass

class Server(Test_Opt, TelnetServer):
    pass

class BaseTestServer(Test_Opt, BaseServer):
    pass

async def shell(client):
    client.log.debug("R start")
    try:
        while True:
            d = await client.receive()
            client.log.debug("R:%s",d)
    except anyio.EndOfStream:
        pass

class NoTtype:
    """
    Mix-in
    """
    async def setup(self):
        await super().setup(has_tterm=False)
        self.extra.ttype = "whatever"

def ignore_option(value_):
    value_=getattr(value_,'value',value_)
    class cls(SilentOption):
        value=value_
    cls.__name__ = f"I_{value_}"
    return cls

class SilentOption(BaseOption):
    """
    An option hand ler that doesn't do anything.
    """
    def _setup_half(self):
        self.loc = SilentHalfOption(self, True)
        self.rem = SilentHalfOption(self, False)

    async def send_do(self, force:Forced = Forced.no) -> bool:
        return False
    async def send_will(self, force:Forced = Forced.no) -> bool:
        return False
    async def process_sb(self, data: bytes) -> None:
        pass

class SilentHalfOption(HalfOption):
    def __init__(self, opt, local:bool):
        super().__init__(opt,local)
        self.state = False

    def reset(self):
        super().reset()
        self.state = False

    async def process_yes(self) -> None:
        pass
    async def process_no(self) -> None:
        pass


class BaseTestClient(Test_Opt, BaseClient):
    def __init__(self, conn, term=None, cols=None, rows=None, tspeed=None, xdisploc=None, **kw):
        super().__init__(conn, **kw)


class Client(Test_Opt, TelnetClient):
    pass

@pytest.fixture(params=['127.0.0.1'])
def server(bind_host, unused_tcp_port):
    @contextlib.asynccontextmanager
    async def mgr(**kw):
        async with anyio.create_task_group() as tg:
            evt = anyio.Event()
            tg.start_soon(partial(server_loop,evt=evt,host=bind_host,port=unused_tcp_port, **kw))
            await evt.wait()
            yield unused_tcp_port
            tg.cancel_scope.cancel()
    return mgr


__all__ = ('BaseTestClient', 'Server', 'shell')
