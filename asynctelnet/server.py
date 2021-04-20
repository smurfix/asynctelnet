"""
The ``main`` function here is wired to the command line tool by name
asynctelnet-server.  If this server's PID receives the SIGTERM signal, it
attempts to shutdown gracefully.

The :class:`TelnetServer` class negotiates a character-at-a-time (WILL-SGA,
WILL-ECHO) session with support for negotiation about window size, environment
variables, terminal type name, and to automatically close connections clients
after an idle period.
"""
# std imports
import collections
import argparse
import asyncio
import logging
import signal
import anyio
from weakref import proxy
from contextlib import asynccontextmanager
from functools import partial

# local
from .server_base import BaseServer
from .accessories import function_lookup, _DEFAULT_LOGFMT, make_logger
from .stream import SetCharset
from .options import NAWS, NEW_ENVIRON, TTYPE, CHARSET, SGA, ECHO, BINARY
from .telopt import SEND


__all__ = ('TelnetServer', 'server_loop', 'run_server', 'parse_server_args')

CONFIG = collections.namedtuple('CONFIG', [
    'host', 'port', 'loglevel', 'logfile', 'logfmt', 'shell', 'encoding',
    'force_binary', 'timeout'])(
        host='localhost', port=6023, loglevel='info',
        logfile=None, logfmt=_DEFAULT_LOGFMT ,
        shell=function_lookup('asynctelnet.telnet_server_shell'),
        encoding='utf8', force_binary=False, timeout=300)


