"""Module provides :class:`TelnetWriter` and :class:`TelnetWriterUnicode`."""
# std imports
import anyio
import collections
import logging
import struct
import sys
import codecs
import inspect
from enum import Enum, IntEnum
from typing import Optional,Union,Iterator,Tuple,Mapping
from contextlib import asynccontextmanager
from functools import partial
from dataclasses import dataclass
from collections import defaultdict

# local imports
from . import slc
from .telopt import (Cmd, Opt,
                     ABORT, ACCEPTED, AO, AYT, BINARY, BRK, CHARSET, CMD_EOR,
                     DM, DO, DONT, EC, ECHO, EL, EOF, EOR, ESC, GA, IAC, INFO,
                     IP, IS, LFLOW, LFLOW_OFF, LFLOW_ON, LFLOW_RESTART_ANY,
                     LFLOW_RESTART_XON, LINEMODE, LOGOUT, NAWS, NEW_ENVIRON,
                     NOP, REJECTED, REQUEST, SB, SE, SEND, SGA, SNDLOC, STATUS,
                     SUSP, TM, TSPEED, TTABLE_ACK, TTABLE_NAK, TTABLE_IS,
                     TTABLE_REJECTED, TTYPE, USERVAR, VALUE, VAR, WILL, WONT,
                     XDISPLOC, name_command, name_commands, SubVar, Req)

from .accessories import CtxObj, spawn, ValueEvent, AttrDict

# list of IAC commands needing 3+ bytes
_iac_multibyte = {DO, DONT, WILL, WONT, SB}

class OptionTimeoutError(TimeoutError):
    def __init__(self, value):
        self.value = value

class TS(Enum):
    DATA="data"  # normal data flow
    IAC="iac"  # IAC
    OPT="opt"  # IAC+multibyte (cmd in _iac_multibyte)
    SUBNEG="subneg"  # IAC+SB+OPT
    SUBIAC="subiac"  # IAC+SB+OPT+…+IAC


__all__ = ('BaseTelnetStream','ReadCallback','TelnetStream', 'EchoAttr',
        'InProgressError', 'RecvMessage', 'SetCharset')

EchoAttr = anyio.typed_attribute()

CR, LF, NUL = b'\r\n\x00'
bIAC = bytes([IAC])


class InProgressError(RuntimeError):
    """Negotiation in progress"""
    pass

class ReadCallback:
    """
    This class syncs the read loop so that a mode-changing message is
    processed without eating any bytes following it.

    Note that this only works reliably when entering a mode (compression,
    encryption, charset). Unstacking (e.g. turning compression off) is
    likely to lose some data if the sender is not extra careful.

    A ReadCallback instance is started by calling
    `BaseTelnetStream.queue_read_callback`.
    """
    prev = None

    def __init__(self):
        self.evt = anyio.Event()

    async def wait(self):
        await self.evt.wait()

    async def _run(self):
        if self.prev is not None:
            await self.prev._run()
        return await self.run()

    async def _set(self):
        if self.prev is not None:
            self.prev._set()
        self.evt.set()

    async def __call__(self):
        try:
            return await self._run()
        finally:
            await self._set()

    async def run(self):
        raise NotImplementedError("You need to actually do something!")

    def __repr__(self):
        if self.prev:
            return f"RCB:{self.__class__.__name__}>{self.prev !r}"
        else:
            return f"RCB:{self.__class__.__name__}"

class RecvMessage:
    """
    Instances of this class may be returned by `ReadCallback.run`. They
    will be inserted in the stream emitted by ``receive`` and ``readline``
    methods.
    """
    pass

@dataclass
class SetCharset(RecvMessage):
    charset: str

class NullDecoder:
    @staticmethod
    def decode(x):
        return x

class NullEncoder:
    @staticmethod
    def __call__(x):
        if isinstance(x,str):
            x = x.encode("utf-8")
        return x

class BaseTelnetStream(CtxObj, anyio.abc.ByteSendStream):
    """
    Basic TELNET protocol handler.

    Magic methods:
        handle_iac_cmd(): Handler for IAC CMD
        handle_subneg_opt(data): Handler for IAC SB OPT data… IAC SE
        handle_do_opt(): Handler for DO OPT
        handle_dont_opt(): Handler for DONT OPT
        handle_will_opt(): Handler for WILL OPT
        handle_wont_opt(): Handler for WONT OPT
        handle_opt(DO/DONT/WILL/WONT): Fallback handler for IAC DO/DONT/WILL/WONT OPT
        handle_do(OPT): Default handler for IAC DO OPT
        handle_dont(OPT): Default handler for IAC DONT OPT
        handle_will(OPT): Default handler for IAC WILL OPT
        handle_wont(OPT): Default handler for IAC WONT OPT
    """
    #: Whether flow control enabled by Transmit-Off (XOFF) (Ctrl-s), should
    #: re-enable Transmit-On (XON) only on receipt of XON (Ctrl-q).  When
    #: False, any keypress from client re-enables transmission.
    xon_any = False

    # Used in CRLF cleanup for the receiver
    _last_input = ""

    # Used in receiver buffer
    _buffer = b''
    _read_callback = None

    _decoder = NullDecoder()
    _encoder = NullEncoder()
    _charset = None
    _charset_lock = None
    _charset_retry = False
    _charsets_wanted = None

    _did_binary = False

    # Storage for extra attributes. Used by client and server
    # so no duplicate code please.
    extra: AttrDict = None

    def __init__(self, stream: anyio.abc.ByteStream, *,
            log=None, force_binary=False, encoding=None,
            encoding_errors="replace", client=False, server=False):
        """
        A wrapper for the telnet protocol. Telnet IAC Interpreter.

        :param logging.Logger log: target logger, if None is given, one is
            created using the namespace ``'asynctelnet.stream'``.
        :param bool force_binary: When ``True``, the encoding specified is used for
            both directions even when failing ``BINARY`` negotiation, :rfc:`856`.

        You *must* call ``await this.reset`` after initialization.
        """
        self._stream = stream
        self._orig_stream = stream
        self.log = log or logging.getLogger(__name__)
        self.force_binary = force_binary

        self.extra = AttrDict()

        if client == server:
            raise TypeError("You must set either `client` or `server`.")
        self._server = server

        #_ receiver callbacks/queues for subnegotiation messages
        self._subneg_recv = {}

        #_ receiver callbacks/queues for IAC messages
        self._iac_callback = {}

        # write lock
        self._write_lock = anyio.Lock()

        # handler registry
        self._handler = {}

        # Locks for preventing concurrent subnegotiations
        self._subneg_lock = defaultdict(anyio.Lock)

        self._charset = encoding
        self._charset_errors = encoding_errors
        self._use_current_charset = bool(encoding)

        self._set_charset_encoder(encoding)
        self._set_charset_decoder(encoding)

    @property
    def extra_attributes(self):
        """
        Attach our extra attrs to anyio's extra_attributes mechanism.

        This isn't really nice since anyio's attrs are singletons, not
        strings. TODO.
        """
        res = self._stream.extra_attributes
        res[EchoAttr] = lambda: self.echo

        for k in self.extra.keys():
            def fn(k):
                return lambda: self.extra[k] 
            res[k] = fn(k)
        return res

        return res

    # Public methods for notifying about, or soliciting state options.
    #
    @property
    def server(self):
        """Whether this stream is from the server's point of view."""
        return bool(self._server)

    @property
    def client(self):
        """Whether this stream is from the client's point of view."""
        return bool(not self._server)


    def set_command_handler(self,cmd:Cmd,opt:Opt,callback):
        if (cmd,opt) in self._handler:
            ofn = self._handler[(cmd,opt)]
            self.log.warning("Command for %s/%s was %r, replaced with %r" % (cmd.name,opt.name, ofn,callback))

        self._handler[(cmd,opt)] = callback

    async def reset(self):
        #: Dictionary of telnet option byte(s) that follow an
        #: IAC-WILL or IAC-WONT command, sent by our end,
        #: indicating state of local capabilities.
        self._local_option = {}

        #: Dictionary of telnet option byte(s) that follow an
        #: IAC-WILL or IAC-WONT command received by remote end,
        #: indicating state of remote capabilities.
        self._remote_option = {}

        #: Sub-negotiation buffer
        self._recv_sb_buffer = bytearray()

        # receiver state
        self._recv_state = TS.DATA

        # cancel option receivers
        for sb_w in list(self._subneg_recv.values()):
            await sb_w.aclose()
        self._subneg_recv = {}

    def push_stream(self, factory):
        """
        Push a stream onto our codec stack. Examples: compression,
        encryption, …
        """
        s = factory(self._stream)
        s.__orig_stream = s
        self._stream = s

    def pop_stream(self, factory):
        """
        Pop the newest stream modifier off our codec stack.
        WARNING: this does nothing about closing the modifier.
        """
        s = self._stream.__orig_stream
        self._stream = s

    async def _send_opt(self, option: int, value:Optional[bool], force: bool, opts:dict, yes_opt:int, no_opt:int):
        # self.log.debug("%s:%s %s %s","LOC" if opts is self._local_options else "REM", option,value,force)

        val = opts.get(option, None)
        if type(val) is OptionTimeoutError:
            if force:
                val = None
            else:
                raise val
        if value is not None and isinstance(val, anyio.abc.Event):
            raise InProgressError(DO,option)
        if (val is value or value is None) and not force:
            return value
        if value is not None:
            if val is value and (force is None or (force is False and val)):
                return value
            try:
                evt = anyio.Event()
                opts[option] = (evt, value)
                await self.send_iac(yes_opt if value else no_opt, option)
                await evt.wait()
                while isinstance(val := opts.get(option), tuple):
                    await val[0].wait()
            finally:
                if isinstance(val := opts.get(option), tuple):
                    val[0].set()
                    opts[option] = OptionTimeoutError(val[1])
        return val

    async def local_option(self, option: int, value:Optional[bool]=None, force: bool = False):
        return await self._send_opt(option,value,force, self._local_option,WILL,WONT)

    async def remote_option(self, option: int, value:Optional[bool]=None, force: Optional[bool] = False):
        return await self._send_opt(option,value,force, self._remote_option,DO,DONT)

    def local_status(self, option:int):
        """
        Get out option, i.e. return True if we got DO.
        """
        val = self._local_option.get(option, None)
        if type(val) is OptionTimeoutError:
            raise val
        if isinstance(val, anyio.abc.Event):
            raise InProgressError(DO, option)
        return val

    def remote_status(self, option:int):
        """
        Get their option, i.e. return True if we got WILL.
        """
        val = self._remote_option.get(option, None)
        if type(val) is OptionTimeoutError:
            raise val
        if isinstance(val, anyio.abc.Event):
            raise InProgressError(WILL, option)
        return val


    @asynccontextmanager
    async def _ctx(self):
        # Main context handler. Called by our CtxObj mix-in.

        await self.reset()

        async with anyio.create_task_group() as tg:
            self._tg = tg
            self._write_queue, self._read_queue = anyio.create_memory_object_stream(100)
            tg.spawn(self._receive_loop)

            try:
                self.log.debug("Start setup")
                await self.setup()
                self.log.debug("Finished setup")
                yield self
            finally:
                del self.extra
                del self.options
                self.log.debug("Start teardown")
                died = True
                with anyio.move_on_after(2):
                    await self.teardown()
                    died = False
                self.log.debug("%s teardown", "Interrupted" if died else "Finished")
                tg.cancel_scope.cancel()

    async def setup(self):
        """
        Called when starting this connection.
        """
        if self.force_binary:
            async with anyio.create_task_group() as tg:
                tg.spawn(self.local_option,BINARY,True)
                tg.spawn(self.remote_option,BINARY,True)

    async def teardown(self):
        """
        Called when closing down this connection.

        Please try hard not to raise an exception.
        """
        for sb_w in list(self._subneg_recv.values()):
            await sb_w.aclose()

    # receiver

    def _intercept(self, data):
        pass

    async def _receive(self, max_bytes=1024) -> Union[bytes,RecvMessage]:
        buf = self._buffer
        if not buf:
            while True:
                buf = await self._read_queue.receive()
                # self.log.debug("INB:%r",buf)
                if isinstance(buf,(bytes,bytearray)):
                    break
                data = await buf()
                if isinstance(data, RecvMessage):
                    self._intercept(data)
                    return data
        buf,self._buffer = buf[:max_bytes],buf[max_bytes:]
        return buf

    async def _receive_loop(self):
        q = self._write_queue
        async with q:
            while True:
                buf = bytearray()
                try:
                    b = await self._stream.receive(4096)
                except (anyio.EndOfStream, anyio.ClosedResourceError, anyio.BrokenResourceError):
                    # self.log.debug("IN: EOF")
                    return
                # self.log.debug("IN: DATA: %r", b)

                if self._recv_state == TS.DATA and IAC not in b:
                    # Speed up: no IAC anywhere to be seen
                    await q.send(b)
                    continue

                for x in b:
                    res = await self.feed_byte(x)
                    if res is True:
                        buf.append(x)
                    if self._read_callback is not None:
                        cb,self._read_callback = self._read_callback,None
                        # self.log.debug("RCB %r %r",cb,buf)
                        if buf:
                            # self.log.debug("IN: Q1: %r", buf)
                            await q.send(buf)
                            buf = bytearray()
                        # self.log.debug("IN: Q3: %r", cb)
                        await q.send(cb)
                        await cb.wait()
                if buf:
                    # self.log.debug("IN: Q2: %r", buf)
                    await q.send(buf)

    def queue_read_callback(self, callback: ReadCallback):
        """
        Queue a read callback.

        The callback is processed when `feed_byte` returns.
        """
        if self._read_callback is not None:
            self.log.warning("Queueing %r while %r is waiting", callback, self._read_callback)
            callback.prev = self._read_callback
        self._read_callback = callback

    async def queue_recv_message(self, msg: RecvMessage):
        """
        Queue a read callback that simply emits a RecvMessage.
        """
        class MQ(ReadCallback):
            def __init__(self, msg:str):
                self.msg = msg
                super().__init__()
            async def run(self):
                return msg
        await self._write_queue.send(MQ(msg))

    async def read_exactly(self, n_bytes) -> Union[bytes,RecvMessage]:
        """
        Read exactly N bytes.

        Mainly used for testing.
        """
        buf = bytearray()
        while len(buf) < n_bytes:
            chunk = await self._receive(n_bytes - len(buf))
            if not isinstance(chunk, (bytes,bytearray)):
                return chunk
            buf += chunk
        return buf


    # string methods, if a decoder is set

    async def receive(self, max_bytes=4096) -> Union[str,bytes,RecvMessage]:
        while True:
            chunk = await self._receive(max_bytes)
            if isinstance(chunk, SetCharset):
                self._set_charset_decoder(chunk.charset)
                continue

            if not isinstance(chunk, (bytes,bytearray)):
                return chunk
            if self._decoder is None:
                return chunk
            decoded = self._decoder.decode(chunk)
            if decoded:
                return decoded

    async def readline(self) -> Union[str,RecvMessage]:
        """
        Read one line, decoding as appropriate.
        """
        while True:
            chunk = await self._readline()
            if isinstance(chunk, SetCharset):
                self._set_charset_decoder(chunk.charset)
                continue
            if isinstance(chunk, RecvMessage):
                return chunk
            if self._decoder is None:
                return chunk
            decoded = self._decoder.decode(chunk)
            if decoded:
                return decoded


    async def _readline(self) -> bytes:
        r"""
        Read one line.

        A "line" is a sequence of characters ending with CR LF, LF,
        or CR NUL. This readline function is a strict interpretation of
        Telnet Protocol :rfc:`854`.

          The sequence "CR LF" must be treated as a single "new line" character
          and used whenever their combined action is intended; The sequence "CR
          NUL" must be used where a carriage return alone is actually desired;
          and the CR character must be avoided in other contexts.

        And therefor, a line does not yield for a stream containing a
        CR if it is not succeeded by NUL or LF.

        ================= =====================
        Given stream      readline() yields
        ================= =====================
        ``--\r\x00---``   ``--\r``, ``---`` *...*
        ``--\r\n---``     ``--\r\n``, ``---`` *...*
        ``--\n---``       ``--\n``, ``---`` *...*
        ``--\r---``       ``--\r``, ``---`` *...*
        ================= =====================

        If EOF is received before the termination of a line, the method will
        yield the partially read string.

        """

        buf,self._buffer = self._buffer,b''
        res = bytearray()

        while True:
            if buf == b"":
                buf = await self._receive()
                if isinstance(buf, RecvMessage):
                    self._buffer = res+self._buffer
                    return buf
            for i,inp in enumerate(buf):
                if inp in (LF, NUL) and self._last_input == CR:
                    self._buffer = buf[i+1:]+self._buffer
                    return res
                
                elif inp in (CR, LF):
                    # first CR or LF yields res
                    self._buffer = buf[i+1:]+self._buffer
                    await self.echo(res)
                    await self.echo(bytes((CR,LF)))
                    # TODO configure CRLF style
                    return res
                
                elif inp in (ord(b'\b'), 0x7f):
                    # backspace over input
                    if res:
                        res = res[:-1]  
                        await self.send(b'\b \b')
                
                else:
                    # buffer and echo input
                    res.append(inp)
                    self._last_input = inp
            buf = b''

    async def _writeline(self, line: bytes):
        line += bytes((CR,LF))
        await self.send(line)

    async def writeline(self, line: str):
        await self._writeline(self._encoder(line))

    async def handle_do_binary(self):
        return True

    async def handle_dont_binary(self):
        return self.force_binary

    async def handle_will_binary(self):
        return True

    async def handle_wont_binary(self):
        if seld._did_binary:
            return False
        self._did_binary = True
        return self.force_binary

