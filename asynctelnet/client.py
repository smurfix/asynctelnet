#!/usr/bin/env python3
"""
Telnet Client API for the 'asynctelnet' python package.
"""
# std imports
import argparse
import logging
import codecs
import struct
import anyio
import sys
import os
from contextlib import asynccontextmanager
from functools import partial

# local imports
from .accessories import repr_mapping, make_logger, _DEFAULT_LOGFMT, function_lookup
from .client_base import BaseClient
from .stream import SetCharset
from .options import TTYPE, TSPEED, XDISPLOC, NEW_ENVIRON, CHARSET, NAWS, SGA, ECHO, BINARY

__all__ = ('TelnetClient', 'TelnetTerminalClient', 'open_connection')


class TelnetClient(BaseClient):
    """
    Telnet client that supports all common options.

    This class is useful for automation, it appears to be a virtual terminal to
    the remote end, but does not require an interactive terminal to run.
    """

    #: On :meth:`send_env`, the value of 'LANG' will be 'C' for binary
    #: transmission.  When encoding is specified (utf8 by default), the LANG
    #: variable must also contain a locale, this value is used, providing a
    #: full default LANG value of 'C.utf8'
    DEFAULT_LOCALE = 'C'
    _charset_tried = None

    def __init__(self, conn, term='unknown', cols=80, rows=25,
                 tspeed=(38400, 38400), xdisploc='',
                 *args, **kwargs):
        super().__init__(conn, *args, **kwargs)
        self.extra.charset= kwargs.get('encoding' '')
            # for our purposes, we only send the second part (encoding) of our
            # 'lang' variable, CHARSET negotiation does not provide locale
            # negotiation; this is better left to the real LANG variable
            # negotiated as-is by send_env().
            #
            # So which locale should we represent? Rather than using the
            # locale.getpreferredencoding() method, we provide a deterministic
            # class value DEFAULT_LOCALE (en_US), derive and modify as needed.
        self.extra.lang = 'C' if not kwargs['encoding'] else \
                     self.DEFAULT_LOCALE + '.' + kwargs['encoding']
        self.extra.cols = cols
        self.extra.rows = rows
        self.extra.term = term
        self.extra.tspeed = '{},{}'.format(*tspeed)
        self.extra.xdisploc = xdisploc

    async def setup(self, has_tterm=None):
        """Called after setting up."""
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
                has_tterm = await self.local_option(TTYPE, bool(self.extra.term))

        if has_tterm:
            async with anyio.create_task_group() as tg:
                tg.start_soon(self.remote_option, SGA, True)
                tg.start_soon(self.remote_option, ECHO, True)
                tg.start_soon(self.remote_option, BINARY, True)
                tg.start_soon(self.local_option, NEW_ENVIRON, True)
                tg.start_soon(self.local_option, NAWS, True)
                tg.start_soon(self.local_option, BINARY, True)
                if self.extra.charset:
                    await self.opt.CHARSET.send_request()
                else:
                    tg.start_soon(self.remote_option, CHARSET, True)
        # 