class TelnetServer(BaseServer):
    """Telnet Server protocol performing common negotiation."""
    #: Maximum number of cycles to seek for all terminal types.  We are seeking
    #: the repeat or cycle of a terminal table, choosing the first -- but when
    #: negotiated by MUD clients, we chose the must Unix TERM appropriate,
    TTYPE_LOOPMAX = 8

    # Derived methods from base class

    def __init__(self, stream, term='unknown', cols=80, rows=25, timeout=300,
                 *args, **kwargs):
        super().__init__(stream, *args, **kwargs)
        self._ttype_count = 1
        self._timer = None

        self.extra.term = term
        self.extra.term_done = False
        self.extra.charset = kwargs.get('encoding', '')
        self.extra.cols = cols
        self.extra.rows = rows
        self.extra.timeout = timeout

    async def setup(self, has_tterm=None):
        self.opt.add(TTYPE)
        self.opt.add(SGA)
        self.opt.add(ECHO)
        self.opt.add(BINARY)
        self.opt.add(NEW_ENVIRON)
        self.opt.add(NAWS)
        self.opt.add(CHARSET)

        await super().setup()

        # No terminal? don't try.
        if not isinstance(has_tterm, bool):
            with anyio.fail_after(has_tterm):
                has_tterm = await self.remote_option(TTYPE, True)

        if has_tterm:
            async with anyio.create_task_group() as tg:
                tg.start_soon(self.local_option, SGA, True)
                tg.start_soon(self.local_option, ECHO, True)
                tg.start_soon(self.local_option, BINARY, True)
                tg.start_soon(self.remote_option, NEW_ENVIRON, True)
                tg.start_soon(self.remote_option, NAWS, True)
                tg.start_soon(self.remote_option, BINARY, True)
                if isinstance(self.extra.charset, str):
                    if self.extra.charset:
                        # We have a charset we want to use. Send WILL.
                        await self.request_charset()
                    else:
                        # We don't have a charset we want to use. Ask the
                        # remote to send us a list.
                        tg.start_soon(self.remote_option, CHARSET, True)

        # TODO request environment

        # prefer 'LANG' environment variable forwarded by client, if any.
        # for modern systems, this is the preferred method of encoding
        # negotiation.
        #_lang = self.extra.get('LANG', '')
        #if _lang:
        #    return encoding_from_lang(_lang)

        # otherwise, the less CHARSET negotiation may be found in many
        # East-Asia BBS and Western MUD systems.
        #return self.extra.charset or self.default_encoding

    async def handle_will_new_environ(self):
        return True
    async def handle_will_naws(self):
        return True
    async def handle_do_sga(self):
        return True
    async def handle_do_echo(self):
        return True

    @asynccontextmanager
    async def with_timeout(self, duration=-1):
        """
        Restart or unset timeout for client.

        :param int duration: When specified as a positive integer,
            schedules Future for callback of :meth:`on_timeout`.  When ``-1``,
            the value of ``self.extra.timeout`` is used.  When
            non-True, it is canceled.
        """
        if duration == -1:
            duration = self.extra.timeout
        if duration > 0:
            with anyio.move_on_after(duration) as sc:
                yield sc
        else:
            yield None

    def on_naws(self, rows, cols):
        """
        Callback receives NAWS response, :rfc:`1073`.

        :param int rows: screen size, by number of cells in height.
        :param int cols: screen size, by number of cells in width.
        """
        self.extra.rows = rows
        self.extra.cols = cols

    def on_request_environ(self):
        """
        Definition for NEW_ENVIRON request of client, :rfc:`1572`.

        This method is a callback from :meth:`~.TelnetWriter.request_environ`,
        first entered on receipt of (WILL, NEW_ENVIRON) by server.  The return
        value *defines the request made to the client* for environment values.

        :rtype list: a list of unicode character strings of US-ASCII
            characters, indicating the environment keys the server requests
            of the client.  If this list contains the special byte constants,
            ``USERVAR`` or ``VAR``, the client is allowed to volunteer any
            other additional user or system values.

            Any empty return value indicates that no request should be made.

        The default return value is::

            ['LANG', 'TERM', 'COLUMNS', 'LINES', 'DISPLAY', 'COLORTERM',
             VAR, USERVAR, 'COLORTERM']
        """
        from .telopt import VAR, USERVAR
        return ['LANG', 'TERM', 'COLUMNS', 'LINES', 'DISPLAY', 'COLORTERM',
                VAR, USERVAR]

    def on_environ(self, mapping):
        """Callback receives NEW_ENVIRON response, :rfc:`1572`."""
        # A well-formed client responds with empty values for variables to
        # mean "no value".  They might have it, they just may not wish to
        # divulge that information.  We pop these keys as a side effect in
        # the result statement of the following list comprehension.
        no_value = [mapping.pop(key) or key
                    for key, val in list(mapping.items())
                    if not val]

        # because we are working with "untrusted input", we make one fair
        # distinction: all keys received by NEW_ENVIRON are in uppercase.
        # this ensures a client may not override trusted values such as
        # 'peer'.
        u_mapping = {key.upper(): val for key, val in list(mapping.items())}

        self.log.debug('on_environ received: {0!r}'.format(u_mapping))

        self.extra.update(u_mapping)

    def _intercept(self, msg):
        super()._intercept(msg)
        if isinstance(msg,SetCharset):
            self.on_charset(msg.charset)

    def on_charset(self, charset):
        """Callback for CHARSET response, :rfc:`2066`."""
        self.extra.charset = charset

    async def handle_recv_tspeed(self, rx, tx):
        """Callback for TSPEED response, :rfc:`1079`."""
        self.extra.tspeed = '{0},{1}'.format(rx, tx)

    def on_xdisploc(self, xdisploc):
        """Callback for XDISPLOC response, :rfc:`1096`."""
        self.extra.xdisploc = xdisploc


