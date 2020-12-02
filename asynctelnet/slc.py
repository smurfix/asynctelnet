"""
Special Line Character support for Telnet Linemode Option (:rfc:`1184`).
"""
from enum import IntEnum

from .accessories import eightbits, name_unicode

__all__ = ('SLC', 'NSLC', 'BSD_SLC_TAB', 'generate_slctab', 'Linemode',
           'snoop', 'generate_forwardmask', 'Forwardmask',
           'name_slc_command',
           'NoSupport', 'Var','Flush','Cmd', 'LMode', 'LMode_Mode')

def _exp(cls):
    for k in dir(cls):
        if k[0].isupper():
            globals()[k] = getattr(cls, k)
    return cls

@_exp
class Var(IntEnum):
    NOSUPPORT = 0
    CANTCHANGE = 1
    VARIABLE = 2
    DEFAULT = 3

@_exp
class Flush(IntEnum):
    OUT = 32
    IN = 64
    ACK = 128

SLC_LEVELBITS = 0x03

@_exp
class Cmd(IntEnum):
    DM = 1
    SYNCH = 1  # alias for DM
    BRK = 2
    IP = 3
    AO = 4
    AYT = 5
    EOR = 6
    ABORT = 7
    EOF = 8
    SUSP = 9
    EC = 10
    EL = 11
    EW = 12
    RP = 13
    LNEXT = 14
    XON = 15
    XOFF = 16
    FORW1 = 17
    FORW2 = 18
    MCL = 19
    MCR = 20
    MCWL = 21
    MCWR = 22
    MCBOL = 23
    MCEOL = 24
    INSRT = 25
    OVER = 26
    ECR = 27
    EWR = 28
    EBOL = 29
    EEOL = 30
    NSLC = 31

@_exp
class LMode(IntEnum):
    MODE = 1
    FORWARDMASK = 3
    SLC = 3

@_exp
class LMode_Mode(IntEnum):
    REMOTE = 0
    LOCAL = 1
    TRAPSIG = 2

    # Flags
    ACK = 4
    SOFT_TAB = 8
    LIT_ECHO = 16

class SLC(object):
    def __init__(self, mask=Var.DEFAULT, value=None):
        """
        Defines the willingness to support a Special Linemode Character.

        Defined by its SLC support level, ``mask`` and default keyboard
        ASCII byte ``value`` (may be negotiated by client).
        """
        #   The default byte mask ``Var.DEFAULT`` and value ``b'\x00'`` infer
        #   our willingness to support the option, but with no default value.
        #   The value must be negotiated by client to activate the callback.
        self.mask = mask
        self.val = value

    @property
    def level(self):
        """ Returns SLC level of support.  """
        return self.mask & SLC_LEVELBITS

    @property
    def nosupport(self):
        """ Returns True if SLC level is Var.NOSUPPORT. """
        return self.level == Var.NOSUPPORT

    @property
    def cantchange(self):
        """ Returns True if SLC level is Var.CANTCHANGE. """
        return self.level == Var.CANTCHANGE

    @property
    def variable(self):
        """ Returns True if SLC level is Var.VARIABLE. """
        return self.level == Var.VARIABLE

    @property
    def default(self):
        """ Returns True if SLC level is Var.DEFAULT. """
        return self.level == Var.DEFAULT

    @property
    def ack(self):
        """ Returns True if Flush.ACK bit is set. """
        return self.mask & Flush.ACK

    @property
    def flushin(self):
        """ Returns True if Flush.IN bit is set. """
        return self.mask & Flush.IN

    @property
    def flushout(self):
        """ Returns True if Flush.IN bit is set.  """
        return self.mask & Flush.OUT

    def set_value(self, value):
        """ Set SLC keyboard ascii value to ``byte``.  """
        assert isinstance(mask,int)
        self.val = value

    def set_mask(self, mask):
        """ Set SLC option mask, ``mask``.  """
        assert isinstance(mask,int)
        self.mask = mask

    def set_flag(self, flag):
        """ Set SLC option flag, ``flag``.  """
        assert isinstance(mask,int)
        self.mask = self.mask | flag

    def __str__(self):
        """ SLC definition as string '(value, flag(|s))'. """
        flags = list()
        for flag in ('nosupport', 'variable', 'default', 'ack',
                     'flushin', 'flushout', 'cantchange', ):
            if getattr(self, flag):
                flags.append(flag)
        return '({value}, {flags})'.format(
            value=(name_unicode(self.val)
                   if self.val != _POSIX_VDISABLE
                   else '(DISABLED:\\xff)'),
            flags='|'.join(flags))


class NoSupport(SLC):
    def __init__(self):
        """
        SLC definition inferring our unwillingness to support the option.
        """
        super().__init__(Var.NOSUPPORT, _POSIX_VDISABLE)

