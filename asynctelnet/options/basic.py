from ._base import BaseOption, Forced
from ..telopt import NAWS, NEW_ENVIRON, TTYPE, TSPEED, CHARSET, SGA, ECHO, BINARY, XDISPLOC
from ..telopt import REQUEST,ACCEPTED,REJECTED,SEND,IS,INFO, Req, SubT
from ..telopt import VAR, USERVAR, VALUE, ESC, SubVar
import anyio
import codecs
from typing import Iterator,Tuple,Mapping


class StdOption(BaseOption):
    """
    A basic option which is OK with being set
    """
    async def handle_do(self):
        return True

    async def handle_will(self):
        return True


class FullOption(StdOption):
    """
    A StdOption which auto-sets itself on init
    """
    async def setup(self, tg):
        tg.start_soon(self.send_will)
        tg.start_soon(self.send_do)
        await super().setup(tg)


class _ServerOption(BaseOption):
    """
    A StdOption which auto-sets WILL on the server, DO on the client
    """
    async def setup(self, tg):
        s = self.stream
        if s.server:
            tg.start_soon(self.send_will)
        else:
            tg.start_soon(self.send_do)
        await super().setup(tg)

    async def handle_do(self):
        s = self.stream
        return s.server

    async def handle_will(self):
        s = self.stream
        return s.client


class _ClientOption(BaseOption):
    """
    A StdOption which auto-sets WILL on the client, DO on the server
    """
    async def setup(self, tg):
        s = self.stream
        if s.client:
            tg.start_soon(self.send_will)
        else:
            tg.start_soon(self.send_do)
        await super().setup(tg)

    async def remote_do(self):
        s = self.stream
        return s.client

    async def remote_will(self):
        s = self.stream
        return s.server


for _n in (NAWS, TSPEED, SGA, ECHO, BINARY, XDISPLOC):
    class _std(StdOption):
        value = _n
    _std.__name__ = n = f"std{_n.name}"
    globals()[n] = _std

for _n in (BINARY,):
    class _full(FullOption):
        value = _n
    _full.__name__ = n = f"full{_n.name}"
    globals()[n] = _full


class stdTTYPE(BaseOption):
    """
    TTYPE negotiation, :rfc:`930`.
    """
    value = TTYPE

    # server

    async def handle_will(self):
        s = self.stream
        if not s.server:
            # only servers may do TTYPE
            return False
        if not s.extra.get('term',None):
            return False
        return True

    async def handle_do(self):
        s = self.stream
        return s.client

    async def after_handle_will(self):
        s = self.stream
        await s.send_subneg(TTYPE, SEND)

    async def handle_reply(self, ttype):
        """
        Callback for TTYPE response, server side.

        TTYPE may be requested multiple times, we honor this system and
        attempt to cause the client to cycle, as their first response may
        not be their most significant. All responses held as 'ttype{n}',
        where {n} is their serial response order number.
       
        According to the RFC, the most recently received terminal type
        is assigned to ``extra.TERM``, even when unsolicited.
        """
        s = self.stream
        from ..telopt import SEND

        key = f'ttype{s._ttype_count}'
        s.extra[key] = ttype
        if ttype:
            s.extra.TERM = ttype

        _lastval = s.extra.get(f'ttype{s._ttype_count-1}', '')
        
        if key != 'ttype1' and ttype == s.extra.get('ttype1', None):
            # cycle has looped, stop
            s.log.debug('ttype cycle stop at %s: %s, looped.', key, ttype)
            s.extra.term_done = True
        
        elif (not ttype or s._ttype_count > s.TTYPE_LOOPMAX):
            # empty reply string or too many responses!
            s.log.warning('ttype cycle stop at %s: %s.', key, ttype)
           
        elif (s._ttype_count == 3 and ttype.upper().startswith('MTTS ')):
            val = s.extra.ttype2
            s.log.debug(
                'ttype cycle stop at %s: %s, using %s from ttype2.',
                key, ttype, val)
            s.extra.TERM = val

        elif (ttype == _lastval):
            s.log.debug('ttype cycle stop at %s: %s, repeated.', key, ttype)
            s.extra.term_done = True

        else:
            s.log.debug('ttype cycle cont at %s: %s.', key, ttype)
            s._ttype_count += 1
            await s.send_subneg(TTYPE, SEND)


    # client

    async def handle_do(self):
        s = self.stream
        if not s.client:
            return False
        if not s.extra.get('term',''):
            return False
        return True

    def get_reply(self):
        """
        Current terminal type.

        If you support multiple types, return them one by one.
        At the end of the list, replicate the last type.

        The default always sends ``extra.term``.
        """
        s = self.stream
        return s.extra.term


    # both

    async def process_sb(self, buf):
        s = self.stream
        opt,buf = buf[0],buf[1:]
        from ..telopt import IS,SEND

        opt_kind = {IS: 'IS', SEND: 'SEND'}.get(opt)           

        if opt == IS:
            # server is supposed to have this
            if s.server:
                s.log.debug('R: TTYPE %s: %r', opt_kind, buf)
                ttype_str = buf.decode('ascii')
                await self.handle_reply(ttype_str)
                return

        elif opt == SEND:
            # only a client is supposed to have this
            if s.client and s.extra.get('term',None):
                s.log.debug('R: TTYPE %s: %r', opt_kind, buf)
                ttype_str = self.get_reply()
                await s.send_subneg(TTYPE, IS, ttype_str.encode("ascii"))
                return

        s.log.warning('R: TTYPE %s: %r', opt_kind, buf)
        await self.disable()


