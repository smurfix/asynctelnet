# PYTHONPATH=. examples/server --shell examples.server:serve

import anyio

async def serve(stream):
	if not await stream.request_charset("utf-8"):
		await stream.writeline("Huh. You don't support setting UTF-8. Shame on you.")
		await stream.writeline("")
	await stream.writeline("Hello.")
	try:
		while True:
			await stream.send("> ")
			await stream.send_ga()
			inp = await stream.readline()
			await stream.writeline("You sent %r. Oh well." % (inp,))

	except (anyio.EndOfStream, anyio.ClosedResourceError):
		return
