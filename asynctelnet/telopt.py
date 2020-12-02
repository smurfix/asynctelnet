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

@_exp
class Opt(IntEnum):
    BINARY = 0  # 8-bit data path
    ECHO = 1  # echo
    RCP = 2  # prepare to reconnect
    SGA = 3  # suppress go ahead
    NAMS = 4  # approximate message size
    STATUS = 5  # give status
    TM = 6  # timing mark
    RCTE = 7  # remote controlled transmission and echo
    NAOL = 8  # negotiate about output line width
    NAOP = 9  # negotiate about output page size
    NAOCRD = 10  # negotiate about CR disposition
    NAOHTS = 11  # negotiate about horizontal tabstops
    NAOHTD = 12  # negotiate about horizontal tab disposition
    NAOFFD = 13  # negotiate about formfeed disposition
    NAOVTS = 14  # negotiate about vertical tab stops
    NAOVTD = 15  # negotiate about vertical tab disposition
    NAOLFD = 16  # negotiate about output LF disposition
    XASCII = 17  # extended ascii character set
    LOGOUT = 18  # force logout
    BM = 19  # byte macro
    DET = 20  # data entry terminal
    SUPDUP = 21  # supdup protocol
    SUPDUPOUTPUT = 22  # supdup output
    SNDLOC = 23  # send location
    TTYPE = 24  # terminal type
    EOR = 25  # end or record
    TUID = 26  # TACACS user identification
    OUTMRK = 27  # output marking
    TTYLOC = 28  # terminal location number
    VT3270REGIME = 29  # 3270 regime
    X3PAD = 30  # X.3 PAD
    NAWS = 31  # window size
    TSPEED = 32  # terminal speed
    LFLOW = 33  # remote flow control
    LINEMODE = 34  # Linemode option
    XDISPLOC = 35  # X Display Location
    OLD_ENVIRON = 36  # Old - Environment variables
    AUTHENTICATION = 37  # Authenticate
    ENCRYPT = 38  # Encryption option
    NEW_ENVIRON = 39  # New - Environment variables
    # http://www.iana.org/assignments/telnet-options
    TN3270E = 40  # TN3270E
    XAUTH = 41  # XAUTH
    CHARSET = 42  # CHARSET
    RSP = 43  # Telnet Remote Serial Port
    COM_PORT_OPTION = 44  # Com Port Control Option
    SUPPRESS_LOCAL_ECHO = 45  # Telnet Suppress Local Echo
    TLS = 46  # Telnet Start TLS
    KERMIT = 47  # KERMIT
    SEND_URL = 48  # SEND-URL
    FORWARD_X = 49  # FORWARD_X
    MSDP = 69  # Mud Server Data, https://tintin.mudhalla.net/protocols/msdp/
    MSSP = 70  # Mud Server Status, https://tintin.mudhalla.net/protocols/mssp/
    MCCP_COMPRESS = 85  # MUD compression, old (broken start sequence, DO NOT USE)
    MCCP2_COMPRESS = 86  # MUD compression, new (correct start sequence)
    PRAGMA_LOGON = 138  # TELOPT PRAGMA LOGON
    SSPI_LOGON = 139  # TELOPT SSPI LOGON
    PRAGMA_HEARTBEAT = 140  # TELOPT PRAGMA HEARTBEAT
    GMCP = 201  # Generic Mud Communication Protocol, https://tintin.mudhalla.net/protocols/gmcp/
    EXOPL = 255  # extended options. Not implemented!

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