class stdCHARSET(BaseOption):
    """
    CHARSET negotiation
    """
    value = CHARSET

    _charset_tried:str = None

    async def send_request(self) -> bool:
        """
        Send a CHARSET
        """
        s = self.stream
        if not await self.loc.send_yes():
            return False
        if not s._charset_lock:
            await self.send_sb()

        if s._charset_lock:
            await s._charset_lock.wait()
        return True

    async def send_sb(self, **kw):
        from ..telopt import REQUEST
        s = self.stream
                                            
        charsets = s._charsets_wanted
        if charsets is None:
            s._charsets_wanted = charsets = s.get_supported_charsets() or ("UTF-8","LATIN9","LATIN1","US-ASCII")

        if self.has_local:
            if not s._charset_lock:
                s._charset_lock = anyio.Event()
            if not charsets:
                s.log.error("Charset list is empty!")
                await s._set_charset(None)
                return                          
            await s.send_subneg(CHARSET,REQUEST,b';',';'.join(charsets).encode("ascii"))
        else:
            if not await self.set_local(True):
                return False
            # if True, we got a DO back, which triggers handle_do

    async def handle_will(self):
        """
        The remote side sent a WILL. Ack if we do charsets.
        """
        s = self.stream

        return isinstance(s._charset, str)


    async def after_handle_do(self):
        """
        The remote side accepts our WILL. Start negotiating.
        """ 
        await self._send_request()

    async def _send_request(self):
        """
        Send a CHARSET REQUEST subnegotiation message.
        """

        s = self.stream
        from ..telopt import REQUEST

        if not self.loc.state:
            raise RuntimeError("You can't do that not.")

        if not isinstance(s._charset, str):
            return False
        if s._charset_lock is not None:      
            return True
            
        charsets = s._charsets_wanted
        if charsets is None:
            s._charsets_wanted = charsets = s.get_supported_charsets() or ("UTF-8","LATIN9","LATIN1","US-ASCII")
        if not charsets:
            s.log.error("Charset list is empty!")
            await self.send_wont(Forced.yes)
            return

        s._charset_lock = anyio.Event()
        # executed by the dispatcher after sending WILL
        return await s.send_subneg(CHARSET,REQUEST,b';',';'.join(charsets).encode("ascii"))

    async def reply_do(self):
        """
        The remote side accepted our WILL. Start negotiating.
        """ 
        await self._send_request()

    def get_response(self, offers):
        """
        Callback for responding to CHARSET requests.

        Receives a list of character encodings offered by the server
        as ``offers`` such as ``('LATIN-1', 'UTF-8')``, for which the
        client may return a value it agrees to use, or None to disagree to
        all available offers.

        The default implementation selects any matching encoding that
        Python is capable of using, preferring any that matches
        :py:attr:`encoding` if matched in the offered list.

        :param list offered: list of CHARSET options offered by server.
        :returns: character encoding agreed to be used.
        :rtype: Union[str, None]
        """
        ## TODO fix this

        s = self.stream
        if s.client and hasattr(s,"DEFAULT_LOCALE"):
            selected = None
            cur = s.extra.charset
            if cur:
                cur = cur.lower()
                for offer in offers:
                    if offer.lower() == cur:
                        s.log.debug('encoding unchanged: %s', offer)
                        return offer

            if self._charset_tried is not None:
                self._charset_tried = None
            elif len(offers) == 1 and cur:
                s.log.debug('Skipping %s: we want %s', offers[0], cur)
                self._charset_tried = offers[0]
                return None

            for offer in offers:
                try:
                    codec = codecs.lookup(offer)
                except LookupError as err:
                    s.log.info('Unknown: %s', err)
                else:
                    s.extra.charset = codec.name
                    s.extra.lang = s.DEFAULT_LOCALE + '.' + codec.name
                    selected = offer
                    break
            if selected is not None:
                s.log.debug('encoding negotiated: %s', selected)
            else:
                s.log.warning('No suitable encoding offered by server: %r.', offers)
            return selected
        else:
            if s._charset:
                loc = s._charset.lower()
                for c in offers:
                    if c.lower() == loc:
                        return c

            # Local charset set? use that.
            import locale    
            loc = locale.getpreferredencoding()
            if loc:
                loc = loc.lower()
                for c in offers:
                    if c.lower() == loc:
                        return c

            # Otherwise use the first we can find in their list that works.
            for c in offers:
                try:
                    codecs.getincrementaldecoder(c)
                except LookupError:
                    continue
                else:
                    s.log.info("Charsets: charset %s not offered, using %s", loc, c)
                    return c
            s.log.warning("Charsets: no idea what to do with %r", offers)
            return None


    async def process_sb(self, buf):
        s = self.stream
        opt,buf = buf[0],buf[1:]
        from ..telopt import REQUEST,ACCEPTED,REJECTED, Req

        try:
            opt_kind = Req(opt).name
        except ValueError:
            opt_kind = f'?{opt}'

        if opt == REQUEST:
            s.log.debug('R: IAC SB %s %s: %r', 'CHARSET', opt_kind, buf.decode("ascii"))
            if s._charset_lock is not None and s.server:
                if not s._charset_retry:
                    # NACK this request: simultaneous requests sent by both sides.
                    await s.send_subneg(CHARSET,REJECTED)
                    return
                # However, we need to guard against the case where the
                # client also rejects our choice because it doesn't
                # like it. In that case the incoming reject, below, sets
                # this flag so we know we may process the client's new
                # request.
                s._charset_retry = False

            if buf.startswith(b'TTABLE '):
                buf = buf[8:]  # ignore TTABLE_V
            sep,buf = buf[0:1],buf[1:]
            offers = [charset.decode('ascii') for charset in buf.split(sep)]
            selected = self.get_response(offers)

            if selected is None:
                await s.send_subneg(CHARSET, REJECTED)
                if s.client and s._charset_lock is not None and self.has_local:
                    # The server has rejected my request due to a
                    # collision. Thus I need to retry.
                    s._charset_retry = True
                else:
                    await s._set_charset(selected)
            else:
                await s.send_subneg(CHARSET, ACCEPTED, selected.encode('ascii'))
                await s._set_charset(selected)

        elif opt == ACCEPTED:
            s.log.debug('R: IAC SB %s %s: %r', 'CHARSET', opt_kind, buf.decode("ascii"))
            charset = buf.decode('ascii')
            if not await s._set_charset(charset):
                # Duh. The remote side returned something we can't handle.
                await s._set_charset("UTF-8", False)

        elif opt == REJECTED:
            s.log.warning('R: IAC SB CHARSET REJECTED')
            if s._charset_retry:
                if s.server:
                    # this is normal on the client
                    s.log.warning("Charset: retry set and we get a REJ??")
                    s._charset_retry = False
            elif s._charsets_wanted:
                s._charsets_wanted = None
            else:
                await s._set_charset(None)
                return

            if s._charset_lock:
                # Other side rejected us, either because of overlapping
                # requests or because it didn't like ours: remember that it
                # did, see above
                if s.client:
                    # Server didn't like our first attempt, so try again
                    await self.send_sb()
                else:
                    s._charset_retry = True

        else:
            s.log.warning("R: SB CHARSET nonsense: %r %r", opt, buf)
            await self.disable()


