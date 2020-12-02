"""Module provides class BaseClient."""

import logging
import datetime
import traceback
import weakref
import anyio
import sys

from .stream import TelnetStream
from .telopt import name_commands
from .accessories import CtxObj

__all__ = ('BaseClient',)

from anyio.abc.sockets import SocketAttribute

class BaseClient(TelnetStream):
    """Base Telnet Client."""
    _when_connected = None
    _last_received = None
    _transport = None
    _closing = False

    def __init__(self, stream, log=None,
                 encoding='utf8', encoding_errors='strict',
                 force_binary=False):
        """Class initializer."""
        super().__init__(stream)
        self.log = log or logging.getLogger('asynctelnet.client')
        #: encoding

        self.default_encoding = encoding
        self._encoding_errors = encoding_errors
        self.force_binary = force_binary
        self._tasks = []

        #: minimum duration for :meth:`check_negotiation`.
        #self.connect_minwait = connect_minwait
        #: maximum duration for :meth:`check_negotiation`.
        #self.connect_maxwait = connect_maxwait

    # public protocol methods

    def __repr__(self):
        hostport = self.extra_attributes[SocketAttribute.remote_address]()[:2]
        return '<Peer {0} {1}>'.format(*hostport)

    def encoding(self, outgoing=False, incoming=False):
        """
        Encoding that should be used for the direction indicated.

        The base implementation **always** returns ``encoding`` argument
        given to class initializer or, when unset (``None``), ``US-ASCII``.
        """
        # pylint: disable=unused-argument
        return self.default_encoding or 'US-ASCII'  # pragma: no cover

