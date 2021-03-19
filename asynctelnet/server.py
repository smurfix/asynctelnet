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
from . import server_base
from . import accessories

__all__ = ('TelnetServer', 'server_loop', 'run_server', 'parse_server_args')

CONFIG = collections.namedtuple('CONFIG', [
    'host', 'port', 'loglevel', 'logfile', 'logfmt', 'shell', 'encoding',
    'force_binary', 'timeout'])(
        host='localhost', port=6023, loglevel='info',
        logfile=None, logfmt=accessories._DEFAULT_LOGFMT ,
        shell=accessories.function_lookup('asynctelnet.telnet_server_shell'),
        encoding='utf8', force_binary=False, timeout=300)


class TelnetServer(server_base.BaseServer):
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
        self._extra = {
            'term': term,
            'charset': kwargs.get('encoding', ''),
            'cols': cols,
            'rows': rows,
            'timeout': timeout
        }

    @property
    def extra_attributes(self):
        res = super().extra_attributes
        for k in self._extra.keys(): 
            def fn(k):
                return lambda: self._extra[k] 
            res[k] = fn(k)
        return res

    async def setup(self):
        from .telopt import NAWS, NEW_ENVIRON, TSPEED, TTYPE, XDISPLOC, CHARSET
        await super().setup()

        # begin timeout timer
#       async with self.with_timeout():

#           # Wire extended rfc callbacks for responses to
#           # requests of terminal attributes, environment values, etc.
#           for tel_opt, callback_fn in [
#               (NAWS, self.on_naws),
#               (NEW_ENVIRON, self.on_environ),
#               (TSPEED, self.on_tspeed),
#               (TTYPE, self.on_ttype),
#               (XDISPLOC, self.on_xdisploc),
#               (CHARSET, self.on_charset),
#           ]:
#               self.writer.set_ext_callback(tel_opt, callback_fn)