class stdNEW_ENVIRON(StdOption):
    """
    Handle NEW_ENVIRON, :rfc:`1572`.
    """
    value = NEW_ENVIRON

    # Server

    async def handle_will(self):
        """    
        Returns True if request is valid for telnet state, and was sent.
        """
        s = self.stream

        if not s.server:
            s.log.error('NEW_ENVIRON DO may only be sent by server')
            return False
        return True

    def get_request(self):
        """
        Returns the list of variables the server wants from the client.
        """
        from ..telopt import VAR, USERVAR
        return ['LANG', 'TERM', 'COLUMNS', 'LINES', 'DISPLAY', 'COLORTERM',
                VAR, USERVAR]

    async def handle_reply(self, mapping):
        """
        Handle the incoming NEW_ENVIRON response."""
        s = self.stream

        # A well-formed client responds with empty values for variables to
        # mean "no value".  They might have it, they just may not wish to
        # divulge that information.  We pop these keys as a side effect in
        # the result statement of the following list comprehension.
        no_value = [mapping.pop(key) or key
                    for key, val in list(mapping.items())
                    if not val]

        # because we are working with "untrusted input", we make one fair
        # distinction: all keys received by NEW_ENVIRON are in uppercase.
        # this ensures a client may not override trusted values such as
        # 'peer'.
        u_mapping = {key.upper(): val for key, val in list(mapping.items())}

        s.log.debug('on_environ received: %r', u_mapping)

        s.extra.update(u_mapping)
        if 'LANG' in u_mapping:
            charset = u_mapping['LANG'].rsplit(".")[-1]
            await s._set_charset(charset)



    async def after_handle_will(self):
        s = self.stream
        request_list = self.get_request()

        if not request_list:
            s.log.debug('request_environ: server protocol makes no demand, '
                           'no request will be made.')
            return False

        response = bytearray([SEND])

        for env_key in request_list:
            if env_key in (VAR, USERVAR):
                # VAR followed by IAC,SE indicates "send all the variables",
                # whereas USERVAR indicates "send all the user variables".
                # In today's era, there is little distinction between them.
                response.append(env_key)
            else:
                response.extend(_escape_environ([(VAR,env_key.encode('ascii'))]))
        await s.send_subneg(NEW_ENVIRON, response)
        return True

    # Client

    async def handle_do(self):
        """    
        Returns True if request is valid for telnet state, and was sent.
        """
        s = self.stream

        if not s.client:
            s.log.error('NEW_ENVIRON WILL may only be sent by client')
            return False
        return True

    def get_reply(self, keys):
        """
        Create a response to to NEW_ENVIRON requests.

        :param dict keys: Values are requested for the keys specified.
           When empty, all environment values that wish to be volunteered
           should be returned.
        :returns: dictionary of environment values requested, or an
            empty string for keys not available. A return value must be
            given for each key requested.
        :rtype: dict
        """

        s = self.stream
        env = {
            'LANG': s.extra.lang,
            'TERM': s.extra.term,
            'DISPLAY': s.extra.xdisploc,
            'LINES': s.extra.rows,
            'COLUMNS': s.extra.cols,
        }
        fn = getattr(s,"get_windowsize",None)
        if fn:
            env['LINES'], env['COLUMNS'] = fn()

        return env
        return {key: env.get(key, '') for key in keys} or env

    async def process_sb(self, buf):
        """
        Callback handles (IAC, SB, NEW_ENVIRON, <buf>, SE), :rfc:`1572`.

        For requests beginning with IS, or subsequent requests beginning
        with INFO, any callback registered by :meth:`set_ext_callback` of
        cmd NEW_ENVIRON is passed a dictionary of (key, value) replied-to
        by client.

        For requests beginning with SEND, the callback registered by
        ``set_ext_send_callback`` is provided with a list of keys
        requested from the server; or None if only VAR and/or USERVAR
        is requested, indicating to "send them all".
        """
        s = self.stream
        opt,buf = buf[0],buf[1:]

        opt_kind = SubT(opt).name
        
        env = _decode_env_buf(buf)

        if opt in (IS, INFO):
            if s.server and env:
                s.log.debug('recv SB Env %s: %r', opt_kind, buf)
                await self.handle_reply(env)
                return
        
        elif opt == SEND:
            if s.client:
                s.log.debug('recv SB Env %s: %r', opt_kind, buf)
                # client-side, we do _not_ honor the 'send all VAR' or 'send all
                # USERVAR' requests -- it is a small bit of a security issue.
                send_env = _encode_env_buf(
                    self.get_reply(env.keys()))
                s.log.debug('env send: %r', send_env)
                await s.send_subneg(NEW_ENVIRON, IS, send_env)
                return

        s.log.warning('recv SB Env %s: %r', opt_kind, buf)
        await self.disable()


