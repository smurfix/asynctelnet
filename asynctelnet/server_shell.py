import anyio
from anyio.streams.text import TextStream

CR, LF, NUL = '\r\n\x00'
from . import slc
from . import telopt
from . import accessories

__all__ = ('telnet_server_shell',)


async def telnet_server_shell(stream):
    """
    A default telnet shell, appropriate for use with asynctelnet.create_server.

    This shell provides a very simple REPL, allowing introspection and state
    toggling of the connected client session.

    """
    stream = RLTextStream(stream)
    await stream.send("Ready." + CR + LF)

    command = None
    while True:
        if command:
            await writer.send(CR + LF)
        await writer.send('tel:sh> ')
        command = await stream.readline()
        if not command:
            return
        await stream.send(CR + LF)
        if command == 'quit':
            await stream.send('Goodbye.' + CR + LF)
            break
        elif command == 'help':
            await stream.send('quit, stream, slc, toggle [option|all], '
                         '… and that\'s it.')
        elif command == 'stream':
            await stream.send(repr(stream))
        elif command == 'version':
            await stream.send(accessories.get_version())
        elif command == 'slc':
            await stream.send(get_slcdata(stream))
        elif command.startswith('toggle'):
            option = command[len('toggle '):] or None
            await stream.send(await do_toggle(stream, option))
        elif command:
            await stream.send(f'no such command: {command!r}.')
    await stream.aclose()


def get_slcdata(writer):
    """Display Special Line Editing (SLC) characters."""
    _slcs = sorted([
        '{:>15}: {}'.format(slc.name_slc_command(slc_func), slc_def)
        for (slc_func, slc_def) in sorted(writer.slctab.items())
        if not (slc_def.nosupport or slc_def.val == slc.theNULL)])
    _unset = sorted([
        slc.name_slc_command(slc_func)
        for (slc_func, slc_def) in sorted(writer.slctab.items())
        if slc_def.val == slc.theNULL])
    _nosupport = sorted([
        slc.name_slc_command(slc_func)
        for (slc_func, slc_def) in sorted(
            writer.slctab.items())
        if slc_def.nosupport])

    return ('Special Line Characters:\r\n' +
            '\r\n'.join(_slcs) +
            '\r\nUnset by client: ' +
            ', '.join(_unset) +
            '\r\nNot supported by server: ' +
            ', '.join(_nosupport))


async def do_toggle(writer, option):
    """Display or toggle telnet session parameters."""
    tbl_opt = {
        'echo': writer.local_option.enabled(telopt.ECHO),
        'goahead': not writer.local_option.enabled(telopt.SGA),
        'outbinary': writer.outbinary,
        'inbinary': writer.inbinary,
        'binary': writer.outbinary and writer.inbinary,
        'xon-any': writer.xon_any,
        'lflow': writer.lflow,
    }

    if not option:
        return ('\r\n'.join('{0} {1}'.format(
            opt, 'ON' if enabled else 'off')
            for opt, enabled in sorted(tbl_opt.items())))

    msgs = []
    if option in ('echo', 'all'):
        cmd = (telopt.WONT if tbl_opt['echo'] else telopt.WILL)
        await writer.iac(cmd, telopt.ECHO)
        msgs.append('{} echo.'.format(
            telopt.name_command(cmd).lower()))

    if option in ('goahead', 'all'):
        cmd = (telopt.WILL if tbl_opt['goahead'] else telopt.WONT)
        await writer.iac(cmd, telopt.SGA)
        msgs.append('{} suppress go-ahead.'.format(
            telopt.name_command(cmd).lower()))

    if option in ('outbinary', 'binary', 'all'):
        cmd = (telopt.WONT if tbl_opt['outbinary'] else telopt.WILL)
        await writer.iac(cmd, telopt.BINARY)
        msgs.append('{} outbinary.'.format(
            telopt.name_command(cmd).lower()))

    if option in ('inbinary', 'binary', 'all'):
        cmd = (telopt.DONT if tbl_opt['inbinary'] else telopt.DO)
        await writer.iac(cmd, telopt.BINARY)
        msgs.append('{} inbinary.'.format(
            telopt.name_command(cmd).lower()))

    if option in ('xon-any', 'all'):
        writer.xon_any = not tbl_opt['xon-any']
        await writer.send_lineflow_mode()
        msgs.append('xon-any {}abled.'.format(
            'en' if writer.xon_any else 'dis'))

    if option in ('lflow', 'all'):
        writer.lflow = not tbl_opt['lflow']
        await writer.send_lineflow_mode()
        msgs.append('lineflow {}abled.'.format(
            'en' if writer.lflow else 'dis'))

    if option not in tbl_opt and option != 'all':
        msgs.append('toggle: not an option.')


    return '\r\n'.join(msgs)

class ReadLine:
    """
    A very primitive readline wrapper.

    Usage::
        rl = ReadLine(stream)
        while True:
            line = await rl()
    """
    def __init__(self, stream):
        self._stream = stream
        self._buf = ''
        self._echo = self.extra_attributes[EchoAttr]
        self._last_inp = ''

    async def __call__(self):
        buf = self._buf
        command = ""
        while True:
            if buf == "":
                buf = await self._stream.receive()
            for i,inp in enumerate(buf):
                if inp in (LF, NUL) and self._last_inp == CR:
                    self._buf = buf[i+1:]
                    return command

                elif inp in (CR, LF):
                    # first CR or LF yields command
                    self._buf = buf[i+1:]
                    return command

                elif inp in ('\b', '\x7f'):
                    # backspace over input
                    if command:
                        command = command[:-1]
                        await self.send('\b \b')

                else:
                    # buffer and echo input
                    command += inp
                    await self._stream.echo(inp)
                    self._last_inp = inp

