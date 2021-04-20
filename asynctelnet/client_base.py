"""Module provides class BaseClient."""

from .stream import TelnetStream

import logging

__all__ = ('BaseClient',)


class BaseClient(TelnetStream):
    """Base Telnet Client."""

    def __init__(self, stream, **kw):
        """Class initializer."""
        kw.setdefault("log", logging.getLogger('asynctelnet.client'))
        super().__init__(stream, client=True, **kw)
        #: encoding
