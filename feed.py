"""Dhan live market feed (tick by tick) with a local relay to the browser.

One background thread holds a WebSocket to Dhan's feed (wss://api-feed.dhan.co, binary,
little endian), keeps the latest tick per instrument in memory, and runs a small
WebSocket server on 127.0.0.1 that pushes changed ticks to the app's live widgets
several times a second.
"""
from __future__ import annotations

import asyncio
import json
import socket
import struct
import threading
import time
from datetime import datetime, timedelta, timezone

import websockets

FEED_URL = "wss://api-feed.dhan.co?version=2&token={token}&clientId={cid}&authType=2"
SEG_NAME = {0: "IDX_I", 1: "NSE_EQ", 2: "NSE_FNO", 3: "NSE_CURRENCY", 4: "BSE_EQ", 5: "MCX_COMM",
            7: "BSE_CURRENCY", 8: "BSE_FNO"}
SUB_FULL, SUB_QUOTE = 21, 17
PACKET_SIZE = {1: 16, 2: 16, 4: 50, 5: 12, 6: 16, 7: 8, 8: 162, 50: 10}
IST = timezone(timedelta(hours=5, minutes=30))
PUSH_EVERY = 0.15  # seconds between relay pushes (ticks are coalesced per instrument)
INSTANCES: list = []  # running feeds (the app keeps one)
VERSION = 2  # bump when DhanFeed changes, so a running app replaces its old feed object
# Reason codes Dhan sends in its disconnect packet (code 50)
DISCONNECT = {
    805: "too many live-feed connections on this Dhan account (max 5). Close other Omnipuls windows/copies or "
         "other apps using the Dhan feed, then press Restart live feed",
    806: "Dhan Data APIs are not active on this account",
    807: "the access token has expired: generate a new one on web.dhan.co",
    808: "authentication failed: check the Client ID",
    809: "the access token is invalid: generate a new one on web.dhan.co",
    810: "the Client ID is invalid",
}
FATAL = {806, 807, 808, 809, 810}  # retrying won't help until the token / plan changes


def key(seg: str, sid) -> str:
    return f"{seg}:{int(sid)}"