#           # Wire up a callbacks that return definitions for requests.
#           for tel_opt, callback_fn in [
#               (NEW_ENVIRON, self.on_request_environ),
#               (CHARSET, self.on_request_charset),
#           ]:
#               self.writer.set_ext_send_callback(tel_opt, callback_fn)


        from .telopt import (DO, WILL, SGA, ECHO, BINARY, TTYPE, 
                             NEW_ENVIRON, NAWS, CHARSET)
        # No terminal? don't try.
        if await self.remote_option(TTYPE, True):
            async with anyio.create_task_group() as tg:
                await tg.spawn(self.local_option,SGA,True)
                await tg.spawn(self.local_option,ECHO,True)
                await tg.spawn(self.local_option,BINARY,True)
                await tg.spawn(self.remote_option,NEW_ENVIRON,True)
                await tg.spawn(self.remote_option,NAWS,True)
                await tg.spawn(self.remote_option,BINARY,True)
                await tg.spawn(self.request_charset("UTF-8"))

        # TODO request environment

        # prefer 'LANG' environment variable forwarded by client, if any.
        # for modern systems, this is the preferred method of encoding
        # negotiation.
        #_lang = self.get_extra_info('LANG', '')
        #if _lang:
        #    return accessories.encoding_from_lang(_lang)

        # otherwise, the less CHARSET negotiation may be found in many
        # East-Asia BBS and Western MUD systems.
        #return self.get_extra_info('charset') or self.default_encoding

    @asynccontextmanager
    async def with_timeout(self, duration=-1):
        """
        Restart or unset timeout for client.

        :param int duration: When specified as a positive integer,
            schedules Future for callback of :meth:`on_timeout`.  When ``-1``,
            the value of ``self.get_extra_info('timeout')`` is used.  When
            non-True, it is canceled.
        """
        if duration == -1:
            duration = self.get_extra_info('timeout')
        if duration > 0:
            async with anyio.move_on_after(duration) as sc:
                yield sc
        else:
            yield None

    def on_naws(self, rows, cols):
        """
        Callback receives NAWS response, :rfc:`1073`.

        :param int rows: screen size, by number of cells in height.
        :param int cols: screen size, by number of cells in width.
        """
        self._extra.update({'rows': rows, 'cols': cols})

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

        self._extra.update(u_mapping)

    def on_request_charset(self):
        """
        Definition for CHARSET request by client, :rfc:`2066`.

        This method is a callback from :meth:`~.TelnetWriter.request_charset`,
        first entered on receipt of (WILL, CHARSET) by server.  The return
        value *defines the request made to the client* for encodings.

        :rtype list: a list of unicode character strings of US-ASCII
            characters, indicating the encodings offered by the server in
            its preferred order.

            Any empty return value indicates that no encodings are offered.

        The default return value begins::

            ['UTF-8', 'UTF-16', 'LATIN1', 'US-ASCII', 'BIG5', 'GBK', ...]
        """
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

    def on_charset(self, charset):
        """Callback for CHARSET response, :rfc:`2066`."""
        self._extra['charset'] = charset

    def on_tspeed(self, rx, tx):
        """Callback for TSPEED response, :rfc:`1079`."""
        self._extra['tspeed'] = '{0},{1}'.format(rx, tx)

    def on_ttype(self, ttype):
        """Callback for TTYPE response, :rfc:`930`."""
        # TTYPE may be requested multiple times, we honor this system and
        # attempt to cause the client to cycle, as their first response may
        # not be their most significant. All responses held as 'ttype{n}',
        # where {n} is their serial response order number.
        #
        # The most recently received terminal type by the server is
        # assumed TERM by this implementation, even when unsolicited.
        key = 'ttype{}'.format(self._ttype_count)
        self._extra[key] = ttype
        if ttype:
            self._extra['TERM'] = ttype

        _lastval = self.get_extra_info('ttype{0}'.format(
            self._ttype_count - 1))

        if key != 'ttype1' and ttype == self.get_extra_info('ttype1', None):
            # cycle has looped, stop
            self.log.debug('ttype cycle stop at {0}: {1}, looped.'
                           .format(key, ttype))

        elif (not ttype or self._ttype_count > self.TTYPE_LOOPMAX):
            # empty reply string or too many responses!
            self.log.warning('ttype cycle stop at {0}: {1}.'.format(key, ttype))

        elif (self._ttype_count == 3 and ttype.upper().startswith('MTTS ')):
            val = self.get_extra_info('ttype2')
            self.log.debug(
                'ttype cycle stop at {0}: {1}, using {2} from ttype2.'
                .format(key, ttype, val))
            self._extra['TERM'] = val

        elif (ttype == _lastval):
            self.log.debug('ttype cycle stop at {0}: {1}, repeated.'
                           .format(key, ttype))

        else:
            self.log.debug('ttype cycle cont at {0}: {1}.'
                           .format(key, ttype))
            self._ttype_count += 1
            self.writer.request_ttype()

    def on_xdisploc(self, xdisploc):
        """Callback for XDISPLOC response, :rfc:`1096`."""
        self._extra['xdisploc'] = xdisploc


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
    :param str encoding: The default assumed encoding, or ``False`` to disable
        unicode support.  Encoding may be negotiation to another value by
        the client through NEW_ENVIRON :rfc:`1572` by sending environment value
        of ``LANG``, or by any legal value for CHARSET :rfc:`2066` negotiation.

        The server's stream accepts and returns Unicode, unless this value
        is explicitly set to ``None``.  In that case, the attached stream
        interface is bytes-only.
    :param str encoding_errors: Same meaning as :meth:`codecs.Codec.encode`.
        Default value is ``strict``.
    :param bool force_binary: When ``True``, the encoding specified is
        used for both directions even when BINARY mode, :rfc:`856`, is not
        negotiated for the direction specified.  This parameter has no effect
        when ``encoding=None``.
    :param str term: Value returned for ``writer.get_extra_info('term')``
        until negotiated by TTYPE :rfc:`930`, or NAWS :rfc:`1572`.  Default value
        is ``'unknown'``.
    :param int cols: Value returned for ``writer.get_extra_info('cols')``
        until negotiated by NAWS :rfc:`1572`. Default value is 80 columns.
    :param int rows: Value returned for ``writer.get_extra_info('rows')``
        until negotiated by NAWS :rfc:`1572`. Default value is 25 rows.
    :param float connect_maxwait: If the remote end is not compliant, or
        otherwise confused by our demands, the shell continues anyway after the
        greater of this value has elapsed.  A client that is not answering
        option negotiation will delay the start of the shell by this amount.

    This method does not return until cancelled.
    """
    protocol_factory = protocol_factory or TelnetServer
    l = await anyio.create_tcp_listener(local_host=host, local_port=port)
    if shell is None:
        async def shell(_s):
            while True:
                await anyio.sleep(99999)
    async def serve(s):
        async with protocol_factory(s, log=log, **kwds) as stream:
            await shell(stream)

    if log is not None:
        log.info('Server ready on {0}:{1}'.format(host, port))
    if evt is not None:
        await evt.set()
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
                        type=accessories.function_lookup,
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
    log = accessories.make_logger(
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
