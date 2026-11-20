# -*- coding: utf-8 -*-
"""
米诺┃秒播 (MiNO) TVBox / Newbox Python Spider
================================================
纯标准库实现：无 requests / 无 cryptography / 无 pycryptodome
  - secp256r1 纯 Python ECDH（生成设备密钥对、导出 65 字节公钥、做共享密钥）
  - 签名：HMAC-SHA256，串 = METHOD\\npath\\n排序query\\nbody哈希\\nts\\nnonce\\ndevice\\nsid\\n1.0.23
  - 密钥派生：s1 = HMAC(sid, ECDH_secret)；m = HMAC(s1, "bwv/apisec/ecdh-signkey/v1\\x01")；
              n = HMAC(s1, "bwv/apisec/ecdh-bodykey/v1\\x01")
  - 响应 enc=1 用 AES-256-GCM(n) 解密，内置纯 Python AES 实现
接口：
  POST /api/v1/security/init
  GET  /api/v1/category/videos   type_id,page,page_size
  GET  /api/v1/search            wd,page
  GET  /api/v1/category/filters  type_id
  GET  /api/v1/video/detail      id
  POST /api/v1/vod/ticket        {"token":"tk:xxxx"}   ← token 必须保留 tk: 前缀
  GET  /api/v1/vod/parse         code,tk,t,url
"""
import json
import time
import base64
import hashlib
import hmac
import random
import os
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        def init(self, extend=""):
            pass

        def getName(self):
            return ""

        def isVideoFormat(self, url):
            return False

        def manualVideoCheck(self):
            return False

        def destroy(self):
            pass

        def localProxy(self, param):
            return None


# ============================================================ 纯 Python AES-256-GCM
_SBOX = [
    0x63,0x7C,0x77,0x7B,0xF2,0x6B,0x6F,0xC5,0x30,0x01,0x67,0x2B,0xFE,0xD7,0xAB,0x76,
    0xCA,0x82,0xC9,0x7D,0xFA,0x59,0x47,0xF0,0xAD,0xD4,0xA2,0xAF,0x9C,0xA4,0x72,0xC0,
    0xB7,0xFD,0x93,0x26,0x36,0x3F,0xF7,0xCC,0x34,0xA5,0xE5,0xF1,0x71,0xD8,0x31,0x15,
    0x04,0xC7,0x23,0xC3,0x18,0x96,0x05,0x9A,0x07,0x12,0x80,0xE2,0xEB,0x27,0xB2,0x75,
    0x09,0x83,0x2C,0x1A,0x1B,0x6E,0x5A,0xA0,0x52,0x3B,0xD6,0xB3,0x29,0xE3,0x2F,0x84,
    0x53,0xD1,0x00,0xED,0x20,0xFC,0xB1,0x5B,0x6A,0xCB,0xBE,0x39,0x4A,0x4C,0x58,0xCF,
    0xD0,0xEF,0xAA,0xFB,0x43,0x4D,0x33,0x85,0x45,0xF9,0x02,0x7F,0x50,0x3C,0x9F,0xA8,
    0x51,0xA3,0x40,0x8F,0x92,0x9D,0x38,0xF5,0xBC,0xB6,0xDA,0x21,0x10,0xFF,0xF3,0xD2,
    0xCD,0x0C,0x13,0xEC,0x5F,0x97,0x44,0x17,0xC4,0xA7,0x7E,0x3D,0x64,0x5D,0x19,0x73,
    0x60,0x81,0x4F,0xDC,0x22,0x2A,0x90,0x88,0x46,0xEE,0xB8,0x14,0xDE,0x5E,0x0B,0xDB,
    0xE0,0x32,0x3A,0x0A,0x49,0x06,0x24,0x5C,0xC2,0xD3,0xAC,0x62,0x91,0x95,0xE4,0x79,
    0xE7,0xC8,0x37,0x6D,0x8D,0xD5,0x4E,0xA9,0x6C,0x56,0xF4,0xEA,0x65,0x7A,0xAE,0x08,
    0xBA,0x78,0x25,0x2E,0x1C,0xA6,0xB4,0xC6,0xE8,0xDD,0x74,0x1F,0x4B,0xBD,0x8B,0x8A,
    0x70,0x3E,0xB5,0x66,0x48,0x03,0xF6,0x0E,0x61,0x35,0x57,0xB9,0x86,0xC1,0x1D,0x9E,
    0xE1,0xF8,0x98,0x11,0x69,0xD9,0x8E,0x94,0x9B,0x1E,0x87,0xE9,0xCE,0x55,0x28,0xDF,
    0x8C,0xA1,0x89,0x0D,0xBF,0xE6,0x42,0x68,0x41,0x99,0x2D,0x0F,0xB0,0x54,0xBB,0x16]
