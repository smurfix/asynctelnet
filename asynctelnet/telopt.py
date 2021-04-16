# Telnet options.
#
# No we don't import from telnetlib. Enums are way nicer.

from enum import IntEnum

__all__ = (
    'Cmd', 'Opt', 'SubT', 'SubVar', 'Flow', 'Req',
    'ABORT', 'ACCEPTED', 'AO', 'AUTHENTICATION', 'AYT', 'BINARY', 'BM',
    'BRK', 'CHARSET', 'CMD_EOR', 'COM_PORT_OPTION', 'DET', 'DM', 'DO',
    'DONT', 'EC', 'ECHO', 'EL', 'ENCRYPT', 'EOF', 'EOR', 'ESC', 'EXOPL',
    'FORWARD_X', 'GA', 'IAC', 'INFO', 'IP', 'IS', 'KERMIT', 'LFLOW',
    'LFLOW_OFF', 'LFLOW_ON', 'LFLOW_RESTART_ANY', 'LFLOW_RESTART_XON',
    'LINEMODE', 'LOGOUT', 'MCCP2_COMPRESS', 'MCCP_COMPRESS', 'NAMS',
    'NAOCRD', 'NAOFFD', 'NAOHTD', 'NAOHTS', 'NAOL', 'NAOLFD', 'NAOP',
    'NAOVTD', 'NAOVTS', 'NAWS', 'NEW_ENVIRON', 'NOP', 'PRAGMA_HEARTBEAT',
    'PRAGMA_LOGON', 'RCP', 'RCTE', 'REJECTED', 'REQUEST', 'RSP', 'SB',
    'SE', 'SEND', 'SEND_URL', 'SGA', 'SNDLOC', 'SSPI_LOGON', 'STATUS',
    'SUPDUP', 'SUPDUPOUTPUT', 'SUPPRESS_LOCAL_ECHO', 'SUSP', 'TLS', 'TM',
    'TN3270E', 'TSPEED', 'TTABLE_ACK', 'TTABLE_IS', 'TTABLE_NAK',
    'TTABLE_REJECTED', 'TTYLOC', 'TTYPE', 'USERVAR', 'VALUE', 'VAR',
    'VT3270REGIME', 'WILL', 'WONT', 'X3PAD', 'XASCII', 'XAUTH',
    'XDISPLOC', 'name_command', 'name_commands',
    'MSSP', 'MSDP', 'GMCP',
)

def _exp(cls):
    for k in dir(cls):
        if k[0].isupper():
            globals()[k] = getattr(cls, k)
    return cls

@_exp
class Cmd(IntEnum):
    EOF = 236  # End of File
    SUSP = 237  # Suspend
    ABORT = 238  # 238
    EOR = 239  # End of Record
    SE = 240  # Subnegotiation Start
    NOP = 241  # No Operation
    DM = 242  # Data Mark
    BRK = 243  # Break
    IP = 244  # Interrupt Process
    AO = 245  # Abort Output
    AYT = 246  # Are You There
    EC = 247  # Erase Character
    EL = 248  # Erase Line
    GA = 249  # Go Ahead
    SB = 250  # Subnegotiation Begin
    WILL = 251  # I want to do …
    WONT = 252  # I will not do …
    DO = 253  # Please do …
    DONT = 254  # You should not do …
    IAC = 255  # Escape

from .options import Opt
for _opt in Opt.options:
    globals()[_opt.name] = _opt

CMD_EOR=Cmd.EOR
EOR = Opt.EOR

@_exp
class SubT(IntEnum):
    IS = 0
    SEND = 1
    INFO = 2

@_exp
class SubVar(IntEnum):
    VAR = 0
    VALUE = 1
    ESC = 2
    USERVAR = 3

@_exp
class Flow(IntEnum):
    LFLOW_OFF = 0
    LFLOW_ON = 1
    LFLOW_RESTART_ANY = 2
    LFLOW_RESTART_XON = 3

@_exp
class Req(IntEnum):
    REQUEST = 1
    ACCEPTED = 2
    REJECTED = 3
    TTABLE_IS = 4
    TTABLE_REJECTED = 5
    TTABLE_ACK = 6
    TTABLE_NAK = 7


def name_command(byte):
    """Return string description for (maybe) telnet command byte."""
    try:
        return Cmd(byte)
    except ValueError:
        try:
            return Opt(byte).name
        except ValueError:
            raise ValueError("Unknown: %r"%(byte,)) from None

def name_commands(cmds, sep=' '):
    """Return string description for array of (maybe) telnet command bytes."""
    return sep.join(name_command(byte) for byte in cmds)