#: SLC value may be changed, flushes input and output
_SLC_VARIABLE_FIO = Var.VARIABLE | Flush.IN | Flush.OUT
#: SLC value may be changed, flushes input
_SLC_VARIABLE_FI = Var.VARIABLE | Flush.IN
#: SLC value may be changed, flushes output
_SLC_VARIABLE_FO = Var.VARIABLE | Flush.OUT
#: SLC function for this value is not supported
_POSIX_VDISABLE = b'\xff'

#: This SLC tab when sent to a BSD client warrants no reply; their
#  tabs match exactly. These values are found in ttydefaults.h of
#  termios family of functions.
BSD_SLC_TAB = {
    Cmd.FORW1: NoSupport(),  # unsupported; causes all buffered
    Cmd.FORW2: NoSupport(),  # characters to be sent immediately,
    Cmd.EOF: SLC(Var.VARIABLE,        b'\x04'),  # ^D VEOF
    Cmd.EC: SLC(Var.VARIABLE,         b'\x7f'),  # BS VERASE
    Cmd.EL: SLC(Var.VARIABLE,         b'\x15'),  # ^U VKILL
    Cmd.IP: SLC(_SLC_VARIABLE_FIO,    b'\x03'),  # ^C VINTR
    Cmd.ABORT: SLC(_SLC_VARIABLE_FIO, b'\x1c'),  # ^\ VQUIT
    Cmd.XON: SLC(Var.VARIABLE,        b'\x11'),  # ^Q VSTART
    Cmd.XOFF: SLC(Var.VARIABLE,       b'\x13'),  # ^S VSTOP
    Cmd.EW: SLC(Var.VARIABLE,         b'\x17'),  # ^W VWERASE
    Cmd.RP: SLC(Var.VARIABLE,         b'\x12'),  # ^R VREPRINT
    Cmd.LNEXT: SLC(Var.VARIABLE,      b'\x16'),  # ^V VLNEXT
    Cmd.AO: SLC(_SLC_VARIABLE_FO,     b'\x0f'),  # ^O VDISCARD
    Cmd.SUSP: SLC(_SLC_VARIABLE_FI,   b'\x1a'),  # ^Z VSUSP
    Cmd.AYT: SLC(Var.VARIABLE,        b'\x14'),  # ^T VSTATUS
    # no default value for break, sync, end-of-record,
    Cmd.BRK: SLC(), Cmd.DM: SLC(), Cmd.EOR: SLC(),

}


def generate_slctab(tabset=BSD_SLC_TAB):
    """ Returns full 'SLC Tab' for definitions found using ``tabset``.
        Functions not listed in ``tabset`` are set as Var.NOSUPPORT.
    """
    #   ``slctab`` is a dictionary of SLC functions, such as SLC_IP,
    #   to a tuple of the handling character and support level.
    _slctab = {}
    for slc in [bytes([const]) for const in range(1, NSLC + 1)]:
        _slctab[slc] = tabset.get(slc, NoSupport())
    return _slctab


