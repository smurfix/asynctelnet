#!/usr/bin/python3

import anyio, asynctelnet

async def shell(tcp):
    async with asynctelnet.TelnetClient(tcp, client=True) as stream:
        while True:
            # read stream until '?' mark is found
            outp = await stream.receive(1024)
            if not outp:
                # End of File
                break
            elif '?' in outp:
                # reply all questions with 'y'.
                await stream.send('y')

            # display all server output
            print(outp, flush=True)

    # EOF
    print()

async def main():
    async with await connect_tcp('localhost', 56023) as client:
        await shell(client)
anyio.run(main)