# public derivable methods DO, DONT, WILL, and WONT negotiation
#
    async def handle_do(self, opt):
        """
        Process byte 3 of series (IAC, DO, opt) received by remote end.
        """
        return False

    async def handle_dont(self, opt):
        """
        Process byte 3 of series (IAC, DONT, opt) received by remote end.
        """
        return False

    async def handle_will(self, opt):
        """
        Process byte 3 of series (IAC, WILL, opt) received by remote end.
        """
        return False

    async def handle_wont(self, opt):
        """
        Process byte 3 of series (IAC, WONT, opt) received by remote end.
        """
        return False

# public derivable Sub-Negotation parsing
#
    async def handle_subneg(self, opt, buf):
        """
        Callback for end of sub-negotiation buffer.

        :param bytes buffer: Message buffer. Byte 0 is the command.
        """
        opt = Opt(opt)
        hdl = self._subneg_recv.get(opt, None)
        if hdl is None:
            hdl = getattr(self,'handle_subneg_'+opt.name.lower(), None)
        if hdl is not None:
            await hdl(buf)
            return
        self.log.error('SB unhandled: opt=%d, buf=%r', opt.name, buf)

    handle_subnegotiation = handle_subneg


    async def send(self, buf, *, escape_iac=True, locked = False):
        """
        Write bytes to transport, conditionally escaping IAC.

        :param bytes buf: bytes to write to transport.
        :param bool escape_iac: whether bytes in buffer ``buf`` should be
            escape bytes ``IAC``.  This should be set ``False`` for direct
            writes of ``IAC`` commands.
        :param bool locked: The write lock has already been acquired.
        """
        if isinstance(buf, str):
            if not escape_iac:
                raise ValueError("Raw sending is only possible for bytes")
            buf = self._encoder(buf)

        if escape_iac:
            # when escape_iac is True, we may safely assume downstream
            # application has provided an encoded string.  If force_binary
            # is unset, we enforce strict adherence of BINARY protocol
            # negotiation.
            if not self.force_binary and not self.outbinary:
                # check each byte position by index to report location
                for position, byte in enumerate(buf):
                    if byte >= 128:
                        raise TypeError(
                            f'Byte value {byte!r} at index {position} not valid, '
                            'send IAC WILL BINARY first: buf={buf!r}')
            buf = self._escape_iac(buf)

        if locked:
            assert self._write_lock.is_locked()
            await self._stream.send(buf)
        else:
            async with self._write_lock:
                await self._stream.send(buf)

    # Our Private API methods

    @staticmethod
    def _escape_iac(buf):
        r"""Replace bytes in buf ``IAC`` (``b'\xff'``) by ``IAC IAC``."""
        return buf.replace(bIAC, bIAC + bIAC)


    # Base protocol methods

    async def aclose(self):
        await self._stream.aclose()
        # break circular refs
        self._ext_callback.clear()
        self._ext_send_callback.clear()
        self._slc_callback.clear()
        self._iac_callback.clear()

    def _repr(self):
        info = []
        if self._local_option:

            info.append('local:')
            for k,v in self._local_option.items():
                c = '-+'[v] if isinstance(v,bool) else '!'+'-+'[v.value] if type(v) is OptionTimeoutError else '?'
            info.append(c+str(k).rsplit(".")[-1])

        if self._remote_option:
            info.append('remote:')
            for k,v in self._remote_option.items():
                c = '-+'[v] if isinstance(v,bool) else '!'+'-+'[v.value] if type(v) is OptionTimeoutError else '?'
            info.append(c+str(k).rsplit(".")[-1])

        if self.extra:
            info.append('extra:')
            for k,v in self.extra.items():
                info.append(f"{k}={v !r}")

        return info

    def __repr__(self):
        """Description of stream encoding state."""
        return '<%s: %s>' % (self.__class__.__name__, ' '.join(self._repr()))

    async def feed_byte(self, byte) -> bool:
        """
        Feed a single byte into Telnet option state machine.

        :param int byte: an 8-bit byte value as integer (0-255), or
            a bytes array.  When a bytes array, it must be of length
            1.

        :rtype bool: Whether the given ``byte`` is "in band", that is, should
            be duplicated to a connected terminal or device.  ``False`` is
            returned for an ``IAC`` command for each byte until its completion.
        """
        if self._recv_state == TS.DATA:
            if byte == IAC:
                self._recv_state = TS.IAC
                return False
            else:
                return True

        elif self._recv_state == TS.IAC:
            if byte == IAC:
                self._recv_state = TS.DATA
                return True
            elif byte in _iac_multibyte:
                self._recv_cmd = Cmd(byte)
                self._recv_state = TS.OPT
                return False
            else:
                try:
                    callback = self._iac_callback.get(byte,None)
                    if callback is None:
                        callback = getattr(self,'handle_iac_'+Cmd(byte).name.lower(),None)
                    if callback is None:
                        self.log.info("recv: unknown IAC+%r", byte)
                    else:
                        await callback(cmd)
                finally:
                    self._recv_state = TS.DATA
                return False

        elif self._recv_state == TS.OPT:
            if self._recv_cmd == SB:
                self._recv_cmd = Opt(byte)
                self._recv_state = TS.SUBNEG
                self._recv_sb_buffer = bytearray()
            else:
                self._recv_state = TS.DATA
                await self._recv_opt(self._recv_cmd, byte)
            return False

        elif self._recv_state == TS.SUBNEG:
            if byte == IAC:
                self._recv_state = TS.SUBIAC
            else:
                self._recv_sb_buffer.append(byte)
            return False

        elif self._recv_state == TS.SUBIAC:
            if byte == IAC:
                self._recv_sb_buffer.append(byte)
            elif byte == SE:
                self._recv_state = TS.DATA
                try:
                    await self.handle_subneg(self._recv_cmd, self._recv_sb_buffer)
                finally:
                    self._recv_sb_buffer.clear()
            else:
                # The standard says to just ignore the IAC but it's better
                # to treat this as if the sender forgot the IAC+SE.
                self.log.warning("recv: protocol error: IAC SB %s <%d> IAC %s: no IAC+SE?",
                        self._recv_cmd.name, len(self._recv_sb_buffer), name_command(byte))
                self._recv_state = TS.IAC
                try:
                    await self.handle_subneg(self._recv_cmd, self._recv_sb_buffer)
                finally:
                    self._recv_sb_buffer.clear()
                await self.flow_byte(byte)

        else:
            raise RuntimeError("Unknown Telne state %r" %
                    (self._recv_state,))

    async def _recv_opt(self,cmd,opt):
        """
        Incoming option.
        """
        opt = Opt(opt)

        # neg: negative message corresponding to "opt"
        # .... used to select the handler when ack is not possible
        # opts: dict with the option's state
        # reply: (reject,accept) command for replies
        # want: does the remote want a positive or a negative reply?
        if cmd == DO:
            opts = self._local_option
            want = True
            reply = (WONT,WILL)
            neg = DONT
        elif cmd == DONT:
            opts = self._local_option
            want = False
            reply = (WONT,WILL)
            neg = DONT
        elif cmd == WILL:
            opts = self._remote_option
            want = True
            reply = (DONT,DO)
            neg = WONT
        elif cmd == WONT:
            opts = self._remote_option
            want = False
            reply = (DONT,DO)
            neg = WONT
        else:
            raise RuntimeError("? received %r" % cmd)

        prev = opts.get(opt, None)
        waiting = True
        evt = None
        proc = None

        self.log.debug('recv IAC %s %s old:%r', Cmd(cmd).name, opt.name, prev)
        if type(prev) is OptionTimeoutError:
            # Let's assume that the timeout is healed by this message.
            prev = prev.value
        elif isinstance(prev, tuple):
            evt, prev = prev
        else:
            waiting = False

        if waiting and not prev:
            self.log.warning("Recv %s %s: we sent NO but got YES", cmd,opt)
            want = False
            cmd = neg
        handler = self._get_handler(cmd,opt)

        try:
            new = await handler()
        except BaseException:
            opts[opt] = None
            # Error. Reply with rejection.
            with anyio.move_on_after(0.5, shield=True):
                await self.send_iac(reply[0], opt)
            raise

        if inspect.iscoroutine(new):
            proc = new
            # if we got a negative request we cannot reply yes.
            # however, if the request is positive we assume that a
            # handler replying with a coroutine wants us to ack.
            new = want
        elif new is None:
            # The handler was silent, so we echo.
            new = want
        elif not isinstance(new, bool):
            raise RuntimeError("%r returned %r?", handler, new)

        opts[opt] = new

        # clean up
        if evt is not None:
            evt.set()

        if not waiting:
            # send a reply if the state changed *or* we don't accept the change
            if prev is not want or want is not new:
                await self.send_iac(reply[new], opt)
        # otherwise this is a reply, which we MUST NOT react on

        if proc is not None:
            await proc


    def _get_handler(self, cmd, opt):
        cmdn = cmd.name.lower()
        optn = opt.name.lower()

        hdl = self._handler.get((cmd,opt),None)
        if hdl is not None:
            return hdl
        hdl = getattr(self, 'handle_%s_%s'%(cmdn,optn), None)
        if hdl is not None:
            return hdl
        hdl = getattr(self, 'handle_'+optn, None)
        if hdl is not None:
            return partial(hdl,cmd)
        return partial(getattr(self,'handle_'+cmdn),opt)


    # Our protocol methods

    @property
    def inbinary(self):
        """
        Whether binary data is expected to be received on reader, :rfc:`856`.
        """
        return self._remote_option.get(BINARY)

    @property
    def outbinary(self):
        """Whether binary data may be written to the writer, :rfc:`856`."""
        return self._local_option.get(BINARY)

    async def echo(self, data:Union[bytes,str]):
        """
        Conditionally write ``data`` to transport when "remote echo" enabled.

        :param bytes data: string received as input, conditionally written.
        :rtype: None

        The default implementation depends on telnet negotiation willingness
        for local echo, only an RFC-compliant telnet client will correctly
        set or unset echo accordingly by demand.

        The input data type is `str` or `bytes` depending on whether an
        encoding has been specified.
        """
        assert self.server, ('Client never performs echo of input received.')
        if self.will_echo:
            await self.send(data=data)

    @property
    def will_echo(self):
        """
        Whether Server end is expected to echo back input sent by client.

        From server perspective: the server should echo (duplicate) client
        input back over the wire, the client is awaiting this data to indicate
        their input has been received.

        From client perspective: the server will not echo our input, we should
        chose to duplicate our input to standard out ourselves.
        """
        return (self.server and self._local_option.get(ECHO, False)) or \
               (self.client and self._remote_option.get(ECHO, False))

    @property
    def mode(self):
        """
        String describing NVT mode.

        :rtype str: One of:

            ``kludge``: Client acknowledges WILL-ECHO, WILL-SGA. character-at-
                a-time and remote line editing may be provided.

            ``local``: Default NVT half-duplex mode, client performs line
                editing and transmits only after pressing send (usually CR)

            ``remote``: Client supports advanced remote line editing, using
                mixed-mode local line buffering (optionally, echoing) until
                send, but also transmits buffer up to and including special
                line characters (SLCs).
        """
        if self._remote_option.get(LINEMODE, False):
            if self._linemode.local:
                return 'local'
            return 'remote'
        if self.server:
            if (self._local_option.get(ECHO, False) and
                    self._local_option.get(SGA, False)):
                return 'kludge'
            return 'local'
        if (self._remote_option.get(ECHO, False) and
                self._remote_option.get(SGA, False)):
            return 'kludge'
        return 'local'

    @property
    def linemode(self):
        """
        Linemode instance for stream.

        .. note:: value is meaningful after successful LINEMODE negotiation,
            otherwise does not represent the linemode state of the stream.

        Attributes of the stream's active linemode may be tested using boolean
        instance attributes, ``edit``, ``trapsig``, ``soft_tab``, ``lit_echo``,
        ``remote``, ``local``.
        """
        return self._linemode

    async def send_subneg(self, opt, *bufs):
        """
        Send a subnegotiation.
        """
        opt = Opt(opt)
        buf = self._escape_iac(b''.join(bytes([b]) if isinstance(b,int) else b
            for b in bufs))
        self.log.debug("send IAC SB %s %r",opt.name,buf)
        await self.send(bytes([IAC,SB,opt])+buf+bytes([IAC,SE]), escape_iac=False)

    async def send_iac(self, *bufs):
        """
        Send a command starting with IAC (byte value 0xFF).

        No transformations of bytes are performed.  Normally, if the
        byte value 255 is sent, it is escaped as ``IAC + IAC``.  This
        method ensures it is not escaped.

        Try not to call this to transmit DO/DONT/WILL/WONT/SB/SE.
        """
        buf = self._escape_iac(b''.join(bytes([b]) if isinstance(b,int) else b
            for b in bufs))
        if len(bufs) == 1:
            self.log.debug("send IAC %s",Cmd(bufs[0]).name)
        elif len(bufs) == 2:
            self.log.debug("send IAC %s %s",Cmd(bufs[0]).name,Opt(bufs[1]).name)
        else:
            self.log.debug("send IAC %s %s %s",Cmd(bufs[0]).name,Opt(bufs[1]).name,bufs[2:])

        assert isinstance(buf, (bytes, bytearray)), buf
        assert buf and len(buf), buf
        await self.send(bytes([IAC])+buf, escape_iac=False)

    @asynccontextmanager
    async def receive_subneg(self, opt):
        """
        Returns an iterator for subnegotiation messages for this option.
        """
        if opt in self._subneg_recv:
            raise RuntimeError("There's already a listener on %r"%(opt,))

        sb_w,sb_r = anyio.create_memory_object_stream(10)
        try:
            self._subneg_recv[opt] = sb_w.send
            yield sb_r
        finally:
            del self._subneg_recv[opt]
            await sb_w.aclose()

    receive_subnegotiation=receive_subneg


    async def read_subneg(self, opt:bytes, sender):
        """
        Returns the next message from a subnegotiation.

        :param bytes opt: the option to register for
            which can be the first one or two bytes of the subnegotiation
            block
        :param Awaitable sender:
            a coroutine that sends the actual request, to ensure that
            the reply doesn't arrive before we're ready for it
        """
        if opt in self._subneg_recv:
            raise RuntimeError("There's already a listener on %r"%(opt,))

        res = None
        evt = anyio.Event()
        async def reader(buf):
            nonlocal res
            evt.set()
            res = buf

        try:
            self._subneg_recv[opt] = reader
            if sender is not None:
                await sender
            await evt.wait()
        finally:
            del self._subneg_recv[opt]
        return res

    read_subnegotiation = read_subneg


    @staticmethod
    def _check_cmd(cmd: Cmd):
        if cmd == 240 or cmd>=250:
            raise ValueError("You can't send that as a command")
        if cmd < 240 and self._local_option.get(self._opt_for_(cmd), False) is not True:
            # Also if it's under negotiation
            raise ValueError("You may not send that, remote didn't say WILL")

    async def send_command(self, cmd:Union[bytes,int]):
        """
        Send a 1-byte command.
        """
        self._check_cmd(cmd)
        if cmd == Cmd.GA and self._local_option.get(SGA, False) is True:
            # remote doesn't want GA so don't send it
            return
            # if it's under negotiation, don't care, RFC says OK to send anyway
        await self.send_iac(cmd)


