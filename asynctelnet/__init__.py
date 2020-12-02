"""asynctelnet: an anyio-based Telnet Protocol implementation."""
# pylint: disable=wildcard-import,undefined-variable
from .server_base import *      # noqa
from .server_shell import *     # noqa
from .server import *           # noqa
from .stream import *           # noqa
from .client_base import *      # noqa
from .client_shell import *     # noqa
from .client import *           # noqa
from .telopt import *           # noqa
from .slc import *              # noqa
from .accessories import get_version as __get_version

__all__ = (
    server_base.__all__ +
    server_shell.__all__ +
    server.__all__ +

    client_base.__all__ +
    client_shell.__all__ +
    client.__all__ +

    stream.__all__ +
    telopt.__all__ +
    slc.__all__
)  # noqa

__author__ = "Matthias Urlichs"
__url__ = u'https://github.com/smurfix/asynctelnet/'
__copyright__ = "Copyright 2020"
__credits__ = ["Jim Storch", "Wijnand Modderman-Lenstra", "Jeff Quast"]
__license__ = 'ISC'
__version__ = __get_version()
