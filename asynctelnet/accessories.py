"""Accessory functions."""
# std imports
import pkg_resources
import importlib
import logging
import outcome
import anyio

__all__ = ('encoding_from_lang', 'name_unicode', 'eightbits', 'make_logger',
           'repr_mapping', 'function_lookup', 'CtxObj', 'spawn', 'ValueEvent')


def get_version():
    try:
        return pkg_resources.get_distribution("asynctelnet").version
    except Exception:
        return "0.0"


def encoding_from_lang(lang):
    """
    Parse encoding from LANG environment value.

    Example::

        >>> encoding_from_lang('en_US.UTF-8@misc')
        'UTF-8'
    """
    encoding = lang
    if '.' in lang:
        _, encoding = lang.split('.', 1)
    if '@' in encoding:
        encoding, _ = encoding.split('@', 1)
    return encoding


def name_unicode(ucs):
    """Return 7-bit ascii printable of any string. """
    # more or less the same as curses.ascii.unctrl -- but curses
    # module is conditionally excluded from many python distributions!
    bits = ord(ucs)
    if 32 <= bits <= 126:
        # ascii printable as one cell, as-is
        rep = chr(bits)
    elif bits == 127:
        rep = "^?"
    elif bits < 32:
        rep = "^" + chr(((bits & 0x7f) | 0x20) + 0x20)
    else:
        rep = r'\x{:02x}'.format(bits)
    return rep


def eightbits(number):
    """
    Binary representation of ``number`` padded to 8 bits.

    Example::

        >>> eightbits(ord('a'))
        '0b01100001'
    """
    # useful only so far in context of a forwardmask or any bitmask.
    prefix, value = bin(number).split('b')
    return '0b%0.8i' % (int(value),)

_DEFAULT_LOGFMT = ' '.join(('%(asctime)s',
                            '%(levelname)s',
                            '%(filename)s:%(lineno)d',
                            '%(message)s'))
def make_logger(name, loglevel='info', logfile=None, logfmt=_DEFAULT_LOGFMT):
    """Create and return simple logger for the given arguments.
    This is only suitable for your main program.
    """
    lvl = getattr(logging, loglevel.upper())
    logging.getLogger().setLevel(lvl)

    _cfg = {'format': logfmt}
    if logfile:
        _cfg['filename'] = logfile
    logging.basicConfig(**_cfg)
    return logging.getLogger(name)

def repr_mapping(mapping):
    """Return printable string, 'key=value [key=value ...]' for mapping."""
    return ' '.join('='.join(map(str, kv)) for kv in mapping.items())

def function_lookup(pymod_path):
    """Return callable function target from standard module.function path."""
    module_name, func_name = pymod_path.rsplit('.', 1)
    module = importlib.import_module(module_name)
    shell_function = getattr(module, func_name)
    assert callable(shell_function), shell_function
    return shell_function

class CtxObj:
    """
    Add an async context manager that calls `_ctx` to run the context.

    Usage::
        class Foo(CtxObj):
            @asynccontextmanager
            async def _ctx(self):
                yield self  # or whatever

        async with Foo() as self_or_whatever:
            pass
    """
    __ctx = None
    def __aenter__(self):
        if self.__ctx is not None:
            breakpoint()
            raise RuntimeError("Double context")
        self.__ctx = ctx = self._ctx()
        return ctx.__aenter__()

    async def __aexit__(self, *tb):
        ctx,self.__ctx = self.__ctx,None
        if hasattr(self,"aclose"):
            async with anyio.move_on_after(2, shield=True):
                await self.aclose()
        return await ctx.__aexit__(*tb)


async def spawn(tg, proc,*args, _name=None, **kwargs):
    """
    Helper to start a subtask. Like `anyio.abc.TaskGroup.spawn` but
    (a) accepts keyword arguments, (b) returns an `anyio.abc.CancelScope`
    which can be used to kill the task.
    """
    sc = None
    async def _spawn(evt, p,a,k):
        nonlocal sc
        async with anyio.open_cancel_scope() as sc:
            await evt.set()
            await p(*a,**k)

    evt = anyio.create_event()
    await tg.spawn(_spawn, evt, proc,args,kwargs, name=_name)
    await evt.wait()
    return sc

class ValueEvent:
    """A waitable value useful for inter-task synchronization,
    inspired by :class:`threading.Event`.

    An event object manages an internal value, which is initially
    unset, and a task can wait for it to become True.

    Note that the value can only be read once.
    """

    event = None
    value = None

    def __init__(self):
        self.event = anyio.create_event()

    async def set(self, value):
        """Set the result to return this value, and wake any waiting task.
        """
        assert not self.event.is_set(), self
        self.value = outcome.Value(value)
        await self.event.set()

    async def set_error(self, exc):
        """Set the result to raise this exceptio, and wake any waiting task.
        """
        assert not self.event.is_set(), self
        self.value = outcome.Error(exc)
        await self.event.set()

    def is_set(self):
        """Check whether the event has occurred.
        """
        return self.value is not None

    async def get(self):
        """Block until the value is set.

        If it's already set, then this method returns immediately.

        The value can only be read once.
        """
        await self.event.wait()
        return self.value.unwrap()

    async def wait(self):
        """
        Block until the value is set.

        This does not retrieve the value and is meant for locks and similar helpers.
        """
        await self.event.wait()