bVAR = bytes([VAR])
bUSERVAR = bytes([USERVAR])
bVALUE = bytes([VALUE])
bESC = bytes([ESC])

EnvTagList = Iterator[Tuple[SubVar,bytes]]

def _escape_environ(seq: EnvTagList) -> bytes:
    """
    Return a buffer for this sequence of tagged values.

    :param bytes buf: a sequence of (SubVar,bytes) tuples
    :returns: bytes buffer
    :rtype: bytes
    """
    buf = bytearray()
    for t,s in seq:
        buf.append(t)
        for b in s:
            if b < 4:
                buf.append(SubVar.ESC)
            buf.append(b)
    return buf

def _unescape_environ(buf: bytes) -> EnvTagList:
    """
    Return a (SubVar,bytes) tuple iterator sourcing this sequence.

    :param bytes buf: given bytes buffer
    :returns: bytes buffer with escape characters removed.
    :rtype: bytes
    """
    bi = iter(buf)
    try:
        typ = next(bi)
    except StopIteration:
        return
    while True:
        buf = bytearray()
        while True:
            try:
                c = next(bi)
                if c == SubVar.ESC:                                         
                    c = next(bi)                                            
                elif c < 4:                                                 
                    break                                                   
                buf.append(c)                                               
            except StopIteration:                                           
                yield (typ,buf.decode("utf-8"))                             
                return
        yield (typ,buf.decode("utf-8"))                                      
        typ = c                                                              

