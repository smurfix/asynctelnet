from ._base import BaseOption
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


class CHARSET(BaseOption):
    """
    CHARSET negotiation
    """
    value = 42

    async def send_sb(self, **kw):
        from ..telopt import REQUEST
        s = self.stream
                                            
        charsets = s._charsets_wanted
        if charsets is None:
            s._charsets_wanted = charsets = s.get_supported_charsets() or ("UTF-8","LATIN9","LATIN1","US-ASCII")

        if self.has_will:
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

    async def handle_sb(self, buf):
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
                if s.client and s._charset_lock is not None and self.has_will:
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


