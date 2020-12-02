#!/usr/bin/python3

import anyio, asynctelnet

async def shell(tcp):
    async with asynctelnet.TelnetServer(tcp) as stream:
        # this will fail if no charset has been negotiated
        await stream.send('\r\nWould you like to play a game? ')
        inp = await reader.receive(1)
        if inp:
            await stream.echo(inp)
            await stream.send('\r\nThey say the only way to win '
                                'is to not play at all.\r\n')

async def main():
    listener = await anyio.create_tcp_listener(local_port=56023)
    await listener.serve(shell)
anyio.run(main)
