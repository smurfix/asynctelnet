============================
Client and server subclasses
============================

AsyncTelnet is extensible. While the base classes support common
extensions, more can be added via subclassing.

All methods described here are called asynchronously unless explicitly
marked as sync.


Server error handling
=====================

If you write a nontrivial server, it may be a good idea to wrap the
server's ``ProtocolFactory`` with an error handler. Otherwise any exception
that propagates through it will take down your server and all other
clients.


Startup option handling
=======================

After connecting, both client and server call their ``setup()`` method. By
default this sends an initial TTERM DO/WILL exchange and then, if positive,
exchanges a couple of other Telnet options to establish an initial shared
state.

If you want to modify this behavior, you need to override this method.

``setup`` accepts one argument, ``has_tterm``, which can be ``None`` (the
default), ``False`` (assume that there is no terminal, roughly equivalent
to setting ``term=''``), ``True`` (assume that there is a terminal, do
exchange the other options), or a timeout in seconds.

If the timeout is reached, ``setup()`` will raise a ``TimeoutError``. If
you want to continue, it is safe to proceed.

If you want a timeout on the whole initial option exchange, wrap ``setup``
in ``with anyio.fail_after(TIMEOUT)`` (or ``move_on_after``).

This corresponds to the original ``connect_minwait`` and
``connect_maxwait`` options. I chose to not support these because while
they do set a timeout, they don't tell AsyncTelnet what to do when they are
exceeded.


Option management
=================

This section describes how to actively ask the remote side whether it
supports an option.

Interrupting an option request (e.g. cancellation by timeout) puts the option
in "timeout" mode. Another request for that option will raise a `TimeoutError`
unless either ``force`` is set or the remote does answer.


local options
+++++++++++++

You call `await local_option(OPTION, value=True, force=None)` to send a
WILL or WONT (depending on the second argument) to the other side. This
function returns ``True`` if the remote answers (or answered) with ``DO``,
``False`` otherwise.

If the remote answer is known and matches your query, nothing is sent
unless you set the ``force`` parameter.

It is an error to call this function while a previous call is still
running. In that case you may omit the ``value`` parameter.

remote options
++++++++++++++

You call `await remote_option(OPTION, value=True, force=None)` to send a
DO or DONT (depending on the second argument) to the other side. This
function returns ``True`` if the remote answers (or answered) with ``WILL``,
``False`` otherwise.

If the remote answer is known and matches your query, nothing is sent
unless you set the ``force`` parameter.

It is an error to call this function while a previous call is still
running. In that case you may omit the ``value`` parameter.


Generic Option handling
=======================

This section describes how to react when the remote side asks whether you
support an option.

These procedures can return ``True``, ``False``, or a coroutine. The
latter is interpreted as ``True`` and executed after sending the
corresponding reply. You commonly use this feature to trigger sending a
subnegotiation: simply ``return self.send_subneg(‹option›, …)`` *without*
the otherwise-required ``await``.

set_command_handler
+++++++++++++++++++

Use this function to register a specific command handler without
subclassing. Parameters: the command, the option, and the async callback
(no arguments).

handle_will_‹option›
++++++++++++++++++++

Called when the remote sends a WILL command. The result determines whether
``DO`` or ``DONT`` should be returned.

handle_wont_‹option›
++++++++++++++++++++

Called when the remote sends a WILL command. The result determines whether
``DO`` or ``DONT`` should be returned.

handle_do_‹option›
++++++++++++++++++++

Called when the remote sends a WILL command. The result determines whether
``WILL`` or ``WONT`` should be returned.

handle_dont_‹option›
++++++++++++++++++++

Called when the remote sends a WILL command. The result determines whether
``WILL`` or ``WONT`` should be returned.

handle_‹option›
+++++++++++++++

This is a fallback handler, called when no more specific handler exists,
with the command as argument.

handle_will, handle_wont, handle_do, handle_dont
++++++++++++++++++++++++++++++++++++++++++++++++

These are fallback handlers, called when no specific handler exists, with
the option. The default implementation of all four returns ``False``.


Specific Options
================


charset
+++++++

RFC 2066.

The handlers in this section are not asynchronous.

get_supported_charsets
----------------------

Called with no arguments. Returns a list of encodings to be sent to the
remote side.

select_charset
--------------

Called with a list of encodings. It should return on of
them, or the empty string.

on_charset
----------

Called with the new encoding when your reader processes the ``SetCharset`` message.

This method is mainly used for testing; real code should process the actual
message.


ttype
+++++

RFC 1091.

AsyncTelnet implements ``handle_will_ttype`` and ``handle_do_ttype``.

handle_send_ttype
-----------------

Called without arguments when the remote requests a terminal type.
An attribute check is used to determine whether to send WILL. Implemented
in `TelnetClient`.

handle_recv_ttype
-----------------

Called with the incoming terminal type when the remote sends it.
An attribute check is used to determine whether to send DO. Implemented in
`TelnetServer`.
