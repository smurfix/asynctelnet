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

    def __init__(self, stream, **kw):
        """Class initializer."""
        if not kw.get('log',None):
            kw.log = logging.getLogger('asynctelnet.client')
        super().__init__(stream, client=True, **kw)
        #: encoding

