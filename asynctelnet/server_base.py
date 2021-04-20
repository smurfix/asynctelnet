"""Module provides class BaseServer."""

from .stream import TelnetStream

import logging

__all__ = ('BaseServer',)


class BaseServer(TelnetStream):
    """Base Telnet Server Protocol."""

    def __init__(self, stream, **kw):
        """Class initializer."""
        if not kw.get('log',None):
            kw["log"] = logging.getLogger('asynctelnet.server')
        super().__init__(stream, server=True, **kw)
