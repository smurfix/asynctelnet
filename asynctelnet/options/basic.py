from ._base import BaseOption, Forced
import anyio


class BINARY(BaseOption):
    """
    8-bit data path
    """
    value = 0

    async def remote_do(self):
        return True

    async def remote_will(self):
        return True


class TTYPE(BaseOption):
    """
    TTYPE negotiation
    """
    value = 24

    # server

    async def handle_will(self):
        s = self.stream
        if not s.server:
            return False
        if not s.extra.get('tterm',None):
            return False
        return True

    async def after_handle_will(self):
        s = self.stream
        await s.send_subneg(TTYPE, SEND)

    async def handle_send(self):
        s = self.stream
        return s.extra.term

    async def handle_recv(self, ttype):
        """Callback for TTYPE response, :rfc:`930`."""
        # TTYPE may be requested multiple times, we honor this system and
        # attempt to cause the client to cycle, as their first response may
        # not be their most significant. All responses held as 'ttype{n}',
        # where {n} is their serial response order number.
        #
        # The most recently received terminal type by the server is
        # assumed TERM by this implementation, even when unsolicited.
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
        if not s.extra.get('tterm',''):
            return False
        return True

    async def process_sb(self, buf):
        """Callback handles IAC-SB-TTYPE-<buf>-SE."""
        s = self.stream
        opt,buf = buf[0],buf[1:]
        from ..telopt import IS,SEND

        opt_kind = {IS: 'IS', SEND: 'SEND'}.get(opt)           

        if opt == IS:
            # server is supposed to have this
            if s.server:
                s.log.debug('R: TTYPE %s: %r', opt_kind, buf)
                ttype_str = buf.decode('ascii')
                await self.handle_recv(ttype_str)
                return

        elif opt == SEND:
            # only a client is supposed to have this
            if s.client and s.extra.get('term',None):
                s.log.debug('R: TTYPE %s: %r', opt_kind, buf)
                ttype_str = self.handle_send()
                await s.send_subneg(TTYPE, IS, ttype_str.encode("ascii"))
                return

        s.log.warning('R: TTYPE %s: %r', opt_kind, buf)
        await self.loc.send_no(Forced.yes)
        await self.rem.send_no(Forced.yes)


class CHARSET(BaseOption):
    """
    CHARSET negotiation
    """
    value = 42

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


    async def handle_do(self):
        """
        The remote side accepts our WILL. Start negotiating.
        """ 
        s = self.stream
        from ..telopt import REQUEST

        if not isinstance(s._charset, str):
            return False
        if s._charset_lock is not None:      
            return True
            
        charsets = s._charsets_wanted
        if charsets is None:
            s._charsets_wanted = charsets = s.get_supported_charsets() or ("UTF-8","LATIN9",       + "LATIN1","US-ASCII")
        if not charsets:
            s.log.error("Charset list is empty!")
            await self.send_wont(Forced.yes)
            return

        s._charset_lock = anyio.Event()
        # executed by the dispatcher after sending WILL
        return await s.send_subneg(CHARSET,REQUEST,b';',';'.join(charsets).encode("ascii"))

    async def reply_do(self):
        """
        The remote side accepts our WILL. Start negotiating.
        """ 
        await self.handle_do()

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
            selected = s.select_charset(offers)

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
                    await s._request_charset()
                else:
                    s._charset_retry = True

        else:
            s.log.warning("R: SB CHARSET nonsense: %r %r", opt, buf)
            await self.loc.send_wont(Forced.yes)
            await self.rem.send_wont(Forced.yes)