# Public methods for transmission signaling
#

    def set_iac_callback(self, cmd, func):
        """
        Register async callback ``func`` for IAC ``cmd``.

        The callback receives a single argument: the IAC ``cmd`` which
        triggered it.
        """
        assert callable(func), ('Argument func must be callable')
        cmd = self._to_cmd(cmd)

        ofn = self._iac_callback.get(cmd, None)
        if ofn is not None:
            self.log.warning("Command for %s was %r, replaced with %r" % (cmd,ofn,func))

        self._iac_callback[cmd] = func


    # send commands. Ordered by option code.

    async def send_eof(self):
        await self.send_command(Cmd.EOF)
        return True

    async def send_susp(self):
        await self.send_command(Cmd.SUSP)
        return True

    async def send_abort(self):
        await self.send_command(Cmd.ABORT)
        return True

    async def send_eor(self):
        await self.send_command(Cmd.EOR)
        return True

    async def send_nop(self):
        await self.send_command(NOP)
        return True

    async def send_dm(self):
        await self.send_command(DM)
        return True

    async def send_brk(self):
        await self.send_command(BRK)
        return True

    async def send_ip(self):
        await self.send_command(IP)
        return True

    async def send_ao(self):
        await self.send_command(AO)
        return True

    async def send_ayt(self):
        await self.send_command(AYT)
        return True

    async def send_ec(self):
        await self.send_command(EC)
        return True

    async def send_el(self):
        await self.send_command(EL)
        return True

    async def send_ga(self):
        await self.send_command(GA)
        return True


    # charset handling
    # included in basic code because necessary

    def get_supported_charsets(self):
        """
        This method lists the character sets acceptable by us.
        A request is started whenever we receive a DO from the remote side.

        :rtype list: a list of unicode character strings of US-ASCII
            characters, indicating the encodings offered by the server in
            its preferred order.

            An empty return value indicates that no encodings are offered.

        If a default encoding is set, it is returned as the sole entry
        unless it has been rejected previously.

        The default return value begins::

            ['UTF-8', 'UTF-16', 'LATIN1', 'US-ASCII', 'BIG5', 'GBK', ...]
        """
        if self._charset and self._use_current_charset:
            self._use_current_charset = False
            return [self._charset]

        return ['UTF-8', 'UTF-16', 'LATIN1', 'US-ASCII', 'BIG5',
                'GBK', 'SHIFTJIS', 'GB18030', 'KOI8-R', 'KOI8-U',
                ] + [
                    # "Part 12 was slated for Latin/Devanagari,
                    # but abandoned in 1997"
                    'ISO8859-{}'.format(iso) for iso in range(1, 16)
                    if iso != 12
                ] + ['CP{}'.format(cp) for cp in (
                    154, 437, 500, 737, 775, 850, 852, 855, 856, 857,
                    860, 861, 862, 863, 864, 865, 866, 869, 874, 875,
                    932, 949, 950, 1006, 1026, 1140, 1250, 1251, 1252,
                    1253, 1254, 1255, 1257, 1257, 1258, 1361,
                )]

    def select_charset(self, offers):
        """
        Select a charset from those offered by the other side.
        Default: use the one corresponding to the current locale.
                 If that isn't in the list, use the first for which we have
                 an incremental decoder.
        """

        # Local charset set? use that.
        if self._charset:
            loc = self._charset.lower()
            for c in offers:
                if c.lower() == loc:
                    return c

        # Local charset set? use that.
        import locale
        loc = locale.getpreferredencoding()
        if loc:
            loc = loc.lower()
            for c in offers:
                if c.lower() == loc:
                    return c

        # Otherwise use the first we can find in their list that works.
        for c in offers:
            try:
                codecs.getincrementaldecoder(c)
            except LookupError:
                continue
            else:
                self.log.info("Charsets: charset %s not offered, using %s", loc, c)
                return c
        self.log.warning("Charsets: no idea what to do with %r", offers)
        return None

    def _set_charset_decoder(self, codec):
        if codec or codec is None:
            self._decoder = codecs.getincrementaldecoder(codec or "utf8")(errors=self._charset_errors)
        else:
            self._decoder = NullDecoder()

    def _set_charset_encoder(self, codec):
        if codec or codec is None:
            self._encoder = lambda x: x.encode(encoding=codec or "utf8", errors=self._charset_errors)
        else:
            self._encoder = lambda x: x

    async def _set_charset(self, charset, rv=True):
        """
        Completed charset subnegotiation.
        Queues a callback to set the decoder in-line.

        Only clears the lock if `charset` is not a non-empty string.
        """
        if charset:
            try:
                codecs.getincrementaldecoder(charset)
            except LookupError:
                return False

            self._set_charset_encoder(charset)
            self._use_current_charset = bool(charset)

            await self.queue_recv_message(SetCharset(charset))
            self._charset = charset
        if self._charset_lock is not None:
            self._charset_lock.set()
            self._charset_lock = None
        self._charset_retry = False
        return rv

    async def handle_will_charset(self):
        """
        The remote side sent a WILL. Ack if we do charsets.
        """
        return isinstance(self._charset, str)

    async def handle_do_charset(self):
        """
        The remote side accepts our WILL. Start negotiating.
        """
        if not isinstance(self._charset, str):
            return False
        if self._charset_lock is not None:
            return True

        charsets = self._charsets_wanted
        if charsets is None:
            self._charsets_wanted = charsets = self.get_supported_charsets() or ("UTF-8","LATIN9","LATIN1","US-ASCII")
        if not charsets:
            import pdb;pdb.set_trace()

        self._charset_lock = anyio.Event()
        # executed by the dispatcher after sending WILL
        return self.send_subneg(CHARSET,REQUEST,b';',';'.join(charsets).encode("ascii"))

    async def wait_for_charset(self):
        if self._charset_lock is not None:
            await self._charset_lock.wait()

    async def request_charset(self):
        """
        Ask the remote side to choose one of the charsets returned by
        `get_supported_charsets`.

        Return False if no charset negotiation, None if rejected, or the
        name of the charset accepted by the other side.
        """
        return self._do_request(CHARSET, True, lambda: self._charset)

    async def _do_request(self, opt, is_local, result):
        if (self.local_status if is_local else self.remote_status)(CHARSET):
            await getattr(self,"_request_"+opt.name.lower())()
        elif not await (self.local_option if is_local else self.remote_option)(CHARSET, True):
            return False

        while self._charset_lock:
            await self._charset_lock.wait()
        await self._request_charset()
        await self._charset_lock.wait()
        return self._charset

    async def _request_charset(self):

        charsets = self._charsets_wanted
        if charsets is None:
            self._charsets_wanted = charsets = self.get_supported_charsets() or ("UTF-8","LATIN9","LATIN1","US-ASCII")

        if self.local_status(CHARSET):
            if not self._charset_lock:
                self._charset_lock = anyio.Event()
            if not charsets:
                self.log.error("Charset list is empty!")
                await self._set_charset(None)
                return
            await self.send_subneg(CHARSET,REQUEST,b';',';'.join(charsets).encode("ascii"))
        else:
            if not await self.local_option(CHARSET, True):
                return False
            # if True, we got a DO back, which triggered handle_do_charset


    async def handle_subneg_charset(self, buf):
        opt,buf = buf[0],buf[1:]

        try:
            opt_kind = Req(opt).name
        except ValueError:
            opt_kind = f'?{opt}'
        self.log.debug('recv %s %s: %r', 'CHARSET', opt_kind, buf.decode("ascii"))

        if opt == REQUEST:
            if self._charset_lock is not None and self.server:
                if not self._charset_retry:
                    # NACK this request: simultaneous requests sent by both sides.
                    await self.send_subneg(CHARSET,REJECTED)
                    return
                # However, we need to guard against the case where the
                # client also rejects our choice because it doesn't
                # like it. In that case the incoming reject, below, sets
                # this flag so we know we may process the client's new
                # request.
                self._charset_retry = False

            if buf.startswith(b'TTABLE '):
                buf = buf[8:]  # ignore TTABLE_V
            sep,buf = buf[0:1],buf[1:]
            offers = [charset.decode('ascii') for charset in buf.split(sep)]
            selected = self.select_charset(offers)

            if selected is None:
                self.log.debug('send IAC SB CHARSET REJECTED IAC SE')
                await self.send_subneg(CHARSET, REJECTED)
                if self.client and self._charset_lock is not None and self.local_status(CHARSET):
                    # The server has rejected my request due to a
                    # collision. Thus I need to retry.
                    self._charset_retry = True
                else:
                    await self._set_charset(selected)
            else:
                self.log.debug('send IAC SB CHARSET ACCEPTED %r IAC SE',selected)
                await self.send_subneg(CHARSET, ACCEPTED, selected.encode('ascii'))
                await self._set_charset(selected)

        elif opt == ACCEPTED:
            charset = buf.decode('ascii')
            self.log.debug('recv IAC SB CHARSET ACCEPTED %r IAC SE', charset)
            if not await self._set_charset(charset):
                # Duh. The remote side returned something we can't handle.
                await self._set_charset("UTF-8", False)

        elif opt == REJECTED:
            self.log.warning('recv IAC SB CHARSET REJECTED IAC SE')
            if self._charset_retry:
                if self.server:
                    # this is normal on the client
                    self.log.warning("Charset: retry set and we get a REJ??")
                    self._charset_retry = False
            elif self._charsets_wanted:
                self._charsets_wanted = None
            else:
                await self._set_charset(None)
                return

            if self._charset_lock:
                # Other side rejected us, either because of overlapping
                # requests or because it didn't like ours: remember that it
                # did, see above
                if self.client:
                    # Server didn't like our first attempt, so try again
                    await self._request_charset()
                else:
                    self._charset_retry = True

        else:
            self.log.warning("SB CHARSET TTABLE (or other nonsense): %r %r", opt, buf)
            self._local_option[CHARSET] = False
            self._remote_option[CHARSET] = False


    def encoding(self, outgoing=None, incoming=None):
        """
        Return encoding for the given stream direction.

        :param bool outgoing: Whether the return value is suitable for
            encoding bytes for transmission to server.
        :param bool incoming: Whether the return value is suitable for
            decoding bytes received by the client.
        :raises TypeError: when a direction argument, either ``outgoing``
            or ``incoming``, was not set ``True``.
        :returns: ``'US-ASCII'`` for the directions indicated, unless
            ``BINARY`` :rfc:`856` has been negotiated for the direction
            indicated or :attr`force_binary` is set ``True``.
        :rtype: str
        """
        if not (outgoing or incoming):
            raise TypeError("encoding arguments 'outgoing' and 'incoming' "
                            "are required: toggle at least one.")

        # may we encode in the direction indicated?
        _outgoing_only = outgoing and not incoming
        _incoming_only = not outgoing and incoming
        _bidirectional = outgoing and incoming
        may_encode = ((_outgoing_only and self.outbinary) or
                      (_incoming_only and self.inbinary) or
                      (_bidirectional and
                       self.outbinary and self.inbinary))

        if self.force_binary or may_encode:
            # The 'charset' value, initialized using keyword argument
            # default_encoding, may be re-negotiated later.  Only the CHARSET
            # negotiation method allows the server to select an encoding, so
            # this value is reflected here by a single return statement.
            return self.extra.get("charset","utf-8")

        return 'US-ASCII'



