from ._base import BaseOption

# commented-out options are implemented in other modules

# BINARY 0 basic

class ECHO(BaseOption):
    """
    echo
    """
    value = 1

class RCP(BaseOption):
    """
    prepare to reconnect
    """
    value = 2

class SGA(BaseOption):
    """
    suppress go ahead
    """
    value = 3

class NAMS(BaseOption):
    """
    approximate message size
    """
    value = 4

class STATUS(BaseOption):
    """
    give status
    """
    value = 5

class TM(BaseOption):
    """
    timing mark
    """
    value = 6

class RCTE(BaseOption):
    """
    remote controlled transmission and echo
    """
    value = 7

class NAOL(BaseOption):
    """
    negotiate about output line width
    """
    value = 8

class NAOP(BaseOption):
    """
    negotiate about output page size
    """
    value = 9

class NAOCRD(BaseOption):
    """
    negotiate about CR disposition
    """
    value = 10

class NAOHTS(BaseOption):
    """
    negotiate about horizontal tabstops
    """
    value = 11

class NAOHTD(BaseOption):
    """
    negotiate about horizontal tab disposition
    """
    value = 12

class NAOFFD(BaseOption):
    """
    negotiate about formfeed disposition
    """
    value = 13

class NAOVTS(BaseOption):
    """
    negotiate about vertical tab stops
    """
    value = 14

class NAOVTD(BaseOption):
    """
    negotiate about vertical tab disposition
    """
    value = 15

class NAOLFD(BaseOption):
    """
    negotiate about output LF disposition
    """
    value = 16

class XASCII(BaseOption):
    """
    extended ascii character set
    """
    value = 17

class LOGOUT(BaseOption):
    """
    force logout
    """
    value = 18

class BM(BaseOption):
    """
    byte macro
    """
    value = 19

class DET(BaseOption):
    """
    data entry terminal
    """
    value = 20

class SUPDUP(BaseOption):
    """
    supdup protocol
    """
    value = 21

class SUPDUPOUTPUT(BaseOption):
    """
    supdup output
    """
    value = 22

class SNDLOC(BaseOption):
    """
    send location
    """
    value = 23

class TTYPE(BaseOption):
    """
    terminal type
    """
    value = 24

class EOR(BaseOption):
    """
    end or record
    """
    value = 25

class TUID(BaseOption):
    """
    TACACS user identification
    """
    value = 26

class OUTMRK(BaseOption):
    """
    output marking
    """
    value = 27

class TTYLOC(BaseOption):
    """
    terminal location number
    """
    value = 28

class VT3270REGIME(BaseOption):
    """
    3270 regime
    """
    value = 29

class X3PAD(BaseOption):
    """
    X.3 PAD
    """
    value = 30

class NAWS(BaseOption):
    """
    window size
    """
    value = 31

class TSPEED(BaseOption):
    """
    terminal speed
    """
    value = 32

class LFLOW(BaseOption):
    """
    remote flow control
    """
    value = 33

class LINEMODE(BaseOption):
    """
    Linemode option
    """
    value = 34

class XDISPLOC(BaseOption):
    """
    X Display Location
    """
    value = 35

class OLD_ENVIRON(BaseOption):
    """
    Old - Environment variables
    """
    value = 36

class AUTHENTICATION(BaseOption):
    """
    Authenticate
    """
    value = 37

class ENCRYPT(BaseOption):
    """
    Encryption option
    """
    value = 38

class NEW_ENVIRON(BaseOption):
    """
    New - Environment variables
    """
    value = 39

    # http://www.iana.org/assignments/telnet-options
class TN3270E(BaseOption):
    """
    TN3270E
    """
    value = 40

class XAUTH(BaseOption):
    """
    XAUTH
    """
    value = 41

# CHARSET 42 basic

class RSP(BaseOption):
    """
    Telnet Remote Serial Port
    """
    value = 43

class COM_PORT_OPTION(BaseOption):
    """
    Com Port Control Option
    """
    value = 44

class SUPPRESS_LOCAL_ECHO(BaseOption):
    """
    Telnet Suppress Local Echo
    """
    value = 45

class TLS(BaseOption):
    """
    Telnet Start TLS
    """
    value = 46

class KERMIT(BaseOption):
    """
    KERMIT
    """
    value = 47

class SEND_URL(BaseOption):
    """
    SEND-URL
    """
    value = 48

class FORWARD_X(BaseOption):
    """
    FORWARD_X
    """
    value = 49

class MSDP(BaseOption):
    """
    Mud Server Data, https://tintin.mudhalla.net/protocols/msdp/
    """
    value = 69

class MSSP(BaseOption):
    """
    Mud Server Status, https://tintin.mudhalla.net/protocols/mssp/
    """
    value = 70

class MCCP_COMPRESS(BaseOption):
    """
    MUD compression, old (broken start sequence, DO NOT USE)
    """
    value = 85

class MCCP2_COMPRESS(BaseOption):
    """
    MUD compression, new (correct start sequence)
    """
    value = 86

class PRAGMA_LOGON(BaseOption):
    """
    TELOPT PRAGMA LOGON
    """
    value = 138

class SSPI_LOGON(BaseOption):
    """
    TELOPT SSPI LOGON
    """
    value = 139

class PRAGMA_HEARTBEAT(BaseOption):
    """
    TELOPT PRAGMA HEARTBEAT
    """
    value = 140

class GMCP(BaseOption):
    """
    Generic Mud Communication Protocol, https://tintin.mudhalla.net/protocols/gmcp/
    """
    value = 201

class EXOPL(BaseOption):
    """
    extended options. Not implemented!
    """
    value = 255

