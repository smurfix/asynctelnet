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

    def __init__(self, stream, **kw):
        """Class initializer."""
        super().__init__(stream, server=True, **kw)