class TelnetStream(BaseTelnetStream):
    """
    The "real" part of a Telnet implementation
    """
    #: Whether the last byte received by :meth:`~.feed_byte` is a matching
    #: special line character value, if negotiated.
    slc_received = None

    #: SLC function values and callbacks are fired for clients in Kludge
    #: mode not otherwise capable of negotiating LINEMODE, providing
    #: transport remote editing function callbacks for dumb clients.
    slc_simulated = True

    default_slc_tab = slc.BSD_SLC_TAB

    #: Initial line mode requested by server if client supports LINEMODE
    #: negotiation (remote line editing and literal echo of control chars)
    default_linemode = slc.Linemode(slc.LMode_Mode.REMOTE | slc.LMode_Mode.LIT_ECHO)


    def __init__(self, *a, **kw):
        """
        Parameters in addition to those for `TelnetStream`:

        :param bool client: Whether the IAC interpreter should react from
            the client point of view.
        :param bool server: Whether the IAC interpreter should react from
            the server point of view.

        One of ``client`` or ``server`` must be ``True``.

        This is an async context manager.
        """
        super().__init__(*a,**kw)

        #: SLC buffer
        self._slc_buffer = bytearray()

        #: SLC Tab (SLC Functions and their support level, and ascii value)
        self.slctab = slc.generate_slctab(self.default_slc_tab)

        #: Represents LINEMODE MODE negotiated or requested by client.
        #: attribute ``ack`` returns True if it is in use.
        self._linemode = slc.Linemode()

        # wishing not to wire any callbacks at all may simply allow our stream
        # to gracefully log and do nothing about in most cases.

        self._slc_callback = {}

        # extended callbacks for "interesting" incoming messages (LOGOUT, SB)
        self._ext_callback = {}

        # fetch data to send as subneg on incoming WILL
        self._ext_send_callback = {}

    def _repr(self):
        info = super()._repr()

        info.append('mode:{self.mode}'.format(self=self))

        # IAC options
        # info.append('{0}lineflow'.format('+' if self.lflow else '-'))
        info.append('{0}xon_any'.format('+' if self.xon_any else '-'))
        info.append('{0}slc_sim'.format('+' if self.slc_simulated else '-'))

        return info


    async def feed_byte(self, byte):
        """
        Feed a single byte into Telnet option state machine.

        :param int byte: an 8-bit byte value as integer (0-255), or
            a bytes array.  When a bytes array, it must be of length
            1.
        :rtype bool: Whether the given ``byte`` is "in band", that is, should
            be duplicated to a connected terminal or device.  ``False`` is
            returned for an ``IAC`` command for each byte until its completion.
        """
        self.slc_received = None

        if not await super().feed_byte(byte):
            return False

        if (self.mode == 'remote' or
              self.mode == 'kludge' and self.slc_simulated):
            # 'byte' is tested for SLC characters
            (callback, slc_name, slc_def) = slc.snoop(
                byte, self.slctab, self._slc_callback)

            # Inform caller which SLC function occurred by this attribute.
            self.slc_received = slc_name
            if callback:
                self.log.debug('slc.snoop({!r}): {}, callback is {}.'
                               .format(byte, slc.name_slc_command(slc_name),
                                       callback.__name__))
                await callback(slc_name)

        # whether this data should be forwarded (to the reader)
        return True

    def get_slc_callback(self, func):
        try:
            return self._slc_callback[func]
        except KeyError:
            return getattr(self,"handle_slc_"+func.name.lower(), None)

    async def handle_will_status(self):
        """
        Send ``IAC-SB-STATUS-SEND`` sub-negotiation (:rfc:`859`).

        This method may only be called after ``IAC-WILL-STATUS`` has been
        received. Returns True if status request was sent.
        """

        if not self.remote_status(STATUS):
            self.log.debug('cannot send SB STATUS SEND '
                           'without receipt of WILL STATUS')
            return False

        self.log.debug('send IAC SB STATUS SEND IAC SE')
        await self.send_subneg(STATUS,SEND)
        return True

    async def handle_will_tspeed(self):
        """
        Send IAC-SB-TSPEED-SEND sub-negotiation, :rfc:`1079`.

        This method may only be called after ``IAC-WILL-TSPEED`` has been
        received. Returns True if TSPEED request was sent.
        """
        if not self.remote_status(TSPEED):
            self.log.debug('cannot send SB TSPEED SEND '
                           'without receipt of WILL TSPEED')
            return False
        self.log.debug('send IAC SB TSPEED SEND IAC SE')
        await self.send_subnet(TSPEED, SEND)
        return True

    async def handle_will_new_environ(self):
        """
        Request sub-negotiation NEW_ENVIRON, :rfc:`1572`.

        Returns True if request is valid for telnet state, and was sent.
        """
        assert self.server, 'SB NEW_ENVIRON SEND may only be sent by server'

        if not self._remote_option.enabled(NEW_ENVIRON):
            self.log.debug('cannot send SB NEW_ENVIRON SEND IS '
                           'without receipt of WILL NEW_ENVIRON')
            return False

        request_list = await self._ext_send_callback[NEW_ENVIRON]()

        if not request_list:
            self.log.debug('request_environ: server protocol makes no demand, '
                           'no request will be made.')
            return False

        response = bytearray([SEND])

        for env_key in request_list:
            if env_key in (VAR, USERVAR):
                # VAR followed by IAC,SE indicates "send all the variables",
                # whereas USERVAR indicates "send all the user variables".
                # In today's era, there is little distinction between them.
                response.append(env_key)
            else:
                response.extend([VAR])
                response.extend([_escape_environ(env_key.encode('ascii'))])
        self.log.debug('request_environ: {!r}'.format(b''.join(response)))
        await self.send_subneg(NEW_ENVIRON, *response)
        return True

    async def handle_will_xdisploc(self):
        """
        Send XDISPLOC, SEND sub-negotiation, :rfc:`1086`.

        Returns True if request is valid for telnet state, and was sent.
        """
        assert self.server, (
            'SB XDISPLOC SEND may only be sent by server end')
        if not self.remote_status(XDISPLOC):
            self.log.debug('cannot send SB XDISPLOC SEND'
                           'without receipt of WILL XDISPLOC')
            return False

        self.log.debug('send IAC SB XDISPLOC SEND IAC SE')
        await self.send_subneg(XDISPLOC,SEND)
        return True

    async def handle_will_ttype(self):
        """
        Send TTYPE SEND sub-negotiation, :rfc:`930`.

        Returns True if request is valid for telnet state, and was sent.
        """
        if not self.server:
            self.log.error('TTYPE SEND may only be sent by server')
            return False
        if not hasattr(self, "handle_send_ttype"):
            return False
        return self.send_subneg(TTYPE, SEND)

    async def handle_do_ttype(self):
        """
        Send TTYPE SEND sub-negotiation, :rfc:`930`.

        Returns True if request is valid for telnet state, and was sent.
        """
        if self.server:
            self.log.error('TTYPE IS may only be sent by client')
            return False
        if not hasattr(self, "handle_recv_ttype"):
            return False
        return True

    async def handle_will_forwardmask(self, fmask=None):
        """
        Request the client forward their terminal control characters.

        Characters are indicated in the :class:`~.Forwardmask` instance
        ``fmask``.  When fmask is None, a forwardmask is generated for the SLC
        characters registered by :attr:`~.slctab`.
        """
        assert self.server, (
            'DO FORWARDMASK may only be sent by server end')
        if not self.remote_status(LINEMODE):
            self.log.debug('cannot send SB LINEMODE DO'
                           'without receipt of WILL LINEMODE')
            return False

        if fmask is None:  # TODO
            opt = SB + LINEMODE + slc.LMODE_FORWARDMASK
            forwardmask_enabled = (
                self.server and self._local_option.get(opt, False)
            ) or self._remote_option.get(opt, False)
            fmask = slc.generate_forwardmask(
                binary_mode=self._local_option.enabled(BINARY),
                tabset=self.slctab, ack=forwardmask_enabled)

        assert isinstance(fmask, slc.Forwardmask), fmask

        self.log.debug('send IAC SB LINEMODE DO LMODE_FORWARDMASK::')
        for maskbit_descr in fmask.description_table():
            self.log.debug('  {}'.format(maskbit_descr))
        self.log.debug('send IAC SE')

        await self.send_subneg(LINEMODE + DO + slc.LMODE_FORWARDMASK, fmask.value)


    async def send_lineflow_mode(self):
        """Send LFLOW mode sub-negotiation, :rfc:`1372`.

        Returns True if request is valid for telnet state, and was sent.
        """
        if self.client:
            self.log.error('only server may send IAC SB LINEFLOW <MODE>')
        elif self._remote_option.get(LFLOW, None) is not True:
            self.log.error('cannot send IAC SB LFLOW '
                           'without receipt of WILL LFLOW')
        else:
            if self.xon_any:
                (mode, desc) = (LFLOW_RESTART_ANY, 'LFLOW_RESTART_ANY')
            else:
                (mode, desc) = (LFLOW_RESTART_XON, 'LFLOW_RESTART_XON')
            self.log.debug('send IAC SB LFLOW {} IAC SE'.format(desc))
            await self.send_subneg(LFLOW, mode)
            return True
        return False

    async def send_linemode(self, linemode=None):
        """
        Set and Inform other end to agree to change to linemode, ``linemode``.

        An instance of the Linemode class, or self.linemode when unset.
        """
        if not (self._local_option.enabled(LINEMODE) or
                self._remote_option.enabled(LINEMODE)):
            assert False, ('Cannot send LINEMODE-MODE without first '
                           '(DO, WILL) LINEMODE received.')

        if linemode is not None:
            self.log.debug('set Linemode {0!r}'.format(linemode))
            self._linemode = linemode

        self.log.debug('send IAC SB LINEMODE LINEMODE-MODE {0!r} IAC SE'
                       .format(self._linemode))

        await self.send_subneg(LINEMODE, slc.LMODE_MODE + self._linemode.mask)

    async def handle_tm(self, cmd):
        """
        Handle IAC (WILL, WONT, DO, DONT) Timing Mark (TM).

        TM is essentially a NOP that any IAC interpreter must answer, if at
        least it answers WONT to unknown options (required), it may still
        be used as a means to accurately measure the "ping" time.
        """
        self.log.debug('IAC TM: Received {} TM (Timing Mark).'
                       .format(name_command(cmd)))

