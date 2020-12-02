"""Module provides class BaseServer."""

import traceback
import anyio
import logging
import datetime
import weakref
import sys

from .stream import TelnetStream
from anyio.streams.text import TextStream

__all__ = ('BaseServer',)


class BaseServer(TelnetStream):
    """Base Telnet Server Protocol."""
    _stream_factory = TelnetStream
    _stream_factory_wrapper = TextStream

    def __init__(self, stream, *, shell=None, log=None,
                 encoding='utf8', encoding_errors='strict',
                 force_binary=False, connect_maxwait=4.0,
                 limit=None):
        """Class initializer."""
        super().__init__(stream, server=True, force_binary=force_binary, log=log)
        self.default_encoding = encoding
        self._encoding_errors = encoding_errors
        self.force_binary = force_binary

        #: a future used for testing
        self._waiter_connected = _waiter_connected or asyncio.Future()
        #: a future used for testing
        self._tasks = [self._waiter_connected]
        self.shell = shell
        self.reader = None
        self.writer = None
        #: maximum duration for :meth:`check_negotiation`.
        self.connect_maxwait = connect_maxwait
        self._limit = limit

    # Base protocol methods

    def eof_received(self):
        """
        Called when the other end calls write_eof() or equivalent.

        This callback may be exercised by the nc(1) client argument ``-z``.
        """
        self.log.debug('EOF from client, closing.')
        self.connection_lost(None)

    def connection_made(self, transport):
        """
        Called when a connection is made.

        Sets attributes ``_transport``, ``_when_connected``, ``_last_received``,
        ``reader`` and ``writer``.

        Ensure ``super().connection_made(transport)`` is called when derived.
        """
        self._transport = transport
        self._when_connected = datetime.datetime.now()
        self._last_received = datetime.datetime.now()

        reader_factory = self._reader_factory
        writer_factory = self._writer_factory
        reader_kwds = {}
        writer_kwds = {}

        if self.default_encoding:
            reader_kwds['fn_encoding'] = self.encoding
            writer_kwds['fn_encoding'] = self.encoding
            reader_kwds['encoding_errors'] = self._encoding_errors
            writer_kwds['encoding_errors'] = self._encoding_errors
            reader_factory = self._reader_factory_encoding
            writer_factory = self._writer_factory_encoding

        if self._limit:
            reader_kwds['limit'] = self._limit

        self.reader = reader_factory(**reader_kwds)

        self.writer = writer_factory(
            transport=transport, protocol=self,
            reader=self.reader, server=True,
            log=self.log, **writer_kwds)

        self.log.info('Connection from %s', self)

        self._waiter_connected.add_done_callback(self.begin_shell)
        self._loop.call_soon(self.begin_negotiation)

    def data_received(self, data):
        """Process bytes received by transport."""
        # This may seem strange; feeding all bytes received to the **writer**,
        # and, only if they test positive, duplicating to the **reader**.
        #
        # The writer receives a copy of all raw bytes because, as an IAC
        # interpreter, it may likely **write** a responding reply.
        self._last_received = datetime.datetime.now()

        cmd_received = False
        for byte in data:
            try:
                recv_inband = self.writer.feed_byte(bytes([byte]))
            except:
                self._log_exception(self.log.warning, *sys.exc_info())
            else:
                if recv_inband:
                    # forward to reader (shell).
                    self.reader.feed_data(bytes([byte]))

                # becomes True if any out of band data is received.
                cmd_received = cmd_received or not recv_inband

        # until negotiation is complete, re-check negotiation aggressively
        # upon receipt of any command byte.
        if not self._waiter_connected.done() and cmd_received:
            self._check_negotiation_timer()

    # public properties

    @property
    def duration(self):
        """Time elapsed since client connected, in seconds as float."""
        return (datetime.datetime.now() - self._when_connected).total_seconds()

    @property
    def idle(self):
        """Time elapsed since data last received, in seconds as float."""
        return (datetime.datetime.now() - self._last_received).total_seconds()

    # public protocol methods

    def __repr__(self):
        hostport = self.get_extra_info('peername')[:2]
        return '<Peer {0} {1}>'.format(*hostport)

    @staticmethod
    def _log_exception(logger, e_type, e_value, e_tb):
        rows_tbk = [line for line in
                    '\n'.join(traceback.format_tb(e_tb)).split('\n')
                    if line]
        rows_exc = [line.rstrip() for line in
                    traceback.format_exception_only(e_type, e_value)]

        for line in rows_tbk + rows_exc:
            logger(line)