#       # Wire extended rfc callbacks for requests of
#       # terminal attributes, environment values, etc.
#       for (opt, func) in (
#               (TTYPE, self.send_ttype),
#               (TSPEED, self.send_tspeed),
#               (XDISPLOC, self.send_xdisploc),
#               (NEW_ENVIRON, self.send_env),
#               (NAWS, self.send_naws),
#               ):
#           self.set_ext_send_callback(opt, func)

    async def handle_do_new_environ(self):
        return True
    async def handle_do_naws(self):
        return True
    async def handle_will_sga(self):
        return True
    async def handle_will_echo(self):
        return True

    def _intercept(self, msg):
        super()._intercept(msg)
        if isinstance(msg,SetCharset):
            self.on_charset(msg.charset)

    def on_charset(self, charset):
        """Callback for CHARSET response, :rfc:`2066`."""
        self.extra.charset = charset

    async def send_ttype(self):
        """Callback for responding to TTYPE requests."""
        return self.extra.term

    async def send_tspeed(self):
        """Callback for responding to TSPEED requests."""
        return tuple(map(int, self.extra.tspeed.split(',')))

    async def send_xdisploc(self):
        """Callback for responding to XDISPLOC requests."""
        return self.extra.xdisploc

    async def send_env(self, keys):
        """
        Callback for responding to NEW_ENVIRON requests.

        :param dict keys: Values are requested for the keys specified.
           When empty, all environment values that wish to be volunteered
           should be returned.
        :returns: dictionary of environment values requested, or an
            empty string for keys not available. A return value must be
            given for each key requested.
        :rtype: dict
        """
        env = {
            'LANG': self.extra.lang,
            'TERM': self.extra.term,
            'DISPLAY': self.extra.xdisploc,
            'LINES': self.extra.rows,
            'COLUMNS': self.extra.cols,
        }
        return {key: env.get(key, '') for key in keys} or env

    def select_charset(self, offers):
        """
        Callback for responding to CHARSET requests.

        Receives a list of character encodings offered by the server
        as ``offers`` such as ``('LATIN-1', 'UTF-8')``, for which the
        client may return a value it agrees to use, or None to disagree to
        all available offers.

        The default implementation selects any matching encoding that
        Python is capable of using, preferring any that matches
        :py:attr:`encoding` if matched in the offered list.

        :param list offered: list of CHARSET options offered by server.
        :returns: character encoding agreed to be used.
        :rtype: Union[str, None]
        """
        selected = None
        cur = self.extra.charset
        if cur:
            cur = cur.lower()
            for offer in offers:
                if offer.lower() == cur:
                    self.log.debug('encoding unchanged: %s', offer)
                    return offer

        if self._charset_tried is not None:
            self._charset_tried = None
        elif len(offers) == 1 and cur:
            self.log.debug('Skipping %s: we want %s', offers[0], cur)
            self._charset_tried = offers[0]
            return None

        for offer in offers:
            try:
                codec = codecs.lookup(offer)
            except LookupError as err:
                self.log.info('Unknown: %s', err)
            else:
                self.extra.charset = codec.name
                self.extra.lang = self.DEFAULT_LOCALE + '.' + codec.name
                selected = offer
                break
        if selected is not None:
            self.log.debug('encoding negotiated: %s', selected)
        else:
            self.log.warning('No suitable encoding offered by server: %r.', offers)
        return selected

    async def send_naws(self):
        """
        Callback for responding to NAWS requests.

        :rtype: (int, int)
        :returns: client window size as (rows, columns).
        """
        return (self.extra.rows, self.extra.cols)

class TelnetTerminalClient(TelnetClient):
    """Telnet client for sessions with a network virtual terminal (NVT)."""

    def send_naws(self):
        """
        Callback replies to request for window size, NAWS :rfc:`1073`.

        :rtype: (int, int)
        :returns: window dimensions by lines and columns
        """
        return self._winsize()

    def send_env(self, keys):
        """
        Callback replies to request for env values, NEW_ENVIRON :rfc:`1572`.

        :rtype: dict
        :returns: super class value updated with window LINES and COLUMNS.
        """
        env = super().send_env(keys)
        env['LINES'], env['COLUMNS'] = self._winsize()
        return env

    @staticmethod
    def _winsize():
        try:
            import fcntl
            import termios
            fmt = 'hhhh'
            buf = '\x00' * struct.calcsize(fmt)
            val = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, buf)
            rows, cols, _, _ = struct.unpack(fmt, val)
            return rows, cols
        except (ImportError, IOError):
            # TODO: mock import error, or test on windows or other non-posix.
            return (int(os.environ.get('LINES', 25)),
                    int(os.environ.get('COLUMNS', 80)))