_RCON = [0x00,0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36]


def _xt(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1) & 0xFF


def _mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xt(a)
        b >>= 1
    return r


class _AES(object):
    def __init__(self, key):
        self.nk = len(key) // 4
        self.nr = self.nk + 6
        w = [list(key[4 * i:4 * i + 4]) for i in range(self.nk)]
        for i in range(self.nk, 4 * (self.nr + 1)):
            t = list(w[i - 1])
            if i % self.nk == 0:
                t = t[1:] + t[:1]
                t = [_SBOX[b] for b in t]
                t[0] ^= _RCON[i // self.nk]
            elif self.nk > 6 and i % self.nk == 4:
                t = [_SBOX[b] for b in t]
            w.append([w[i - self.nk][j] ^ t[j] for j in range(4)])
        self.rk = w

    def enc(self, blk):
        s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]
        self._ark(s, 0)
        for rnd in range(1, self.nr):
            self._sub(s); self._shift(s); self._mix(s); self._ark(s, rnd)
        self._sub(s); self._shift(s); self._ark(s, self.nr)
        return bytes(s[r][c] for c in range(4) for r in range(4))

    def _ark(self, s, rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= self.rk[4 * rnd + c][r]

    def _sub(self, s):
        for r in range(4):
            for c in range(4):
                s[r][c] = _SBOX[s[r][c]]

    def _shift(self, s):
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]

    def _mix(self, s):
        for c in range(4):
            a = [s[r][c] for r in range(4)]
            s[0][c] = _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3]
            s[1][c] = a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3]
            s[2][c] = a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3)
            s[3][c] = _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)


def _gcm_dec(key, blob):
    iv = blob[:12]
    body = blob[12:]
    if len(body) < 16:
        return b""
    ct = body[:-16]
    aes = _AES(key)
    out = bytearray()
    ctr = 2
    for i in range(0, len(ct), 16):
        ks = aes.enc(iv + (ctr & 0xFFFFFFFF).to_bytes(4, "big"))
        chunk = ct[i:i + 16]
        out += bytes(a ^ b for a, b in zip(chunk, ks))
        ctr += 1
    return bytes(out)


# ============================================================ 纯 Python secp256r1 ECDH
_EC_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_EC_A = _EC_P - 3
_EC_G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
         0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)
_EC_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _EC_P == 0:
        return None
    if x1 == x2 and y1 == y2:
        lam = (3 * x1 * x1 + _EC_A) * pow(2 * y1, _EC_P - 2, _EC_P) % _EC_P
    else:
        lam = (y2 - y1) * pow(x2 - x1, _EC_P - 2, _EC_P) % _EC_P
    x3 = (lam * lam - x1 - x2) % _EC_P
    return (x3, (lam * (x1 - x3) - y1) % _EC_P)


def _ec_mul(k, pt):
    r = None
    q = pt
    while k:
        if k & 1:
            r = _ec_add(r, q)
        q = _ec_add(q, q)
        k >>= 1
    return r


def _ec_gen():
    d = random.randrange(1, _EC_N)
    q = _ec_mul(d, _EC_G)
    pub = b"\x04" + q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")
    return d, pub


def _ec_shared(d, pub65):
    x = int.from_bytes(pub65[1:33], "big")
    y = int.from_bytes(pub65[33:65], "big")
    s = _ec_mul(d, (x, y))
    return s[0].to_bytes(32, "big")