def _ltt(epoch: int) -> str:
    # Dhan sends trade time as epoch seconds already shifted to IST, so read it as naive UTC
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).strftime("%d/%m/%Y %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def parse(buf: bytes, store: dict) -> list[str]:
    """Parse one or more packets from a binary message into store. Returns the keys that changed."""
    changed, i = [], 0
    while i + 8 <= len(buf):
        code, length, seg, sid = struct.unpack_from("<BHBi", buf, i)
        size = length if 8 <= length <= len(buf) - i else PACKET_SIZE.get(code, len(buf) - i)
        p = buf[i:i + size]
        i += max(size, 8)
        segname = SEG_NAME.get(seg)
        if code == 50:
            reason = struct.unpack_from("<h", p, 8)[0] if len(p) >= 10 else 0
            store.setdefault("__status__", {})["disconnect"] = reason
            continue
        if segname is None or code == 7:
            continue
        k = key(segname, sid)
        t = store.setdefault(k, {"seg": segname, "id": sid})
        try:
            if code in (1, 2) and len(p) >= 16:
                ltp, ltt = struct.unpack_from("<fi", p, 8)
                t.update(ltp=ltp, ltt=ltt)
            elif code == 4 and len(p) >= 50:
                ltp, ltq, ltt, atp, vol, tsq, tbq, o, c, h, lo = struct.unpack_from("<fhifiiiffff", p, 8)
                t.update(ltp=ltp, ltq=ltq, ltt=ltt, atp=atp, vol=vol, tsq=tsq, tbq=tbq, open=o, high=h, low=lo,
                         day_close=c)
            elif code == 5 and len(p) >= 12:
                t["oi"] = struct.unpack_from("<i", p, 8)[0]
            elif code == 6 and len(p) >= 16:
                pc, poi = struct.unpack_from("<fi", p, 8)
                t.update(prev_close=pc, prev_oi=poi)
            elif code == 8 and len(p) >= 62:
                (ltp, ltq, ltt, atp, vol, tsq, tbq, oi, oih, oil, o, c, h, lo) = struct.unpack_from("<fhifiiiiiiffff", p, 8)
                t.update(ltp=ltp, ltq=ltq, ltt=ltt, atp=atp, vol=vol, tsq=tsq, tbq=tbq, oi=oi, oi_hi=oih, oi_lo=oil,
                         open=o, high=h, low=lo, day_close=c)
                depth = []
                for j in range(5):
                    off = 62 + j * 20
                    if off + 20 > len(p):
                        break
                    bq, aq, bo, ao, bp, ap = struct.unpack_from("<iihhff", p, off)
                    depth.append((bq, aq, bo, ao, bp, ap))
                t["depth"] = depth
            else:
                continue
        except struct.error:
            continue
        t["ts"] = time.time()
        changed.append(k)
    return changed


def to_quote(t: dict) -> dict:
    """A tick in the same shape as Dhan's REST quote (ohlc.close = previous close)."""
    depth = t.get("depth") or []
    return {
        "last_price": t.get("ltp"), "last_quantity": t.get("ltq"), "last_trade_time": _ltt(t.get("ltt", 0)),
        "average_price": t.get("atp"), "volume": t.get("vol"), "buy_quantity": t.get("tbq"),
        "sell_quantity": t.get("tsq"), "oi": t.get("oi"), "oi_day_high": t.get("oi_hi"), "oi_day_low": t.get("oi_lo"),
        "ohlc": {"open": t.get("open"), "high": t.get("high"), "low": t.get("low"), "close": t.get("prev_close")},
        "depth": {"buy": [{"quantity": d[0], "orders": d[2], "price": d[4]} for d in depth],
                  "sell": [{"quantity": d[1], "orders": d[3], "price": d[5]} for d in depth]},
        "prev_oi": t.get("prev_oi"), "_feed": True, "_ts": t.get("ts"),
    }


def _free_port(start=8765) -> int:
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return 0


class DhanFeed:
    def __init__(self, client_id: str, token: str):
        self.client_id, self.token = str(client_id), token
        self.ticks: dict = {}
        self.wanted: dict[str, tuple[str, int]] = {}
        self._sent: set[str] = set()
        self._dirty: set[str] = set()
        self._lock = threading.Lock()
        self.connected = False
        self.error = ""
        self.msgs = 0
        self.attempts = 0
        self.last_msg_at = 0.0
        self.connected_at = 0.0
        self.fatal = False
        self.started = time.time()
        self.relay_port = _free_port()
        self._stop = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None
        self._clients: dict = {}
        self.thread = threading.Thread(target=self._run, name="dhan-feed", daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ public API (any thread)

    def subscribe(self, pairs):
        new = []
        with self._lock:
            for seg, sid in pairs:
                if sid is None:
                    continue
                k = key(seg, sid)
                if k not in self.wanted and len(self.wanted) < 4900:
                    self.wanted[k] = (seg, int(sid))
                    new.append(k)
        if new and self._loop and self.connected:
            asyncio.run_coroutine_threadsafe(self._send_subs(new), self._loop)

    def quote(self, seg: str, sid) -> dict | None:
        t = self.ticks.get(key(seg, sid))
        return to_quote(t) if t and t.get("ltp") else None

    def healthy(self) -> bool:
        return self.connected and not self.error

    def state(self) -> tuple[str, str]:
        """(kind, text) for the UI. kind: live | idle | connecting | error."""
        now = time.time()
        if self.error and (self.fatal or not self.connected):
            return "error", self.error
        if self.connected:
            if self.last_msg_at and now - self.last_msg_at < 30:
                return "live", "Dhan live ticks"
            return "idle", "Dhan feed on · market closed" if self.msgs == 0 or now - self.last_msg_at > 120 \
                else "Dhan feed on · waiting for ticks"
        waited = int(now - self.started)
        return "connecting", f"Dhan live feed connecting… ({self.attempts} attempt{'s' if self.attempts != 1 else ''}, {waited}s)"

    def stop(self):
        self._stop = True
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

    async def _shutdown(self):
        try:
            if self._ws is not None:
                await self._ws.close()
            if getattr(self, "_server", None) is not None:
                self._server.close()
        except Exception:
            pass
        me = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t is not me]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.get_running_loop().stop()

    # ------------------------------------------------------------ internals

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._relay())
        self._loop.create_task(self._pusher())
        self._loop.create_task(self._feed_forever())
        try:
            self._loop.run_forever()
        except Exception:
            pass

    async def _send_subs(self, keys):
        ws = self._ws
        if ws is None:
            return
        keys = [k for k in keys if k not in self._sent]
        by_mode: dict[int, list] = {}
        for k in keys:
            seg, sid = self.wanted[k]
            mode = SUB_QUOTE if seg == "IDX_I" else SUB_FULL
            by_mode.setdefault(mode, []).append({"ExchangeSegment": seg, "SecurityId": str(sid)})
        for mode, items in by_mode.items():
            for i in range(0, len(items), 100):
                chunk = items[i:i + 100]
                await ws.send(json.dumps({"RequestCode": mode, "InstrumentCount": len(chunk), "InstrumentList": chunk}))
        self._sent.update(keys)

    async def _feed_forever(self):
        backoff = 1
        while not self._stop:
            self.attempts += 1
            try:
                url = FEED_URL.format(token=self.token, cid=self.client_id)
                async with websockets.connect(url, max_size=2 ** 22, ping_interval=None, open_timeout=20) as ws:
                    self._ws, self.connected, self.error = ws, True, ""
                    self.connected_at = time.time()
                    self.ticks.pop("__status__", None)
                    self._sent = set()
                    backoff = 1
                    with self._lock:
                        keys = list(self.wanted)
                    await self._send_subs(keys)
                    async for msg in ws:
                        if isinstance(msg, (bytes, bytearray)):
                            changed = parse(bytes(msg), self.ticks)
                            self.msgs += 1
                            if changed:
                                self.last_msg_at = time.time()
                                self._dirty.update(changed)
                            st = self.ticks.get("__status__", {})
                            code = st.get("disconnect")
                            if code:
                                why = DISCONNECT.get(code, "see Dhan's API status")
                                self.error = f"Dhan closed the live feed (code {code}): {why}."
                                self.fatal = code in FATAL
            except Exception as e:  # network drop, auth failure, etc.
                msg = str(e)
                if "401" in msg or "403" in msg:
                    self.error = "Dhan refused the live feed: the access token is invalid or expired."
                    self.fatal = True
                elif "timed out" in msg.lower() or "getaddrinfo" in msg.lower() or "11001" in msg:
                    self.error = "Can't reach Dhan's live feed (api-feed.dhan.co): check the internet connection, " \
                                 "firewall or antivirus."
                elif not self.error:
                    self.error = f"Live feed disconnected: {msg[:160]}"
            self._ws, self.connected = None, False
            if self._stop:
                break
            if self.fatal:
                await asyncio.sleep(300)  # don't hammer Dhan with a bad token; Restart live feed retries now
                continue
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60 if "805" in self.error else 30)

    # ---- relay to the browser

    async def _relay(self):
        if not self.relay_port:
            return

        async def handler(ws):
            self._clients[ws] = set()
            try:
                async for msg in ws:
                    try:
                        req = json.loads(msg)
                    except ValueError:
                        continue
                    keys = set(req.get("keys") or [])
                    self._clients[ws] = keys
                    snap = {k: self._compact(self.ticks[k]) for k in keys if k in self.ticks and self.ticks[k].get("ltp")}
                    if snap:
                        await ws.send(json.dumps(snap))
            except Exception:
                pass
            finally:
                self._clients.pop(ws, None)

        try:
            self._server = await websockets.serve(handler, "0.0.0.0", self.relay_port, ping_interval=20)
        except OSError:
            self.relay_port = 0

    @staticmethod
    def _compact(t: dict) -> list:
        """[ltp, prev_close, volume, oi, high, low, open, ltt_text, avg, buy_qty, sell_qty, depth, prev_oi]"""
        return [t.get("ltp"), t.get("prev_close"), t.get("vol"), t.get("oi"), t.get("high"), t.get("low"),
                t.get("open"), _ltt(t.get("ltt", 0))[-8:], t.get("atp"), t.get("tbq"), t.get("tsq"),
                t.get("depth"), t.get("prev_oi")]

    async def _pusher(self):
        while not self._stop:
            await asyncio.sleep(PUSH_EVERY)
            if not self._dirty or not self._clients:
                self._dirty.clear() if not self._clients else None
                continue
            dirty, self._dirty = self._dirty, set()
            for ws, keys in list(self._clients.items()):
                upd = {k: self._compact(self.ticks[k]) for k in dirty & keys if self.ticks.get(k, {}).get("ltp")}
                if upd:
                    try:
                        await ws.send(json.dumps(upd))
                    except Exception:
                        self._clients.pop(ws, None)
