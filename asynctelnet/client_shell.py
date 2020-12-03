# std imports
import collections
import contextlib
import logging
import codecs
import sys

# local
from . import accessories

__all__ = ('telnet_client_shell', )


# TODO: needs 'wait_for' implementation (see DESIGN.rst)
# task = telnet_writer.wait_for(lambda: telnet_writer.local_mode[ECHO] == True)

if sys.platform == 'win32':
    raise NotImplementedError(
        'win32 not yet supported as telnet client. Please contribute!')

import termios
import os
import anyio
import fcntl

from .stream import ReadCallback
from .telopt import WILL,WONT, ECHO

class TerminalStream(anyio.abc.ByteStream):
    """
    Context manager that yields a non-blocking stdin+stdout stream.

    When sys.stdin is a attached to a terminal, it is configured for
    the telnet mode negotiated. The caller is responsible for setting
    these as appropriate.

    This class *must* be used as a context manager.
    It will attach to stdin/stdout and modify TTY raw mode as appropriate.
    """
    _orig_fl = None

    _ModeDef = collections.namedtuple(
        'mode', ['iflag', 'oflag', 'cflag', 'lflag',
                    'ispeed', 'ospeed', 'cc'])

    charset = "utf-8"
    _decoder = codecs.getincrementaldecoder(charset)()
    _encoder = "utf-8"
    keyboard_escape = b'\x1d'

    def __init__(self, will_echo=True, keyboard_escape=None):
        self._fileno = sys.stdin.fileno()
        self._istty = os.path.sameopenfile(0, 1)
        self._will_echo = will_echo
        if keyboard_escape is not None:
            self.keyboard_escape = keyboard_escape

    async def __aenter__(self):
        await super().__aenter__()
        if self._istty:
            self._saved_mode = self._ModeDef(*termios.tcgetattr(self._fileno))
            self._set_mode()
            self._orig_fl = fcntl.fcntl(self._fileno, fcntl.F_GETFL)
            fcntl.fcntl(self._fileno, fcntl.F_SETFL, self._orig_fl | os.O_NONBLOCK)
        return self

    async def __aexit__(self, *tb):
        self._close()
        await super().__aexit__(*tb)

    def _close(self):
        if self._istty and self._orig_fl is not None:
            fcntl.fcntl(self._fileno, fcntl.F_SETFL, self._orig_fl)
            termios.tcsetattr(
                self._fileno, termios.TCSAFLUSH, list(self._saved_mode))
            self._orig_fl = None

    async def aclose(self):
        self._close()

    async def send_eof():
        pass

    def _set_mode(self):
        termios.tcsetattr(
            sys.stdin.fileno(), termios.TCSAFLUSH, list(self._wanted_mode))

    @property
    def will_echo(self):
        return self._will_echo

    @will_echo.setter
    def will_echo(self, value):
        self._will_echo = value
        if self._istty:
            self._set_mode()

    def fileno(self):
        return self._fileno

    @property
    def _wanted_mode(self):
        """
        Return copy of 'mode' with changes suggested for telnet connection.
        """
        from asynctelnet.telopt import ECHO

        mode = self._saved_mode
        if not self._will_echo:
            # return mode as-is
            return mode

        # "Raw mode", see tty.py function setraw.  This allows sending
        # of ^J, ^C, ^S, ^\, and others, which might otherwise
        # interrupt with signals or map to another character.  We also
        # trust the remote server to manage CR/LF without mapping.
        #
        iflag = mode.iflag & ~(
            termios.BRKINT |  # Do not send INTR signal on break
            termios.ICRNL  |  # Do not map CR to NL on input
            termios.INPCK  |  # Disable input parity checking
            termios.ISTRIP |  # Do not strip input characters to 7 bits
            termios.IXON)     # Disable START/STOP output control

        # Disable parity generation and detection,
        # Select eight bits per byte character size.
        cflag = mode.cflag & ~(termios.CSIZE | termios.PARENB)
        cflag = cflag | termios.CS8

        # Disable canonical input (^H and ^C processing),
        # disable any other special control characters,
        # disable checking for INTR, QUIT, and SUSP input.
        lflag = mode.lflag & ~(
            termios.ICANON | termios.IEXTEN | termios.ISIG | termios.ECHO)

        # Disable post-output processing,
        # such as mapping LF('\n') to CRLF('\r\n') in output.
        oflag = mode.oflag & ~(termios.OPOST | termios.ONLCR)

        # "A pending read is not satisfied until MIN bytes are received
        #  (i.e., the pending read until MIN bytes are received), or a
        #  signal is received.  A program that uses this case to read
        #  record-based terminal I/O may block indefinitely in the read
        #  operation."
        cc = list(mode.cc)
        cc[termios.VMIN] = 1
        cc[termios.VTIME] = 0

        return self._ModeDef(
            iflag=iflag, oflag=oflag, cflag=cflag, lflag=lflag,
            ispeed=mode.ispeed, ospeed=mode.ospeed, cc=cc)

    async def receive(self, max_bytes=1024):
        while True:
            await anyio.wait_socket_readable(self)
            inp = os.read(self._fileno, max_bytes)
            if self.keyboard_escape in inp:
                # on ^], close connection to remote host
                raise EOFError
            inp = self._decoder.decode(inp)
            if inp:
                return inp

    async def send(self, item):
        if isinstance(item,str):
            item = item.encode(self.charset)
        while len(item):
            await anyio.wait_socket_writable(self)
            done = os.write(self._fileno, item)
            item = item[done:]


async def telnet_client_shell(telnet_stream):
    """
    Minimal telnet client shell for POSIX terminals.

    This shell performs minimal tty mode handling when a terminal is
    attached to standard in (keyboard), notably raw mode is often set
    and this shell may exit only by disconnect from server, or the
    escape character, ^].

    stdin or stdout may also be a pipe or file, behaving much like nc(1).

    """

    class TerminalUpdater(ReadCallback):
        def __init__(self,val):
            super().__init__()
            self.val=val
        async def run(self):
            term.will_echo = self.val

    async def _handle_will_echo():
        telnet_stream.queue_read_callback(TerminalUpdater(True))
        return True

    async def _handle_wont_echo():
        telnet_stream.queue_read_callback(TerminalUpdater(False))
        return False

    async with anyio.create_task_group() as tg, \
            TerminalStream(will_echo=telnet_stream.will_echo) as term :
        telnet_stream.set_command_handler(WILL,ECHO, _handle_will_echo)
        telnet_stream.set_command_handler(WONT,ECHO, _handle_wont_echo)

        linesep = '\n'
        if term._istty and term.will_echo:
            linesep = '\r\n'
        await term.send("Escape character is '{escape}'.{linesep}".format(
            escape=accessories.name_unicode(term.keyboard_escape),
            linesep=linesep).encode())

        async def read_stdin():
            while True:
                inp = await term.receive()
                if not inp:
                    break
                if inp:
                    inp = inp.replace('\n','\r\n').replace('\r\r\n','\r\n')
                await telnet_stream.send(inp)

        async def read_telnet():
            while True:
                try:
                    out = await telnet_stream.receive()
                except anyio.EndOfStream:
                    await term.send(f"\033[m{linesep}Connection closed by foreign host.{linesep}".encode())
                    await tg.cancel_scope.cancel()
                    return
                except anyio.ClosedResourceError: 
                    return
                else:
                    await term.send(out)

        await tg.spawn(read_stdin)
        await tg.spawn(read_telnet)