def _encode_env_buf(env: Mapping[str,str]) -> bytes:                         
    """
    encode dictionary for transmission as environment variables, :rfc:`1572`.
        
    :param bytes buf: dictionary of environment values.
    :returns: bytes buffer meant to follow sequence IAC SB NEW_ENVIRON IS.
        It is not terminated by IAC SE.
    :rtype: bytes
         
    Returns bytes array ``buf`` for use in sequence (IAC, SB,
    NEW_ENVIRON, IS, <buf>, IAC, SE) as set forth in :rfc:`1572`.
    """
    def _make_seq():
        for k,v in env.items():
            if v is None:
                continue
            yield SubVar.VAR,k.encode("ascii")
            yield SubVar.VALUE,str(v).encode("utf-8")

    return _escape_environ(_make_seq())
        
        
def _decode_env_buf(buf):
    """
    Decode environment values to dictionary, :rfc:`1572`.
        
    :param bytes buf: bytes array following sequence IAC SB NEW_ENVIRON
        SEND or IS up to IAC SE. 
    :returns: dictionary representing the environment values decoded from buf.
    :rtype: dict
        
    This implementation does not distinguish between ``USERVAR`` and ``VAR``.
    """
    env = {}
    k = None           
    for t,v in _unescape_environ(buf):
        if t == SubVar.VAR or t == SubVar.USERVAR:
            if k is not None:
                env[k] = None
            k = v
        elif t == SubVar.VALUE:
            if k is None:
                raise ValueError("value without key in %r", buf)
            env[k] = v
            k = None
    return env