# ============================================================ Spider
class Spider(BaseSpider):
    def __init__(self):
        self.base = "http://43.248.128.122:578"
        self.ua = "okhttp/4.12.0"
        self.ver = "1.0.23"
        self.dev = ""
        self.sid = ""
        self.m = None
        self.n = None
        self.t0 = 0
        self.l0 = 0
        self.exp = 0
        self.types_cache = None

    def getName(self):
        return "米诺"

    def init(self, extend=""):
        if extend:
            try:
                cfg = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(cfg, dict) and cfg.get("base"):
                    self.base = str(cfg["base"]).rstrip("/")
            except Exception:
                pass
        return None

    def isVideoFormat(self, url):
        u = (url or "").lower()
        return ".m3u8" in u or ".mp4" in u or "m3u8" in u

    def destroy(self):
        pass

    # ---------------------------------------------------------- 会话
    def _newsession(self):
        d, pub = _ec_gen()
        self.dev = "".join(random.choice("0123456789abcdef") for _ in range(16))
        payload = json.dumps({
            "platform": "android", "version": self.ver, "device_id": self.dev,
            "client_pub": base64.b64encode(pub).decode(),
            "device_brand": "vivo", "device_manufacturer": "vivo", "device_model": "V2364A",
        }, separators=(",", ":"))
        req = urllib.request.Request(
            self.base + "/api/v1/security/init", data=payload.encode(),
            headers={"User-Agent": self.ua, "Content-Type": "application/json; charset=utf-8",
                     "X-App-Version": self.ver, "X-Device-Id": self.dev}, method="POST")
        raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        obj = json.loads(raw)
        data = obj.get("data") or {}
        self.sid = data.get("session_id") or ""
        self.t0 = int(data.get("server_time") or time.time())
        self.l0 = time.time()
        self.exp = int(data.get("expires_in") or 600)
        spub = data.get("server_pub") or ""
        if spub and len(base64.b64decode(spub)) == 65:
            sec = _ec_shared(d, base64.b64decode(spub))
            s1 = hmac.new(self.sid.encode(), sec, hashlib.sha256).digest()
            self.m = hmac.new(s1, b"bwv/apisec/ecdh-signkey/v1\x01", hashlib.sha256).digest()
            self.n = hmac.new(s1, b"bwv/apisec/ecdh-bodykey/v1\x01", hashlib.sha256).digest()
        else:
            sk = (data.get("sign_key") or "").encode()
            self.m = sk
            self.n = sk
        return bool(self.sid and self.m)

    def _ensure(self):
        if not self.sid or not self.m or (time.time() - self.l0) > (self.exp - 60):
            for _ in range(3):
                try:
                    if self._newsession():
                        return True
                except Exception:
                    time.sleep(0.3)
            return False
        return True

    # ---------------------------------------------------------- 请求
    def _request(self, path, params=None, body=None):
        if not self._ensure():
            return {"code": 0, "msg": "会话建立失败"}
        method = "GET" if body is None else "POST"
        params = params or {}
        qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
        canon = "&".join("%s=%s" % (k, v) for k, v in sorted(params.items()))
        bs = "" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        bh = hashlib.sha256(bs.encode()).hexdigest()
        ts = str(int(self.t0 + (time.time() - self.l0)))
        no = "".join(random.choice("0123456789abcdef") for _ in range(32))
        sigstr = "\n".join([method, path, canon, bh, ts, no, self.dev, self.sid, self.ver])
        sign = hmac.new(self.m, sigstr.encode(), hashlib.sha256).hexdigest()
        headers = {
            "User-Agent": self.ua, "X-Session-Id": self.sid, "X-Timestamp": ts,
            "X-Nonce": no, "X-Sign": sign, "X-Body-Sha256": bh,
            "X-App-Version": self.ver, "X-Device-Id": self.dev,
            "Content-Type": "application/json; charset=utf-8", "Accept-Encoding": "identity",
        }
        url = self.base + path + ("?" + qs if qs else "")
        data = bs.encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        txt = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        obj = json.loads(txt)
        dd = obj.get("data")
        if isinstance(dd, dict) and dd.get("enc") == 1:
            try:
                obj["data"] = json.loads(_gcm_dec(self.n, base64.b64decode(dd["payload"])).decode("utf-8"))
            except Exception:
                obj["data"] = {}
        return obj

    # ---------------------------------------------------------- 首页
    def _types(self):
        if self.types_cache:
            return self.types_cache
        out = []
        try:
            r = self._request("/api/v1/category/filters", {"type_id": "1"})
            cats = ((r.get("data") or {}).get("categories") or [])
            for c in cats:
                out.append({"type_id": str(c.get("type_id")), "type_name": c.get("type_name")})
        except Exception:
            out = []
        if not out:
            out = [{"type_id": "1", "type_name": "电影"}, {"type_id": "2", "type_name": "连续剧"},
                   {"type_id": "3", "type_name": "综艺"}, {"type_id": "4", "type_name": "动漫"},
                   {"type_id": "20", "type_name": "短剧"}, {"type_id": "21", "type_name": "少儿"},
                   {"type_id": "22", "type_name": "漫剧"}, {"type_id": "23", "type_name": "纪录片"}]
        self.types_cache = out
        return out

    def homeContent(self, filter):
        return {"class": self._types(), "filters": {}}

    def homeVideoContent(self):
        try:
            return self.categoryContent("2", 1, False, {})
        except Exception:
            return {"list": []}

    # ---------------------------------------------------------- 列表
    @staticmethod
    def _vitem(it):
        return {
            "vod_id": str(it.get("vod_id")),
            "vod_name": it.get("vod_name") or "",
            "vod_pic": it.get("vod_pic") or "",
            "vod_remarks": it.get("vod_remarks") or "",
            "vod_year": str(it.get("vod_year") or ""),
            "vod_area": it.get("vod_area") or "",
        }

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        try:
            r = self._request("/api/v1/category/videos",
                              {"page": str(page), "page_size": "20", "type_id": str(tid)})
            data = r.get("data") or {}
            vids = data.get("videos") or []
            pginfo = data.get("pagination") or {}
            total = int(pginfo.get("total") or 0)
            pages = int(pginfo.get("total_pages") or 0)
            return {"list": [self._vitem(v) for v in vids], "page": page,
                    "pagecount": pages if pages else (total // 20 + 1),
                    "limit": 20, "total": total}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    # ---------------------------------------------------------- 详情
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else str(ids)
        if isinstance(vid, str) and "|" in vid:
            vid = vid.split("|")[0]
        try:
            r = self._request("/api/v1/video/detail", {"id": str(vid)})
            data = r.get("data") or {}
            info = data.get("vod_info") or {}
            players = info.get("vod_url_with_player") or []
            froms, urls = [], []
            for p in players:
                name = p.get("name") or p.get("code") or "线路"
                eps = (p.get("url") or "").split("#")
                parts = []
                for e in eps:
                    if not e.strip():
                        continue
                    if "$" in e:
                        epname, epurl = e.split("$", 1)
                    else:
                        epname, epurl = "正片", e
                    parts.append("%s$%s" % (epname, epurl))
                if parts:
                    froms.append(name)
                    urls.append("#".join(parts))
            if not froms:
                return {"list": []}
            vod = {
                "vod_id": str(vid),
                "vod_name": info.get("vod_name") or "",
                "vod_pic": info.get("vod_pic") or "",
                "vod_year": str(info.get("vod_year") or ""),
                "vod_area": info.get("vod_area") or "",
                "vod_lang": info.get("vod_lang") or "",
                "vod_actor": info.get("vod_actor") or "",
                "vod_director": info.get("vod_director") or "",
                "vod_remarks": info.get("vod_remarks") or "",
                "vod_content": (info.get("vod_blurb") or info.get("vod_content") or "").strip(),
                "vod_play_from": "$$$".join(froms),
                "vod_play_url": "$$$".join(urls),
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    # ---------------------------------------------------------- 搜索
    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        q = urllib.parse.quote(str(key))
        try:
            r = self._request("/api/v1/search", {"page": str(page), "wd": q})
            data = r.get("data") or {}
            hits = data.get("hits") or data.get("videos") or []
            return {"list": [self._vitem(v) for v in hits], "page": page}
        except Exception:
            return {"list": []}

    # ---------------------------------------------------------- 播放
    def _ticket(self, tk):
        try:
            r = self._request("/api/v1/vod/ticket", None, {"token": tk})
            if r.get("code") == 1:
                return ((r.get("data") or {}).get("ticket")) or ""
        except Exception:
            pass
        return ""

    def _resolve(self, tk):
        ticket = self._ticket(tk)
        if not ticket:
            return ""
        try:
            seg = ticket.split(".")[0]
            seg += "=" * (-len(seg) % 4)
            payload = json.loads(base64.urlsafe_b64decode(seg).decode("utf-8", "replace"))
        except Exception:
            return ""
        d = payload.get("data") or {}
        api = str(d.get("parse_api") or "").replace("\\u0026", "&")
        du = str(d.get("url") or "")
        if not api or not du:
            return ""
        if api.startswith("/"):
            u = urllib.parse.urlsplit(api)
            params = dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))
            params["url"] = du
            try:
                r = self._request(u.path, params)
                if isinstance(r, dict):
                    if r.get("url"):
                        return str(r["url"])
                    if r.get("data") and isinstance(r["data"], dict) and r["data"].get("url"):
                        return str(r["data"]["url"])
            except Exception:
                pass
            return ""
        if "{md5}" in api:
            target = api.replace("{md5}", du)
        elif "url=" in api:
            target = api + urllib.parse.quote(du, safe="")
        else:
            target = api + du
        try:
            txt = urllib.request.urlopen(urllib.request.Request(
                target, headers={"User-Agent": self.ua}), timeout=25).read().decode("utf-8", "replace")
            j = json.loads(txt)
            return str(j.get("url") or "")
        except Exception:
            return ""

    def playerContent(self, flag, id, vipFlags=None):
        tk = str(id or "")
        if "|" in tk:
            tk = tk.split("|")[-1]
        url = ""
        try:
            url = self._resolve(tk)
        except Exception:
            url = ""
        if not url:
            return {"parse": 0, "url": "", "header": {}, "msg": "解析失败"}
        return {"parse": 0, "url": url, "header": {"User-Agent": self.ua}}
