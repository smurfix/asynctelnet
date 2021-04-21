from __future__ import annotations
from weakref import ref
from typing import Union

from ._base import BaseOption
from ..telopt import Opt

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
                    opt = Opt.add(value,name)
            else:
                raise

        try:
            return self[opt.value]
        except KeyError:
            self[opt.value] = iopt = BaseOption(self._stream(), value=opt)
            return iopt

    def __getitem__(self, value: int):
        """Look up by option / value."""
        try:
            return super().__getitem__(value)
        except KeyError:
            try:
                opt = Opt(value)
            except KeyError:
                # Ugh, we don't even know this option.
                # Instantiate a subclass for it.
                opt = Opt.add(value, f"X_{value :d}")
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

        if isinstance(opt, Opt):
            opt = BaseOption(value=opt)
        elif isinstance(opt,type) and issubclass(opt,BaseOption):
            opt = opt(self.stream)
        self[opt.value] = opt