# public Special Line Mode (SLC) callbacks
#
    def set_slc_callback(self, slc_byte, func):
        """
        Register ``func`` as callable for receipt of ``slc_byte``.

        :param bytes slc_byte: any of SLC_SYNCH, SLC_BRK, SLC_IP, SLC_AO,
            SLC_AYT, SLC_EOR, SLC_ABORT, SLC_EOF, SLC_SUSP, SLC_EC, SLC_EL,
            SLC_EW, SLC_RP, SLC_XON, SLC_XOFF ...
        :param Callable func: These callbacks receive a single argument: the
            SLC function byte that fired it. Some SLC and IAC functions are
            intermixed; which signaling mechanism used by client can be tested
            by evaluating this argument.
        """
        assert callable(func), ('Argument func must be callable')
        assert isinstance(slc_byte, int) and 0 < slc_byte < slc.NSLC, ('Unknown SLC byte: {!r}'.format(slc_byte))
        self._slc_callback[slc_byte] = func

    async def handle_ew(self, slc):
        """
        Handle SLC_EW (Erase Word).

        Provides a function which deletes the last preceding undeleted
        character, and any subsequent bytes until next whitespace character
        from data ready on current line of input.
        """
        self.log.debug('SLC EC: Erase Word (unhandled).')

    async def handle_rp(self, slc):
        """Handle SLC Repaint (RP)."""
        self.log.debug('SLC RP: Repaint (unhandled).')

    async def handle_lnext(self, slc):
        """Handle SLC Literal Next (LNEXT) (Next character is received raw)."""
        self.log.debug('SLC LNEXT: Literal Next (unhandled)')

    async def handle_xon(self, byte):
        """Handle SLC Transmit-On (XON)."""
        self.log.debug('SLC XON: Transmit On (unhandled).')

    async def handle_xoff(self, byte):
        """Handle SLC Transmit-Off (XOFF)."""
        self.log.debug('SLC XOFF: Transmit Off.')