async def server_loop(host=None, port=23, evt=None, protocol_factory=TelnetServer, shell=None, log=None, **kwds):
    """
    Run a TCP Telnet server.

    :param str host: The host parameter can be a string, in that case the TCP
        server is bound to host and port. The host parameter can also be a
        sequence of strings, and in that case the TCP server is bound to all
        hosts of the sequence.
    :param int port: listen port for TCP Server.
    :param server_base.BaseServer protocol_factory: An alternate protocol
        factory for the server, when unspecified, :class:`TelnetServer` is
        used.

    :param Callable shell: A coroutine that is called after
        negotiation completes, receiving the Telnet stream as an argument.
    :param logging.Logger log: target logger, if None is given, one is created
        using the namespace ``'asynctelnet.server'``.
    :param str encoding: The default encoding.
        Use ``False`` or ``None`` to disable charset negotiation. ``False``
        uses bytes-only encoding of the Telnet stream, while ``None`` uses
        UTF-8.

        Otherwise, the actual encoding may be negotiated via CHARSET
        :rfc:`2066` negotiation. Use an empty string to use binary mode
        until a charset is agreed to.
    :param str encoding_errors: Same meaning as :meth:`codecs.Codec.encode`.
        Default value is ``strict``.
    :param bool force_binary: When ``True``, the encoding specified is
        used for both directions even when BINARY mode, :rfc:`856`, is not
        negotiated for the direction specified.  This parameter has no effect
        when ``encoding=None``.
    :param str term: Value returned for ``writer.extra.term``
        until negotiated by TTYPE :rfc:`930`, or NAWS :rfc:`1572`.  Default value
        is ``'unknown'``.
    :param int cols: Value returned for ``writer.extra.cols``
        until negotiated by NAWS :rfc:`1572`. Default value is 80 columns.
    :param int rows: Value returned for ``writer.extra.rows``
        until negotiated by NAWS :rfc:`1572`. Default value is 25 rows.

    This method does not return until cancelled.
    """
    """
    :param float connect_maxwait: If the remote end is not compliant, or
        otherwise confused by our demands, the shell continues anyway after the
        greater of this value has elapsed.  A client that is not answering
        option negotiation will delay the start of the shell by this amount.
    """

    protocol_factory = protocol_factory or TelnetServer
    l = await anyio.create_tcp_listener(local_host=host, local_port=port)
    log = log or logging.getLogger(__name__)
    if shell is None:
        async def shell(_s):
            while True:
                await anyio.sleep(99999)
    async def serve(s):
        async with protocol_factory(s, log=log, **kwds) as stream:
            await shell(stream)

    log.info('Server ready on {0}:{1}'.format(host, port))
    if evt is not None:
        evt.set()
    await l.serve(serve)


async def _sigterm_handler(server, log):
    log.info('SIGTERM received, closing server.')

    # This signals the completion of the server.wait_closed() Future,
    # allowing the main() function to complete.
    server.close()


def parse_server_args():
    parser = argparse.ArgumentParser(
        description="Telnet protocol server",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('host', nargs='?', default=CONFIG.host,
                        help='bind address')
    parser.add_argument('port', nargs='?', type=int, default=CONFIG.port,
                        help='bind port')
    parser.add_argument('--loglevel', default=CONFIG.loglevel,
                        help='level name')
    parser.add_argument('--logfile', default=CONFIG.logfile,
                        help='filepath')
    parser.add_argument('--logfmt', default=CONFIG.logfmt,
                        help='log format')
    parser.add_argument('--shell', default=CONFIG.shell,
                        type=function_lookup,
                        help='module.function_name')
    parser.add_argument('--encoding', default=CONFIG.encoding,
                        help='encoding name')
    parser.add_argument('--force-binary', action='store_true',
                        default=CONFIG.force_binary,
                        help='force binary transmission')
    parser.add_argument('--timeout', default=CONFIG.timeout,
                        help='idle disconnect (0 disables)')
#   parser.add_argument('--connect-maxwait', type=float,
#                       default=CONFIG.connect_maxwait,
#                       help='timeout for pending negotiation')
    return vars(parser.parse_args())


def run_server(host=CONFIG.host, port=CONFIG.port, loglevel=CONFIG.loglevel,
               logfile=CONFIG.logfile, logfmt=CONFIG.logfmt,
               shell=CONFIG.shell, encoding=CONFIG.encoding,
               force_binary=CONFIG.force_binary, timeout=CONFIG.timeout,
#              connect_maxwait=CONFIG.connect_maxwait
                ):
    """
    Program entry point for server daemon.

    This function configures a logger and creates a telnet server for the
    given keyword arguments, serving forever, completing only upon receipt of
    SIGTERM.
    """
    log = make_logger(
        name=__name__,
        loglevel=loglevel,
        logfile=logfile,
        logfmt=logfmt)

    anyio.run(partial(
        server_loop, host, port, shell=shell, encoding=encoding,
                      force_binary=force_binary, timeout=timeout, log=log))


    # await completion of server stop
    try:
        loop.run_until_complete(server.wait_closed())
    finally:
        # remove signal handler on stop
        loop.remove_signal_handler(signal.SIGTERM)

    log.info('Server stop.')


def main():
    """Command-line 'asynctelnet-server' entry point, via setuptools."""
    return run_server(**parse_server_args())


if __name__ == '__main__':
    exit(main())