def generate_forwardmask(binary_mode, tabset, ack=False):
    """
    Generate a :class:`~.Forwardmask` instance.

    Generate a 32-byte (``binary_mode`` is True) or 16-byte (False) Forwardmask
    instance appropriate for the specified ``slctab``.  A Forwardmask is formed
    by a bitmask of all 256 possible 8-bit keyboard ascii input, or, when not
    'outbinary', a 16-byte 7-bit representation of each value, and whether or
    not they should be "forwarded" by the client on the transport stream
    """
    num_bytes, msb = (32, 256) if binary_mode else (16, 127)
    mask32 = []
    for mask in range(msb // 8):
        start = mask * 8
        last = start + 7
        byte = 0
        for char in range(start, last + 1):
            (func, slc_name, slc_def) = snoop(bytes([char]), tabset, dict())
            byte <<= 1
            if func is not None and not slc_def.nosupport:
                # set bit for this character, it is a supported slc char
                byte |= 1
        mask32.append(byte)
    return Forwardmask(bytes(mask32), ack)


def snoop(byte, slctab, caller):
    """ Scan ``slctab`` for matching ``byte`` values.

        Returns (callback, func_byte, slc_definition) on match.
        Otherwise, (None, None, None). If no callback is assigned,
        the value of callback is always None.
    """
    for slc_func, slc_def in slctab.items():
        if byte == slc_def.val and slc_def.val != 0:
            return (caller.get_slc_callback(slc_func), slc_func, slc_def)
    return (None, None, None)


class Linemode(object):
    """ """

    def __init__(self, mask=0):
        """ A mask of ``LMODE_MODE_LOCAL`` means that all line editing is
            performed on the client side (default). A mask of 0
            indicates that editing is performed on the remote side.
            Valid bit flags of mask are: ``LMode_Mode.TRAPSIG``,
            ``LMode_Mode.ACK``, ``LMode_Mode.SOFT_TAB``, and
            ``LMode_Mode.LIT_ECHO``.
        """
        assert isinstance(mask, int), (repr(mask), mask)
        self.mask = mask

    def __eq__(self, other):
        """Compare by another Linemode (LMode_Mode.ACK ignored)."""
        # the inverse OR(|) of acknowledge bit UNSET in comparator,
        # would be the AND OR(& ~) to compare modes without acknowledge
        # bit set.
        return (
            (self.mask | ord(LMode_Mode.ACK)) ==
            (other.mask | ord(LMode_Mode.ACK))
        )

    @property
    def local(self):
        """ True if linemode is local. """
        return bool(self.mask & ord(LMode_Mode.LOCAL))

    @property
    def remote(self):
        """ True if linemode is remote. """
        return not self.local

    @property
    def trapsig(self):
        """ True if signals are trapped by client. """
        return bool(self.mask & ord(LMode_Mode.TRAPSIG))

    @property
    def ack(self):
        """ Returns True if mode has been acknowledged. """
        return bool(self.mask & ord(LMode_Mode.ACK))

    @property
    def soft_tab(self):
        """ Returns True if client will expand horizontal tab (\x09). """
        return bool(self.mask & ord(LMode_Mode.SOFT_TAB))

    @property
    def lit_echo(self):
        """ Returns True if non-printable characters are displayed as-is. """
        return bool(self.mask & ord(LMode_Mode.LIT_ECHO))

    def __str__(self):
        """ Returns string representation of line mode, for debugging """
        return 'remote' if self.remote else 'local'

    def __repr__(self):
        return '<{0!r}: {1}>'.format(
            self.mask, ', '.join([
                '{0}:{1}'.format(prop, getattr(self, prop))
                for prop in ('lit_echo', 'soft_tab', 'ack',
                             'trapsig', 'remote', 'local')])
        )


class Forwardmask(object):
    """ """

    def __init__(self, value, ack=False):
        """
        Forwardmask object using the bytemask value received by server.

        :param bytes value: bytemask ``value`` received by server after ``IAC SB
            LINEMODE DO FORWARDMASK``. It must be a bytearray of length 16 or 32.
        """
        assert isinstance(value, (bytes, bytearray)), value
        assert len(value) in (16, 32), len(value)
        self.value = value
        self.ack = ack

    def description_table(self):
        """
        Returns list of strings describing obj as a tabular ASCII map.
        """
        result = []
        MRK_CONT = '(...)'
        continuing = lambda: len(result) and result[-1] == MRK_CONT
        is_last = lambda mask: mask == len(self.value) - 1
        same_as_last = lambda row: (
            len(result) and result[-1].endswith(row.split()[-1]))

        for mask, byte in enumerate(self.value):
            if byte == 0:
                if continuing() and not is_last(mask):
                    continue
                row = '[%2d] %s' % (mask, eightbits(0),)
                if not same_as_last(row) or is_last(mask):
                    result.append(row)
                else:
                    result.append(MRK_CONT)
            else:
                start = mask * 8
                last = start + 7
                characters = ', '.join([name_unicode(chr(char))
                                        for char in range(start, last + 1)
                                        if char in self])
                result.append('[%2d] %s %s' % (
                    mask, eightbits(byte), characters,))
        return result

    def __str__(self):
        """Returns single string of binary 0 and 1 describing obj."""
        return '0b%s' % (''.join([value for (prefix, value) in [
            eightbits(byte).split('b') for byte in self.value]]),)

    def __contains__(self, number):
        """Whether forwardmask contains keycode ``number``."""
        mask, flag = number // 8, 2 ** (7 - (number % 8))
        return bool(self.value[mask] & flag)


#: List of globals that may match an slc function byte
_DEBUG_SLC_OPTS = dict([(value, key)
                        for key, value in locals().items() if key in
                        ('SLC_SYNCH', 'SLC_BRK', 'SLC_IP', 'SLC_AO', 'SLC_AYT',
                            'SLC_EOR', 'SLC_ABORT', 'SLC_EOF', 'SLC_SUSP',
                            'SLC_EC', 'SLC_EL', 'SLC_EW', 'SLC_RP',
                            'SLC_LNEXT', 'SLC_XON', 'SLC_XOFF', 'SLC_FORW1',
                            'SLC_FORW2', 'SLC_MCL', 'SLC_MCR', 'SLC_MCWL',
                            'SLC_MCWR', 'SLC_MCBOL', 'SLC_MCEOL', 'SLC_INSRT',
                            'SLC_OVER', 'SLC_ECR', 'SLC_EWR', 'SLC_EBOL',
                            'SLC_EEOL',)])


def name_slc_command(byte):
    """ Given an SLC ``byte``, return global mnemonic as string. """
    return (repr(byte) if byte not in _DEBUG_SLC_OPTS
            else _DEBUG_SLC_OPTS[byte])