# public Telnet extension callbacks
#
    def set_ext_send_callback(self, cmd, func):
        """
        Register async callback for inquires of sub-negotiation of ``cmd``.

        :param Callable func: A callable function for the given ``cmd`` byte.
            Note that the return type must match those documented.
        :param bytes cmd: These callbacks must return any number of arguments,
            for each registered ``cmd`` byte, respectively:

            * SNDLOC: for clients, returning one argument: the string
              describing client location, such as ``b'ROOM 641-A'``,
              :rfc:`779`.

            * NAWS: for clients, returning two integer arguments (width,
              height), such as (80, 24), :rfc:`1073`.

            * TSPEED: for clients, returning two integer arguments (rx, tx)
              such as (57600, 57600), :rfc:`1079`.

            * TTYPE: for clients, returning one string, usually the terminfo(5)
              database capability name, such as 'xterm', :rfc:`1091`.

            * XDISPLOC: for clients, returning one string, the DISPLAY host
              value, in form of <host>:<dispnum>[.<screennum>], :rfc:`1096`.

            * NEW_ENVIRON: for clients, returning a dictionary of (key, val)
              pairs of environment item values, :rfc:`1408`.

            * CHARSET: for clients, receiving iterable of strings of character
              sets requested by server, callback must return one of those
              strings given, :rfc:`2066`.

            * Any other extension: a bytestring, sent as-is in a
              Subnegotiation, unless the return value is ``None``.
        """
        assert isinstance(cmd, int), cmd
        assert callable(func), 'Argument func must be callable'
        self._ext_send_callback[cmd] = func

    def set_ext_callback(self, cmd, func):
        """
        Register async ``func`` as callback for receipt of ``cmd`` negotiation.

        :param bytes cmd: One of the following listed bytes:

        * ``LOGOUT``: for servers and clients, receiving one argument.
          Server end may receive DO or DONT as argument ``cmd``, indicating
          client's wish to disconnect, or a response to WILL, LOGOUT,
          indicating it's wish not to be automatically disconnected.  Client
          end may receive WILL or WONT, indicating server's wish to disconnect,
          or acknowledgment that the client will not be disconnected.

        * ``SNDLOC``: for servers, receiving one argument: the string
          describing the client location, such as ``'ROOM 641-A'``, :rfc:`779`.

        * ``NAWS``: for servers, receiving two integer arguments (width,
          height), such as (80, 24), :rfc:`1073`.

        * ``TSPEED``: for servers, receiving two integer arguments (rx, tx)
          such as (57600, 57600), :rfc:`1079`.

        * ``TTYPE``: for servers, receiving one string, usually the
          terminfo(5) database capability name, such as 'xterm', :rfc:`1091`.

        * ``XDISPLOC``: for servers, receiving one string, the DISPLAY
          host value, in form of ``<host>:<dispnum>[.<screennum>]``,
          :rfc:`1096`.

        * ``NEW_ENVIRON``: for servers, receiving a dictionary of
          ``(key, val)`` pairs of remote client environment item values,
          :rfc:`1408`.

        * ``CHARSET``: for servers, receiving one string, the character set
          negotiated by client. :rfc:`2066`.
        """
        assert isinstance(cmd, int), cmd
        assert callable(func), 'Argument func must be callable'
        self._ext_callback[cmd] = func

    async def handle_recv_xdisploc(self, xdisploc):
        """Receive XDISPLAY value ``xdisploc``, :rfc:`1096`."""
        #   xdisploc string format is '<host>:<dispnum>[.<screennum>]'.
        self.log.debug('X Display is {}'.format(xdisploc))

    async def handle_send_xdisploc(self):
        """Send XDISPLAY value ``xdisploc``, :rfc:`1096`."""
        #   xdisploc string format is '<host>:<dispnum>[.<screennum>]'.
        self.log.warning('X Display requested, sending empty string.')
        return ''

    async def handle_recv_sndloc(self, location):
        """Receive LOCATION value ``location``, :rfc:`779`."""
        self.log.debug('Location is {}'.format(location))

    async def handle_send_sndloc(self):
        """Send LOCATION value ``location``, :rfc:`779`."""
        self.log.warning('Location requested, sending empty response.')
        return ''

    async def handle_recv_naws(self, width, height):
        """Receive window size ``width`` and ``height``, :rfc:`1073`."""
        self.log.debug('Terminal cols={}, rows={}'.format(width, height))

    async def handle_send_naws(self):
        """Send window size ``width`` and ``height``, :rfc:`1073`."""
        self.log.warning('Terminal size requested, sending 80x24.')
        return 80, 24

    async def handle_recv_new_environ(self, env):
        """Receive environment variables as dict, :rfc:`1572`."""
        self.log.debug('Environment values are {!r}'.format(env))

    async def handle_send_client_new_environ(self, keys):
        """
        Send environment variables as dict, :rfc:`1572`.

        If argument ``keys`` is empty, then all available values should be
        sent. Otherwise, ``keys`` is a set of environment keys explicitly
        requested.
        """
        self.log.debug('Environment values requested, sending {{}}.')
        return dict()

    async def handle_send_server_new_environ(self):
        """Server requests environment variables as list, :rfc:`1572`."""
        self.log.debug('Environment values offered, requesting [].')
        return []

    async def handle_recv_tspeed(self, rx, tx):
        """Receive terminal speed from TSPEED as int, :rfc:`1079`."""
        self.log.debug('Terminal Speed rx:{}, tx:{}'.format(rx, tx))

    async def handle_send_tspeed(self):
        """Send terminal speed from TSPEED as int, :rfc:`1079`."""
        self.log.debug('Terminal Speed requested, sending 9600,9600.')
        return 9600, 9600

    async def handle_logout(self, cmd):
        """
        Handle (IAC, (DO | DONT | WILL | WONT), LOGOUT), :rfc:`727`.

        Only the server end may receive (DO, DONT).
        Only the client end may receive (WILL, WONT).
        """
        # Close the transport on receipt of DO, Reply DONT on receipt
        # of WILL.  Nothing is done on receipt of DONT or WONT LOGOFF.
        if cmd == DO:
            assert self.server, (cmd, LOGOUT)
            self.log.debug('client requests DO LOGOUT')
            await self._stream.aclose()
        elif cmd == DONT:
            assert self.server, (cmd, LOGOUT)
            self.log.debug('client requests DONT LOGOUT')
        elif cmd == WILL:
            assert self.client, (cmd, LOGOUT)
            self.log.debug('recv WILL TIMEOUT (timeout warning)')
            self.log.debug('send IAC DONT LOGOUT')
            return False
        elif cmd == WONT:
            assert self.client, (cmd, LOGOUT)
            self.log.debug('recv IAC WONT LOGOUT (server refuses logout')

    async def handle_subneg_tspeed(self, buf):
        """Callback handles IAC-SB-TSPEED-<buf>-SE."""
        opt,buf = buf[0],buf[1:]

        assert opt in (IS, SEND), opt
        opt_kind = {IS: 'IS', SEND: 'SEND'}.get(opt)
        self.log.debug('recv %s %s: %r', name_command(cmd), opt_kind, buf)

        if opt == IS:
            assert self.server, f'SE: cannot recv from server: {name_command(cmd)} {opt_kind}'
            rx, tx = str(), str()
            while len(buf):
                value = buf.popleft()
                if value == b',':
                    break
                rx += value.decode('ascii')
            while len(buf):
                value = buf.popleft()
                if value == b',':
                    break
                tx += value.decode('ascii')
            self.log.debug('sb_tspeed: %s,%s',rx, tx)
            try:
                rx, tx = int(rx), int(tx)
            except ValueError as err:
                self.log.error('illegal TSPEED values received '
                               '(rx={!r}, tx={!r}: {}', rx, tx, err)
                return
            await self._ext_callback[TSPEED](rx, tx)

        elif opt == SEND:
            assert self.client, f'SE: cannot recv from client: {name_command(cmd)} {opt_kind}'
            (rx, tx) = await self._ext_send_callback[TSPEED]()
            assert (type(rx), type(tx)) == (int, int), (rx, tx)
            brx = str(rx).encode('ascii')
            btx = str(tx).encode('ascii')
            response = [IAC, SB, TSPEED, IS, brx, b',', btx, IAC, SE]
            self.log.debug('send: IAC SB TSPEED IS %r,%r IAC SE', brx, btx)
            await self.send_subneg(TSPEED, IS + brx + b',' + btx)

    async def handle_subneg_xdisploc(self, buf):
        """Callback handles IAC-SB-XIDISPLOC-<buf>-SE."""
        opt,buf = buf[0],buf[1:]

        assert opt in (IS, SEND), opt
        opt_kind = {IS: 'IS', SEND: 'SEND'}.get(opt)
        self.log.debug('recv %s %s: %r', name_command(cmd), opt_kind, buf)

        if opt == IS:
            assert self.server, f'SE: cannot recv from server: {name_command(cmd)} {opt}'
            xdisploc_str = buf.decode('ascii')
            self.log.debug('recv IAC SB XDISPLOC IS %r IAC SE', xdisploc_str)
            await self._ext_callback[XDISPLOC](xdisploc_str)
        elif opt == SEND:
            assert self.client, f'SE: cannot recv from client: {name_command(cmd)} {opt}'
            xdisploc_str = (await self._ext_send_callback[XDISPLOC]()).encode('ascii')
            self.log.debug('send IAC SB XDISPLOC IS %r IAC SE', xdisploc_str)
            await self.send_subneg(XDISPLOC,IS+xdisploc_str)

    async def handle_subneg_ttype(self, buf):
        """Callback handles IAC-SB-TTYPE-<buf>-SE."""
        opt,buf = buf[0],buf[1:]

        assert opt in (IS, SEND), opt
        opt_kind = {IS: 'IS', SEND: 'SEND'}.get(opt)
        self.log.debug('recv %s %s: %r', TTYPE, opt_kind, buf)

        if opt == IS:
            # only a server is supposed to have this
            if not hasattr(self,"handle_recv_ttype"):
                self.log.error(f'SE: dunno how to recv: TTYPE {opt}')
                return
            ttype_str = buf.decode('ascii')
            await self.handle_recv_ttype(ttype_str)

        elif opt == SEND:
            # only a client is supposed to have this
            if not hasattr(self,"handle_send_ttype"):
                self.log.error(f'SE: dunno how to send: TTYPE {opt}')
                return
            ttype_str = (await self.handle_send_ttype()).encode('ascii')
            await self.send_subneg(TTYPE, IS, ttype_str)

    async def handle_subneg_new_environ(self, buf):
        """
        Callback handles (IAC, SB, NEW_ENVIRON, <buf>, SE), :rfc:`1572`.

        For requests beginning with IS, or subsequent requests beginning
        with INFO, any callback registered by :meth:`set_ext_callback` of
        cmd NEW_ENVIRON is passed a dictionary of (key, value) replied-to
        by client.

        For requests beginning with SEND, the callback registered by
        ``set_ext_send_callback`` is provided with a list of keys
        requested from the server; or None if only VAR and/or USERVAR
        is requested, indicating to "send them all".
        """
        opt,buf = buf[0],buf[1:]
        opt_kind = SubT(opt).name
        self.log.debug('recv SB Env %s: %r', opt_kind, buf)

        env = _decode_env_buf(buf)

        if opt in (IS, INFO):
            assert self.server, ('SE: cannot recv from server: {} {}'
                                 .format(name_command(NEW_ENVIRON), opt_kind,))
            if env:
                await self._ext_callback[cmd](env)

        elif opt == SEND:
            assert self.client, ('SE: cannot recv from client: {} {}'
                                 .format(name_command(cmd), opt_kind))
            # client-side, we do _not_ honor the 'send all VAR' or 'send all
            # USERVAR' requests -- it is a small bit of a security issue.
            send_env = _encode_env_buf(
                await self._ext_send_callback[NEW_ENVIRON](env.keys()))
            self.log.debug('env send: {!r}'.format(response))
            await self.send_subneg(NEW_ENVIRON, IS, send_env)

    async def handle_subneg_sndloc(self, buf):
        """Fire callback for IAC-SB-SNDLOC-<buf>-SE (:rfc:`779`)."""
        location_str = buf.decode('ascii')
        await self._ext_callback[SNDLOC](location_str)

    async def _send_naws(self):
        """Fire callback for IAC-DO-NAWS from server."""
        # Similar to the callback method order fired by handle_subneg_naws(),
        # we expect our parameters in order of (rows, cols), matching the
        # termios.TIOCGWINSZ and terminfo(5) cup capability order.
        rows, cols = await self._ext_send_callback[NAWS]()

        # NAWS limits columns and rows to a size of 0-65535 (unsigned short).
        #
        # >>> struct.unpack('!HH', b'\xff\xff\xff\xff')
        # (65535, 65535).
        rows, cols = max(min(65535, rows), 0), max(min(65535, cols), 0)

        # NAWS is sent in (col, row) order:
        #
        #    IAC SB NAWS WIDTH[1] WIDTH[0] HEIGHT[1] HEIGHT[0] IAC SE
        #
        value = struct.pack('!HH', cols, rows)
        self.log.debug('send IAC SB NAWS (rows={0}, cols={1}) IAC SE'
                       .format(rows, cols))
        await self.send_subneg(NAWS, value)

    async def handle_subneg_naws(self, buf):
        """Fire callback for IAC-SB-NAWS-<cols_rows[4]>-SE (:rfc:`1073`)."""
        cmd = buf.popleft()
        assert cmd == NAWS, name_command(cmd)
        assert len(buf) == 4, (
            'bad NAWS length {}: {!r}'.format(len(buf), buf)
        )
        assert self._remote_option.enabled(NAWS), (
            'received IAC SB NAWS without receipt of IAC WILL NAWS')
        # note a similar formula:
        #
        #    cols, rows = ((256 * buf[0]) + buf[1],
        #                  (256 * buf[2]) + buf[3])
        cols, rows = struct.unpack('!HH', buf)
        self.log.debug('recv IAC SB NAWS (cols={0}, rows={1}) IAC SE'
                       .format(cols, rows))

        # Flip the bytestream order (cols, rows) -> (rows, cols).
        #
        # This is for good reason: it matches the termios.TIOCGWINSZ
        # structure, which also matches the terminfo(5) capability, 'cup'.
        await self._ext_callback[NAWS](rows, cols)

    async def handle_subneg_lflow(self, buf):
        """Callback responds to IAC SB LFLOW, :rfc:`1372`."""
        buf.popleft()  # LFLOW
        if self._local_option.get(LFLOW, None) is not True:
            raise ValueError('received IAC SB LFLOW without '
                             'first receiving IAC DO LFLOW.')
        opt = buf.popleft()
        if opt in (LFLOW_OFF, LFLOW_ON):
            self.lflow = opt == LFLOW_ON
            self.log.debug('LFLOW (toggle-flow-control) {}'.format(
                'ON' if self.lflow else 'OFF'))

        elif opt in (LFLOW_RESTART_ANY, LFLOW_RESTART_XON):
            self.xon_any = opt == LFLOW_RESTART_XON
            self.log.debug('LFLOW (toggle-flow-control) {}'.format(
                'RESTART_ANY' if self.xon_any else 'RESTART_XON'))

        else:
            raise ValueError(
                'Unknown IAC SB LFLOW option received: {!r}'.format(buf))

    async def handle_subneg_status(self, buf):
        """
        Callback responds to IAC SB STATUS, :rfc:`859`.

        This method simply delegates to either of :meth:`_receive_status`
        or :meth:`_send_status`.
        """
        buf.popleft()
        opt = buf.popleft()
        if opt == SEND:
            self._send_status()
        elif opt == IS:
            self._receive_status(buf)
        else:
            raise ValueError('Illegal byte following IAC SB STATUS: {!r}, '
                             'expected SEND or IS.'.format(opt))

    def _receive_status(self, buf):
        """
        Callback responds to IAC SB STATUS IS, :rfc:`859`.

        :param bytes buf: sub-negotiation byte buffer containing status data.

        This implementation does its best to analyze our perspective's state
        to the state options given.  Any discrepancies are reported to the
        error log, but no action is taken.
        """
        for pos in range(len(buf) // 2):
            cmd = buf.popleft()
            try:
                opt = buf.popleft()
            except IndexError:
                # a remainder in division step-by-two, presumed nonsense.
                raise ValueError('STATUS incomplete at pos {}, cmd: {}'
                                 .format(pos, name_command(cmd)))

            matching = False
            if cmd not in (DO, DONT, WILL, WONT):
                raise ValueError('STATUS invalid cmd at pos {}: {}, '
                                 'expected DO DONT WILL WONT.'
                                 .format(pos, cmd))

            if cmd in (DO, DONT):
                _side = 'local'
                enabled = self._local_option.get(opt, None) is True
                matching = ((cmd == DO and enabled) or
                            (cmd == DONT and not enabled))
            else:  # (WILL, WONT)
                _side = 'remote'
                enabled = self._remote_option.get(opt, None) is True
                matching = ((cmd == WILL and enabled) or
                            (cmd == WONT and not enabled))
            _mode = 'enabled' if enabled else 'not enabled'

            if not matching:
                self.log.error('STATUS {cmd} {opt}: disagreed, '
                               '{side} option is {mode}.'.format(
                                   cmd=name_command(cmd),
                                   opt=name_command(opt),
                                   side=_side, mode=_mode))
                self.log.error('remote {!r} is {}'.format(
                    [(name_commands(_opt), _val)
                     for _opt, _val in self._remote_option.items()],
                    self._remote_option.get(opt, None)))
                self.log.error(' local {!r} is {}'.format(
                    [(name_commands(_opt), _val)
                     for _opt, _val in self._local_option.items()],
                    self._local_option.get(opt, None)))
                continue
            self.log.debug('STATUS {} {} (agreed).'.format(name_command(cmd),
                                                           name_command(opt)))

    async def _send_status(self):
        """Callback responds to IAC SB STATUS SEND, :rfc:`859`."""
        if not self.local_status(STATUS):
            raise ValueError('Only sender of IAC WILL STATUS '
                             'may reply by IAC SB STATUS IS.')

        response = bytearray([STATUS, IS])
        for opt, status in self._local_option.items():
            # status is 'WILL' for local option states that are True,
            # and 'WONT' for options that are False.
            if opt == STATUS:
                continue
            if not isinstance(status, bool):
                continue
            response.extend([WILL if status else WONT, opt])
        for opt, status in self._remote_option.items():
            # status is 'DO' for remote option states that are True,
            # or for any DO option requests pending reply. status is
            # 'DONT' for any remote option states that are False,
            # or for any DONT option requests pending reply.
            if opt == STATUS:
                continue
            if not isinstance(status, bool):
                continue
            response.extend([DO if status else DONT, opt])
        # TODO there ae no SB items here

        self.log.debug('send IAC SB STATUS IS {} IAC SE'.format(' '.join([
            name_command(byte) for byte in list(response)[4:-2]])))
        await self.send_subneg(b''.join(response))

    # Special Line Character and other LINEMODE functions.

    async def handle_subneg_linemode(self, buf):
        """Callback responds to bytes following IAC SB LINEMODE."""
        buf.popleft()
        opt = buf.popleft()
        if opt == slc.LMODE_MODE:
            self.handle_subneg_linemode_mode(buf)
        elif opt == slc.LMODE_SLC:
            self.handle_subneg_linemode_slc(buf)
        elif opt in (DO, DONT, WILL, WONT):
            sb_opt = buf.popleft()
            if sb_opt != slc.LMODE_FORWARDMASK:
                raise ValueError(
                    'Illegal byte follows IAC SB LINEMODE {}: {!r}, '
                    ' expected LMODE_FORWARDMASK.'
                    .format(name_command(opt), sb_opt))
            self.log.debug('recv IAC SB LINEMODE {} LMODE_FORWARDMASK,'
                           .format(name_command(opt)))
            self.handle_subneg_forwardmask(LINEMODE, buf)
        else:
            raise ValueError('Illegal IAC SB LINEMODE option {!r}'.format(opt))

    async def handle_subneg_linemode_mode(self, mode):
        """
        Callback handles mode following IAC SB LINEMODE LINEMODE_MODE.

        :param bytes mode: a single byte

        Result of agreement to enter ``mode`` given applied by setting the
        value of ``self.linemode``, and sending acknowledgment if necessary.
        """
        suggest_mode = slc.Linemode(mode[0])

        self.log.debug('recv IAC SB LINEMODE LINEMODE-MODE {0!r} IAC SE'
                       .format(suggest_mode.mask))

        if not suggest_mode.ack:
            # This implementation acknowledges and sets local linemode
            # to *any* setting the remote end suggests, requiring a
            # reply.  See notes later under server receipt of acknowledged
            # linemode.
            self.send_linemode(linemode=slc.Linemode(
                mask=bytes([ord(suggest_mode.mask) | ord(slc.LMode_Mode.ACK)]))
            )
            return

        # " In all cases, a response is never generated to a MODE
        #   command that has the MODE_ACK bit set."
        #
        # simply: cannot call self.send_linemode() here forward.

        if self.client:
            if self._linemode != suggest_mode:
                # " When a MODE command is received with the MODE_ACK bit set,
                #   and the mode is different that what the current mode is,
                #   the client will ignore the new mode"
                #
                self.log.warning('server mode differs from local mode, '
                                 'though ACK bit is set. Local mode will '
                                 'remain.')
                self.log.warning('!remote: {0!r}'.format(suggest_mode))
                self.log.warning('  local: {0!r}'.format(self._linemode))
                return

            self.log.debug('Linemode matches, acknowledged by server.')
            self._linemode = suggest_mode
            return

        # as a server, we simply honor whatever is given.  This is also
        # problematic in some designers may wish to implement shells
        # that specifically do not honor some parts of the bitmask, we
        # must provide them an any/force-on/force-off mode-table interface.
        if self._linemode != suggest_mode:
            self.log.debug('We suggested, - {0!r}'.format(self._linemode))
            self.log.debug('Client choses + {0!r}'.format(suggest_mode))
        else:
            self.log.debug('Linemode agreed by client: {0!r}'
                           .format(self._linemode))

        self._linemode = suggest_mode

    async def handle_subneg_linemode_slc(self, buf):
        """
        Callback handles IAC-SB-LINEMODE-SLC-<buf>.

        Processes SLC command function triplets found in ``buf`` and replies
        accordingly.
        """
        if not len(buf) - 2 % 3:
            raise ValueError('SLC buffer wrong size: expect multiple of 3: {}'
                             .format(len(buf) - 2))
        await self._slc_start()
        while len(buf):
            func = buf.popleft()
            flag = buf.popleft()
            value = buf.popleft()
            slc_def = slc.SLC(flag, value)
            self._slc_process(func, slc_def)
        await self._slc_end()
        # await self.request_forwardmask()  # TODO

    async def _slc_end(self):
        """Transmit SLC commands buffered by :meth:`_slc_send`."""
        if len(self._slc_buffer):
            self.log.debug('send (slc_end): {!r}'
                           .format(b''.join(self._slc_buffer)))
            buf = b''.join(self._slc_buffer)
            await self.send(buf)
            self._slc_buffer.clear()

        self.log.debug('slc_end: [..] IAC SE')
        await self.send_iac(SE)

    async def _slc_start(self):
        """Send IAC SB LINEMODE SLC header."""
        self.log.debug('slc_start: IAC SB LINEMODE SLC [..]')
        await self.send_iac(SB, LINEMODE, slc.LMODE_SLC)

    async def _slc_send(self, slctab=None):
        """
        Send supported SLC characters of current tabset, or specified tabset.

        :param dict slctab: SLC byte tabset as dictionary, such as
            slc.BSD_SLC_TAB.
        """
        send_count = 0
        slctab = slctab or self.slctab
        for func in range(slc.NSLC):
            if func == 0 and self.client:
                # only the server may send an octet with the first
                # byte (func) set as 0 (SLC_NOSUPPORT).
                continue

            _default = slc.NoSupport()
            if self.slctab.get(bytes([func]), _default).nosupport:
                continue

            self._slc_add(bytes([func]))
            send_count += 1
        self.log.debug('slc_send: {} functions queued.'.format(send_count))

    def _slc_add(self, func, slc_def=None):
        """
        Prepare slc triplet response (function, flag, value) for transmission.

        For the given SLC_func byte and slc_def instance providing
        byte attributes ``flag`` and ``val``. If no slc_def is provided,
        the slc definition of ``slctab`` is used by key ``func``.
        """
        if slc_def is None:
            slc_def = self.slctab[func]
        self.log.debug('_slc_add ({:<10} {})'.format(
            slc.name_slc_command(func) + ',', slc_def))
        if len(self._slc_buffer) >= (slc.NSLC-1) * 6:
            raise ValueError('SLC: buffer full!')
        self._slc_buffer.extend([func, slc_def.mask, slc_def.val])

    async def _slc_process(self, func, slc_def):
        """
        Process an SLC definition provided by remote end.

        Ensure the function definition is in-bounds and an SLC option
        we support. Store SLC_VARIABLE changes to self.slctab, keyed
        by SLC byte function ``func``.

        The special definition (0, SLC_DEFAULT|SLC_VARIABLE, 0) has the
        side-effect of replying with a full slc tabset, resetting to
        the default tabset, if indicated.
        """
        # out of bounds checking
        if ord(func) >= slc.NSLC:
            self.log.warning('SLC not supported (out of range): ({!r})'
                             .format(func))
            self._slc_add(func, slc.NoSupport())
            return

        # process special request
        if func == 0:
            if slc_def.level == slc.Var.DEFAULT:
                # client requests we send our default tab,
                self.log.debug('_slc_process: client request SLC_DEFAULT')
                await self._slc_send(self.default_slc_tab)
            elif slc_def.level == slc.Var.VARIABLE:
                # client requests we send our current tab,
                self.log.debug('_slc_process: client request SLC_VARIABLE')
                await self._slc_send()
            else:
                self.log.warning('func(0) flag expected, got {}.'.format(slc_def))
            return

        self.log.debug('_slc_process {:<9} mine={}, his={}'.format(
            slc.name_slc_command(func), self.slctab[func], slc_def))

        # evaluate slc
        mylevel, myvalue = (self.slctab[func].level, self.slctab[func].val)
        if slc_def.level == mylevel and myvalue == slc_def.val:
            return
        elif slc_def.level == mylevel and slc_def.ack:
            return
        elif slc_def.ack:
            self.log.debug('slc value mismatch with ack bit set: ({!r},{!r})'
                           .format(myvalue, slc_def.val))
            return
        else:
            self._slc_change(func, slc_def)

    async def _slc_change(self, func, slc_def):
        """
        Update SLC tabset with SLC definition provided by remote end.

        Modify private attribute ``slctab`` appropriately for the level
        and value indicated, except for slc tab functions of value
        SLC_NOSUPPORT and reply as appropriate through :meth:`_slc_add`.
        """
        hislevel = slc_def.level
        mylevel = self.slctab[func].level
        if hislevel == slc.Var.NOSUPPORT:
            # client end reports SLC_NOSUPPORT; use a
            # nosupport definition with ack bit set
            self.slctab[func] = slc.Var.nosupport()
            self.slctab[func].set_flag(slc.Flush.ACK)
            self._slc_add(func)
            return

        if hislevel == slc.Var.DEFAULT:
            # client end requests we use our default level
            if mylevel == slc.Var.DEFAULT:
                # client end telling us to use SLC_DEFAULT on an SLC we do not
                # support (such as SYNCH). Set flag to SLC_NOSUPPORT instead
                # of the SLC_DEFAULT value that it begins with
                self.slctab[func].set_mask(slc.Var.NOSUPPORT)
            else:
                # set current flag to the flag indicated in default tab
                self.slctab[func].set_mask(
                    self.default_slc_tab.get(func).mask)
            # set current value to value indicated in default tab
            self.default_slc_tab.get(func, slc.NoSupport())
            self.slctab[func].set_value(slc_def.val)
            self._slc_add(func)
            return

        # client wants to change to a new value, or,
        # refuses to change to our value, accept their value.
        if self.slctab[func].val:
            self.slctab[func].set_value(slc_def.val)
            self.slctab[func].set_mask(slc_def.mask)
            slc_def.set_flag(slc.Flush.ACK)
            self._slc_add(func, slc_def)
            return

        # if our byte value is b'\x00', it is not possible for us to support
        # this request. If our level is default, just ack whatever was sent.
        # it is a value we cannot change.
        if mylevel == slc.Var.DEFAULT:
            # If our level is default, store & ack whatever was sent
            self.slctab[func].set_mask(slc_def.mask)
            self.slctab[func].set_value(slc_def.val)
            slc_def.set_flag(slc.Flush.ACK)
            self._slc_add(func, slc_def)
        elif (slc_def.level == slc.Var.CANTCHANGE and
              mylevel == slc.Var.CANTCHANGE):
            # "degenerate to SLC_NOSUPPORT"
            self.slctab[func].set_mask(slc.Var.NOSUPPORT)
            self._slc_add(func)
        else:
            # mask current level to levelbits (clears ack),
            self.slctab[func].set_mask(self.slctab[func].level)
            if mylevel == slc.Var.CANTCHANGE:
                slc_def = self.default_slc_tab.get(
                    func, slc.NoSupport())
                self.slctab[func].val = slc_def.val
            self._slc_add(func)

    async def handle_subneg_forwardmask(self, cmd, buf):
        """
        Callback handles request for LINEMODE <cmd> LMODE_FORWARDMASK.

        :param bytes cmd: one of DO, DONT, WILL, WONT.
        :param bytes buf: bytes following IAC SB LINEMODE DO FORWARDMASK.
        """
        # set and report about pending options by 2-byte opt,
        # not well tested, no known implementations exist !
        if self.server:
            assert self._remote_option.enabled(LINEMODE), (
                'cannot recv LMODE_FORWARDMASK {} ({!r}) '
                'without first sending DO LINEMODE.'
                .format(cmd, buf,))
            assert cmd not in (DO, DONT,), (
                'cannot recv {} LMODE_FORWARDMASK on server end'
                .format(name_command(cmd)))
        if self.client:
            assert self._local_option.enabled(LINEMODE), (
                'cannot recv {} LMODE_FORWARDMASK without first '
                ' sending WILL LINEMODE.'
                .format(name_command(cmd)))
            assert cmd not in (WILL, WONT,), (
                'cannot recv {} LMODE_FORWARDMASK on client end'
                .format(name_command(cmd)))
            assert cmd not in (DONT,) or len(buf) == 0, (
                'Illegal bytes follow DONT LMODE_FORWARDMASK: {!r}'
                .format(buf))
            assert cmd not in (DO,) and len(buf), (
                'bytes must follow DO LMODE_FORWARDMASK')

        opt = SB + LINEMODE + slc.LMODE_FORWARDMASK
        if cmd in (WILL, WONT,):
            self._remote_option[opt] = bool(cmd is WILL)
        elif cmd in (DO, DONT,):
            self._local_option[opt] = bool(cmd is DO)
            if cmd == DO:
                self._handle_do_forwardmask(buf)

    async def _handle_do_forwardmask(self, buf):
        """
        Callback handles request for LINEMODE DO FORWARDMASK.

        :param bytes buf: bytes following IAC SB LINEMODE DO FORWARDMASK.
        :raises NotImplementedError
        """
        raise NotImplementedError



bVAR = bytes([VAR])
bUSERVAR = bytes([USERVAR])
bVALUE = bytes([VALUE])
bESC = bytes([ESC])

EnvTagList = Iterator[Tuple[SubVar,bytes]]

def _escape_environ(seq: EnvTagList) -> bytes:
    """
    Return a buffer for this sequence of tagged values.

    :param bytes buf: a sequence of (SubVar,bytes) tuples
    :returns: bytes buffer
    :rtype: bytes
    """
    buf = bytearray()
    for t,s in seq:
        buf.append(t)
        for b in s:
            if b < 4:
                buf.append(SubVar.ESC)
            buf.append(b)
    return buf


def _unescape_environ(buf: bytes) -> EnvTagList:
    """
    Return a (SubVar,bytes) tuple iterator sourcing this sequence.

    :param bytes buf: given bytes buffer
    :returns: bytes buffer with escape characters removed.
    :rtype: bytes
    """
    bi = iter(buf)
    try:
        typ = next(bi)
    except StopIteration:
        return
    while True:
        buf = bytearray()
        while True:
            try:
                c = next(bi)
                if c == SubVar.ESC:
                    c = next(bi)
                elif c < 4:
                    break
                buf.append(c)
            except StopIteration:
                yield (typ,buf.decode("utf-8"))
                return
        yield (typ,buf.decode("utf-8"))
        typ = c

def _encode_env_buf(bnv: Mapping[str,str]) -> bytes:
    """
    bncode dictionary for transmission as bnvironment variables, :rfc:`1572`.

    :param bytes buf: dictionary of bnvironment values.
    :returns: bytes buffer meant to follow sequence IAC SB NEW_ENVIRON IS.
        It is not terminated by IAC SE.
    :rtype: bytes

    Returns bytes array ``buf`` for use in sequence (IAC, SB,
    NEW_ENVIRON, IS, <buf>, IAC, SE) as set forth in :rfc:`1572`.
    """
    def _make_seq(bnv):
        for k,v in bnv.items():
            yield SubVar.VAR,v.bncode("ascii")
            yield SubVar.VALUE,v.bncode("utf-8")

    return _escape_environ(_make_seq())


def _decode_env_buf(buf):
    """
    Decode bnvironment values to dictionary, :rfc:`1572`.

    :param bytes buf: bytes array following sequence IAC SB NEW_ENVIRON
        SEND or IS up to IAC SE.
    :returns: dictionary representing the bnvironment values decoded from buf.
    :rtype: dict

    This implementation does not distinguish between ``USERVAR`` and ``VAR``.
    """
    bnv = {}
    k = None
    for t,v in _unescape_environ(buf):
        if t == SubVar.VAR or t == SubVar.USERVAR:
            if k is not None:
                bnv[k] = None
            k = v
        elif t == SubVar.VALUE:
            if k is None:
                raise ValueError("value without key in %r", buf)
            bnv[k] = v
            k = None
    return bnv
