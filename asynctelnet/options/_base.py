"""
Option handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from weakref import ref, ReferenceType
import anyio
from typing import Optional

from ..telopt import Cmd, WILL,WONT,DO,DONT,SB


class Forced(IntEnum):
    no = 0
    yes = 1
    repeat = 2

class _OptRegBase:
    def __init__(self):
        self.name2opt = {}
        self.value2opt = {}

    def __call__(self, num):
        num = getattr(num,"value",num)
        return self.value2opt[num]

    def __getitem__(self, name):
        return self.name2opt[name]

    def __getattr__(self, name):
        try:
            return self.name2opt[name]
        except KeyError:
            raise AttributeError(name) from None

    @property
    def options(self):
        return self.value2opt.values()

    def register(self, opt):
        if opt.name in self.name2opt:
            raise RuntimeError(f"Option {opt.name} already exists")
        if opt.value in self.value2opt:
            raise RuntimeError(f"Option {opt.value} already exists")
        self.value2opt[opt.value] = opt
        self.name2opt[opt.name] = opt
        return opt

class _OptRegHandler(_OptRegBase):
    """
    Registration for option handlers

    Lookup by name is via attribute or indexing, lookup by value via function call.
    """
    def register(self, opt):
        if not isinstance(opt, type) or not issubclass(opt, BaseOption):
            raise RuntimeError("You register option classes")
        super().register(opt)

class _Option(int):
    """
    Internal class to hold options.
    """
    def __new__(cls, name, value, *x):
        obj = int.__new__(cls, value)
        obj.value = value
        obj.name = name
        return obj

    def __repr__(self):
        return f"{self.name}:{self.value}"


class _OptRegName(_OptRegBase):
    """
    Registration for option names/values

    Lookup by name is via indexing, lookup by value via function call.
    """
    def register(self, value, name):
        opt = _Option(value=value, name=name)
        super().register(opt)
        return opt
        
# registry for options
Opt = _OptRegName()

# registries for option handlers
OptH = _OptRegHandler()

class _reg(type):
    """
    Metaclass that registers an option name and a corresponding default handler.
    """
    def __new__(metacls, name, bases, classdict, **kwds):
        cls = super().__new__(metacls, name, bases, classdict, **kwds)
        if cls.value is not None:
            if cls.name is None:
                cls.name = name
            try:
                Opt(cls.value)
            except KeyError:
                Opt.register(cls.value, cls.name)
            try:
                OptH(cls.value)
            except KeyError:
                OptH.register(cls)
        return cls

class BaseOption(metaclass=_reg):
    """
    Handle some option.
    """
    value = None
    name = None

    def __init__(self, stream, value=None):
        self._stream = ref(stream)

        if self.value is None:
            if value is None:
                raise RuntimeError("You need to set the option value")
            self.value = getattr(value,'value',value)
        elif value is not None:
            raise RuntimeError("You cannot override the option value")
        self._setup_half()

    def _setup_half(self):
        # factored out so we can override it, esp for testing
        self.loc = HalfOption(self, True)
        self.rem = HalfOption(self, False)

    def __repr__(self):
        return "%s:%s:%r/%r" % (self.__class__.__name__,Opt(self.value).value, self.loc, self.rem)
    __str__=__repr__


    @property
    def stream(self):
        return self._stream()


    def reset(self):
        self.loc.reset()
        self.rem.reset()

    # Call this when you want to change an option.

    async def set_local(self, value:bool = None, force:Forced = Forced.no) -> bool:
        if value is None:
            return self.has_local
        if value:
            return await self.send_will(force)
        else:
            await self.send_wont(force)
            return False

    async def set_remote(self, value:bool = None, force:Forced = Forced.no) -> bool:
        if value is None:
            return self.has_remote
        if value:
            return await self.send_do(force)
        else:
            await self.send_dont(force)
            return False


    async def send_do(self, force:Forced = Forced.no) -> bool:
        """Send a DO if required.

        Set ``force`` if you want to override the current state.

        Returns the current state.
        """
        return await self.rem.set_state(True, force)

    async def send_dont(self, force:Forced = Forced.no):
        """Send a DONT if required.
        """
        await self.rem.set_state(False, force)

    async def send_will(self, force:Forced = Forced.no) -> bool:
        """Send a WILL if required.

        Set ``force`` if you want to override the current state.

        Returns the current state.
        """
        return await self.loc.set_state(True, force)

    async def send_wont(self, force:Forced = Forced.no):
        """Send a WONT if required.
        """
        await self.loc.set_state(False, force)

    async def send_sb(self, **kw):
        """
        Initiate a subnegotiation.

        Parameters may be option specific.
        """
        s = self._stream()
        s.log.warning("Subneg for %s not implemented", self.value)

    async def _send(self, cmd:Cmd, *bufs):
        """
        Send a IAC sequence
        """
        await self._stream().send_iac(cmd, self.value, *bufs)


    @property
    def has_local(self):
        if self.loc.broken:
            raise TimeoutError("local option: broken")
        if self.loc.waiting:
            raise RuntimeError("local option: waiting")
        return self.loc.state

    @property
    def has_remote(self):
        if self.rem.broken:
            raise TimeoutError("remote option: broken")
        if self.rem.waiting:
            raise RuntimeError("remote option: waiting")
        return self.rem.state


    # Callback from the Half Option when the remote side confirms an option.
    # Override this if you want to do something when that happens.

    async def reply_do(self) -> bool:
        """Incoming DO.

        Return a flag whether the option should be accepted.
        The default is ``True``.
        """
        return True

    async def reply_will(self) -> bool:
        """Incoming WILL.

        Return a flag whether the option should be accepted.
        The default is ``True``.
        """
        return True

    async def reply_dont(self):
        """Incoming DONT.

        No return value.
        """
        pass

    async def reply_wont(self):
        """Incoming WONT.

        No return value.
        """
        pass


    # Callback from the Half Option when the remote side wants an option.
    # Override this if you want to accept this option and/or do something
    # when it is set.

    async def handle_do(self) -> bool:
        """Incoming DO.

        Return a flag whether the option should be accepted.
        The default is ``False``.
        """
        return False

    async def handle_will(self) -> bool:
        """Incoming WILL.

        Return a flag whether the option should be accepted.
        The default is ``False``.
        """
        return False

    async def handle_dont(self):
        """Incoming DONT.

        No return value.
        """
        pass

    async def handle_wont(self):
        """Incoming WONT.

        No return value.
        """
        pass

    # Callback after the remote side wanted an option and the ACK reply has
    # been sent.
    # Override this for post-processing.

    async def after_handle_do(self) -> None:
        """Post-process incoming DO.
        """
        pass

    async def after_handle_will(self) -> None:
        """Post-process incoming WILL.
        """
        pass


    async def process_sb(self, data: bytes) -> None:
        """
        Incoming subnegotiation message.

        The default is to turn the option off, in both directions.
        """
        s = self._stream()
        s.log.warning("Subneg for %s not implemented: %r", self.value, data)
        s.start_soon(self.send_dont, Forced.yes)
        s.start_soon(self.send_wont, Forced.yes)


class HalfOption:
    """
    This class handles sending WILL and receiving DO (if local),
    or vice versa (if not).
    """
    # our Option
    _opt:ReferenceType[BaseOption] = None

    # current state
    state:bool = None

    # We sent a request and are waiting for a reply
    waiting:anyio.Event = None

    # waiting for an event has been aborted (canceled)
    broken:bool = False

    # set when instantiating
    _local:bool = None

    def __init__(self, opt, local:bool):
        self._opt = ref(opt)
        self._local = local

    def __repr__(self):
        s = "!" if self.broken else "?" if self.state is None else "+" if self.state else "-"
        if self.waiting:
            s += "w"
        return s

    @property
    def idle(self):
        """
        Flag whether this option has ever done anything
        """
        if self.state is not None:
            return False
        if self.waiting or self.broken:
            return False
        return True

    def reset(self):
        self.state = None
        self.broken = False
        if self.waiting:
            self.waiting.set()
            self.waiting = None

    async def handle_yes(self) -> Optional[bool]:
        """
        Enable this option (we get an unsolicited DO / WILL).
        Called only if the local state changes.

        Forwards to handle_do / handle_will.
        """
        opt = self._opt()
        return await (opt.handle_do if self._local else opt.handle_will)()

    async def handle_no(self) -> None:
        """
        Disable this option (we get an unsolicited DONT / WONT).

        Forwards to handle_dont / handle_wont.
        """
        opt = self._opt()
        return await (opt.handle_dont if self._local else opt.handle_wont)()


    async def after_handle_yes(self) -> Optional[bool]:
        """
        Enable this option (we get an unsolicited DO / WILL).
        Called only if the local state changes.

        Forwards to handle_do / handle_will.
        """
        opt = self._opt()
        return await (opt.after_handle_do if self._local else opt.after_handle_will)()


    async def reply_yes(self) -> Optional[bool]:
        """
        Enable this option (we get a solicited DO / WILL).

        Forwards to reply_do / reply_will.
        """
        opt = self._opt()
        return await (opt.reply_do if self._local else opt.reply_will)()

    async def reply_no(self) -> None:
        """
        Disable this option (we get a solicited DONT / WONT).

        Forwards to reply_dont / reply_wont.
        """
        opt = self._opt()
        await (opt.reply_dont if self._local else opt.reply_wont)()


    async def send_yes(self, force:Forced = Forced.no) -> None:
        """
        Send a WILL / DO.
        """
        while self.waiting:
            await self.waiting.wait()
        if self.state is True and force < Forced.repeat:
            return
        if self.state is not None and force < Forced.yes:
            return

        if not self.broken:
            self.waiting = anyio.Event()
        opt = self._opt()
        await opt._send(WILL if self._local else DO)

    async def send_no(self, force:Forced = Forced.no) -> None:
        """
        Send a WONT / DONT.
        """
        while self.waiting:
            await self.waiting.wait()
        if self.state is False and force < Forced.repeat:
            return
        if self.state is not None and force < Forced.yes:
            return

        if not self.broken:
            self.waiting = anyio.Event()
        opt = self._opt()
        await opt._send(WONT if self._local else DONT)


    async def process_yes(self) -> None:
        """
        Handle an incoming DO / WILL.
        """
        opt = self._opt()

        if self.waiting:  # message was solicited
            try:
                res = await self.reply_yes()
                if self.state is not False:
                    if res is not False:
                        self.state = True
                        return None
                    self.state = False
                # state is False: we need to reject
                await opt._send(WONT if self._local else DONT)
                return
            except BaseException:
                with anyio.move_on_after(2, shield=True):
                    await opt._send(WONT if self._local else DONT)
                raise
            finally:
                self.waiting.set()
                self.waiting = None

        # Message was not solicited: send reply if changing state
        if self.state is not True:
            res = await self.handle_yes()
            if res is False:
                self.state = False
                await opt._send(WONT if self._local else DONT)
                return
            self.state = True
            await opt._send(WILL if self._local else DO)
            await self.after_handle_yes()


    async def process_no(self) -> None:
        """
        Handle an incoming DONT / WONT.
        """
        opt = self._opt()

        if self.waiting:  # message was solicited
            await self.reply_no()
            self.state = False
            self.waiting.set()
            self.waiting = None
            return

        # Message was not solicited: send reply if changing state
        if self.state is not False:
            self.state = False
            await self.handle_no()
            await opt._send(WONT if self._local else DONT)


    # High level interface

    async def set_state(self, state:bool, force:Forced = Forced.no) -> bool:
        """
        (Tries to) set the current state to this.

        Returns the current state, i.e. always False if state is False.
        """
        await (self.send_yes if state else self.send_no)(force=force)
        try:
            res = await self.get_state()
        except BaseException:
            self.broken = True
            if self.waiting:
                self.waiting.set()
                self.waiting = None
            raise
        else:
            self.broken = False
            return res

    async def get_state(self) -> bool:
        """
        Returns the current state.

        Raises an error if the last `set_state` has been interrupted.
        """
        if self.waiting:
            await self.waiting.wait()
        if self.broken:
            raise RuntimeError("State exchange failed")
        if not isinstance(self.state,bool):
            raise RuntimeError("State is not set")
        return self.state





# Usage:
# stream.opt.TTYPE
#  (instantiates+)returns the TTYPE option on this stream

