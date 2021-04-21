"""
Option handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from weakref import ref, ReferenceType
import anyio
from typing import Optional
from .. import stream

from ..telopt import Cmd, WILL,WONT,DO,DONT,SB, Opt


class Forced(IntEnum):
    no = 0
    yes = 1
    repeat = 2


class _BaseSpecializer(type):
    # This metaclass creates a value-specialized BaseOption (or any subclass)
    # by attributing it with the option name.

    def __getattr__(cls, key):
        try:
            value_ = Opt[key]
        except KeyError:
            raise AttributeError(key)
        if cls.value is not None:
            raise RuntimeError("you cannot re-specialize an option")

        class cls_(cls):
            value = value_
        cls_.__name__ = f"{cls.__name__}.{key}"
        return cls_

class BaseOption(metaclass=_BaseSpecializer):
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
            self.value = Opt(value)
            self.name = self.value.name
        elif value is not None:
            raise RuntimeError("You cannot override the option value")
        elif not isinstance(self.value,Opt):
            raise RuntimeError(f"Use 'value=Opt(num)', not {self.value}")
        self._setup_half()

    def _setup_half(self):
        # factored out so we can override it, esp for testing
        self.loc = HalfOption(self, True)
        self.rem = HalfOption(self, False)

    async def setup(self, tg):
        """
        Setup. *Must* add to this taskgroup instead of blocking.
        """
        pass

    def __repr__(self):
        return "%s:%r/%r" % (self.__class__.__name__, self.loc, self.rem)
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


    async def process_will(self) -> None:
        await self.rem.process_yes()

    async def process_wont(self) -> None:
        await self.rem.process_no()

    async def process_do(self) -> None:
        await self.loc.process_yes()

    async def process_dont(self) -> None:
        await self.loc.process_no()

    async def process_sb(self, data: bytes) -> None:
        """
        Incoming subnegotiation message.

        The default is to turn the option off, in both directions.
        """
        s = self._stream()
        s.log.warning("Subneg for %s not implemented: %r", self.value, data)
        self.disable()

    def teardown(self):
        self.loc.teardown()
        self.rem.teardown()

    @property
    def idle(self):
        """
        Flag whether this option has ever done anything
        """
        return self.loc.idle and self.rem.idle

    async def disable(self):
        """
        Call if the option is broken.
        """
        await self.loc.disable()
        await self.rem.disable()

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

    def teardown(self):
        if self.waiting:
            self.broken = True
            self.waiting.set()
            self.waiting = None

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
        if (self.broken or self.state is not None) and force < Forced.yes:
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
        if (self.broken or self.state is not None) and force < Forced.yes:
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
            self.waiting.set()
            self.waiting = None

            if self.state is False:
                # state is now False: we need to reject
                await opt._send(WONT if self._local else DONT)
            else:
                self.state = True
                self.broken = False
                await self.reply_yes()
        else:
            # Message was not solicited: send reply if changing state
            if self.broken:
                # unsolicited message in broken state. Reject.
                await opt._send(WONT if self._local else DONT)
                return
            if self.state is True:
                return
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
            self.state = False
            self.broken = False
            self.waiting.set()
            self.waiting = None
            await self.reply_no()
            return

        # Message was not solicited: send reply if changing state
        else:
            if self.broken:
                return
            if self.state is False:
                return
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
            opt = self._opt()
            s = opt.stream
            s.log.debug("WAIT %r",opt)
            await self.waiting.wait()
            s.log.debug("WAIT DONE %r",opt)
        if self.broken:
            opt = self._opt()
            raise RuntimeError("State exchange failed: %r" % (opt,))
        if not isinstance(self.state,bool):
            opt = self._opt()
            raise RuntimeError("State is not set: %r" % (opt,))
        return self.state

    async def disable(self):
        """
        Disable this option.

        May not return to working state from the remote side.
        """
        self.broken = True
        if self.waiting:
            self.waiting.set()
            self.waiting = None
        opt = self._opt()
        await opt._send(WONT if self._local else DONT)





# Usage:
# stream.opt.TTYPE
#  (instantiates+)returns the TTYPE option on this stream

