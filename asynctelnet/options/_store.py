from __future__ import annotations
from weakref import ref
from typing import Union

from ._base import Opt, BaseOption, _Option

def _make_opt(value_):
    value_ = getattr(value_,"value",value_)
    class _Opt(BaseOption):
        value = value_
        name = f"X_{value}"
    Opt.register(_Opt)
    return _Opt

class StreamOptions(dict):
    """
    This class collects a stream's known option handlers.

    Lookup by name is via attribute, by option value via indexing.

    Options get BaseOption as their handler. If you don't want that,
    call ``add`` with the "real" handler.
    """
    def __init__(self, stream):
        self._stream = ref(stream)

    @property
    def stream(self):
        return self._stream()

    def __getattr__(self, name: str):
        """Look up by name."""
        try:
            opt = Opt[name]
        except KeyError:
            if name.startswith("X_"):
                value = int(name[2:])
                try:
                    opt = Opt(value)
                except KeyError:
                    opt = _make_opt(value)
            else:
                raise
        try:
            return self[opt.value]
        except KeyError:
            self[opt.value] = iopt = BaseOption(self._stream(), value=opt)
            return iopt

    def __getitem__(self, value: int):
        """Look up by option / value."""
        value = getattr(value,'value',value)
        try:
            return super().__getitem__(value)
        except KeyError:
            try:
                opt = Opt(value)
            except KeyError:
                # Ugh, we don't even know this option.
                # Instantiate a subclass for it.
                opt = _make_opt(value)
            self[opt.value] = iopt = BaseOption(self._stream(), value=opt)
            return iopt

    def __setitem__(self, value, opt):
        if not isinstance(opt,BaseOption):
            raise RuntimeError("Can only set to an option")
        super().__setitem__(value,opt)

    def add(self, opt: Union[BaseOption, type(BaseOption)]):
        """
        Use this option processor
        """
        if opt.value in self:
            self.stream.log.debug("A handler for %s already exists", opt)
            return

        if isinstance(opt, _Option):
            opt = BaseOption(value=opt)
        if isinstance(opt,type) and issubclass(opt,BaseOption):
            opt = opt(self.stream)
        self[opt.value] = opt