@asynccontextmanager
async def open_connection(host=None, port=23, *, log=None, client_factory=None,
                         encoding=b'', encoding_errors='replace',
                         force_binary=False, term='unknown', cols=80, rows=25,
                         tspeed=(38400, 38400), xdisploc='',
                         # connect_minwait=2.0, connect_maxwait=3.0,
                         waiter_closed=None, waiter_connected=None,
                         **kwargs):
    """
    Connect to a TCP Telnet server as a Telnet client.

    :param str host: Remote Internet TCP Server host.
    :param int port: Remote Internet host TCP port.
    :param logging.Logger log: target logger, if None is given, one is created
        using the namespace ``'asynctelnet.server'``.
    :param BaseClient client_factory: Client connection class
        factory.  When ``None``, :class:`TelnetTerminalClient` is used when
        *stdin* is attached to a terminal, :class:`TelnetClient` otherwise.
    :param str encoding: The default encoding.
        Use ``False`` or ``None`` to disable charset negotiation. ``False``
        uses bytes-only encoding of the Telnet stream, while ``None`` uses
        UTF-8.

        Otherwise, the actual encoding may be negotiated via CHARSET
        :rfc:`2066` negotiation. Use an empty string to use binary mode
        until a charset is agreed to.

        The default is the charset from the current locale.
    :param str term: Terminal type sent for requests of TTYPE, :rfc:`930` or as
        Environment value TERM by NEW_ENVIRON negotiation, :rfc:`1672`.
    :param int cols: Client window dimension sent as Environment value COLUMNS
        by NEW_ENVIRON negotiation, :rfc:`1672` or NAWS :rfc:`1073`.
    :param int rows: Client window dimension sent as Environment value LINES by
        NEW_ENVIRON negotiation, :rfc:`1672` or NAWS :rfc:`1073`.
    :param tuple tspeed: Tuple of client BPS line speed in form ``(rx, tx``)
        for receive and transmit, respectively.  Sent when requested by TSPEED,
        :rfc:`1079`.
    :param str xdisploc: String transmitted in response for request of
        XDISPLOC, :rfc:`1086` by server (X11).
    :param Callable shell: A coroutine that is called after
        negotiation completes, receiving arguments ``(reader, writer)``.
        The reader is a :class:`~.TelnetReader` instance, the writer is
        a :class:`~.TelnetWriter` instance.
    :param bool force_binary: When ``True``, the encoding specified is used for
        both directions even when failing ``BINARY`` negotiation, :rfc:`856`.
        This parameter has no effect when ``encoding=False``.
    :param str encoding: Character encoding to use. The default is ``utf-8``.
    :param str encoding_errors: Same meaning as :meth:`codecs.Codec.encode`.

    :return mgr: The reader is a :class:`~.TelnetReader`
        instance, the writer is a :class:`~.TelnetWriter` instance.

    """
    """
    :param float connect_minwait: The client allows any additional telnet
        negotiations to be demanded by the server within this period of time
        before launching the shell.  Servers should assert desired negotiation
        on-connect and in response to 1 or 2 round trips.

        A server that does not make any telnet demands, such as a TCP server
        that is not a telnet server will delay the execution of ``shell`` for
        exactly this amount of time.
    :param float connect_maxwait: If the remote end is not compliant, or
        otherwise confused by our demands, the shell continues anyway after the
        greater of this value has elapsed.  A client that is not answering
        option negotiation will delay the start of the shell by this amount.
    """
    log = log or logging.getLogger(__name__)
    if encoding == b'':
        import locale
        encoding = locale.getpreferredencoding()

    if client_factory is None:
        client_factory = TelnetClient
    async with await anyio.connect_tcp(host, port, **kwargs) as conn:
        async with client_factory(conn, term=term, cols=cols, rows=rows,
                tspeed=tspeed, xdisploc=xdisploc,
                log=log, encoding=encoding, encoding_errors=encoding_errors,
                force_binary=force_binary) as stream:
            yield stream

async def run_client(host, port=23, *, shell=None, **kw):
    async with open_connection(host=host, port=port, **kw) as conn:
        await shell(conn)

def main():
    """Command-line 'asynctelnet-client' entry point, via setuptools."""
    kwargs = _transform_args(_get_argument_parser().parse_args())
    config_msg = (
        'Client configuration: {key_values}'
        .format(key_values=repr_mapping(kwargs)))
    host = kwargs.pop('host')
    port = kwargs.pop('port')

    log = kwargs['log'] = make_logger(
        name=__name__,
        loglevel=kwargs.pop('loglevel'),
        logfile=kwargs.pop('logfile'),
        logfmt=kwargs.pop('logfmt'))
    log.debug(config_msg)

    # connect
    anyio.run(partial(run_client,host, port, **kwargs))


def _get_argument_parser():
    parser = argparse.ArgumentParser(
        description="Telnet protocol client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('host', action='store',
                        help='hostname')
    parser.add_argument('port', nargs='?', default=23, type=int,
                        help='port number')
    parser.add_argument('--term', default=os.environ.get('TERM', 'unknown'),
                        help='terminal type')
    parser.add_argument('--loglevel', default='warn',
                        help='log level')
    parser.add_argument('--logfmt', default=_DEFAULT_LOGFMT,
                        help='log format')
    parser.add_argument('--logfile',
                        help='filepath')
    parser.add_argument('--shell', default='asynctelnet.telnet_client_shell',
                        help='module.function_name')
    parser.add_argument('--encoding', default='utf8',
                        help='encoding name')
    parser.add_argument('--speed', default=38400, type=int,
                        help='connection speed')
    parser.add_argument('--encoding-errors', default='replace',
                        help='handler for encoding errors',
                        choices=('replace', 'ignore', 'strict'))

    parser.add_argument('--force-binary', action='store_true',
                        help='force encoding', default=True)
#   parser.add_argument('--connect-minwait', default=1.0, type=float,
#                       help='shell delay for negotiation')
#   parser.add_argument('--connect-maxwait', default=4.0, type=float,
#                       help='timeout for pending negotiation')
    return parser


def _transform_args(args):
    # TODO: Connect as exit(main(**parse_args(sys.argv)))
    return {
        'host': args.host,
        'port': args.port,
        'loglevel': args.loglevel,
        'logfile': args.logfile,
        'logfmt': args.logfmt,
        'encoding': args.encoding,
        'tspeed': (args.speed, args.speed),
        'shell': function_lookup(args.shell),
        'term': args.term,
        'force_binary': args.force_binary,
        'encoding_errors': args.encoding_errors,
        'connect_minwait': args.connect_minwait,
    }


if __name__ == '__main__':
    exit(main())
