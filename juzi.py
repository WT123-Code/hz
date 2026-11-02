# @tvbox-source
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
橘汁影视 免扫4K - 自托管 py 源（无第三方加密库版本）
逆向自 EasyTV 新版 jar 的 AppJZ，把 App 内部接口与加密链路完整搬到 py。
加密(AES/RSA/protobuf/动态key)全部用内嵌纯 Python 实现，零 pycryptodome 依赖，
任何带 requests 的 py 环境(Newbox/TVBox)都能直接跑。
接口域名写死在 App 里（主 202.189.6.51:18004 / 备用 103.36.167.27:18004），
旧 COS app.txt(451 封禁) 已不再使用。
"""

import re
import json
import time
import base64

import requests


def _pseudo(n):
    _pseudo._s = (_pseudo._s * 1103515245 + 12345 + (time.time_ns() & 0xffff)) & 0x7fffffff
    return _pseudo._s % n


_pseudo._s = time.time_ns() & 0x7fffffff

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object


# ============================================================
# 内嵌纯 Python 加密（AES/Rijndael + RSA/PKCS1_v1_5 + DER），零第三方依赖
# ============================================================
_SBOX = [
0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
_ISBOX = [
0x52,0x09,0x6a,0xd5,0x30,0x36,0xa5,0x38,0xbf,0x40,0xa3,0x9e,0x81,0xf3,0xd7,0xfb,
0x7c,0xe3,0x39,0x82,0x9b,0x2f,0xff,0x87,0x34,0x8e,0x43,0x44,0xc4,0xde,0xe9,0xcb,
0x54,0x7b,0x94,0x32,0xa6,0xc2,0x23,0x3d,0xee,0x4c,0x95,0x0b,0x42,0xfa,0xc3,0x4e,
0x08,0x2e,0xa1,0x66,0x28,0xd9,0x24,0xb2,0x76,0x5b,0xa2,0x49,0x6d,0x8b,0xd1,0x25,
0x72,0xf8,0xf6,0x64,0x86,0x68,0x98,0x16,0xd4,0xa4,0x5c,0xcc,0x5d,0x65,0xb6,0x92,
0x6c,0x70,0x48,0x50,0xfd,0xed,0xb9,0xda,0x5e,0x15,0x46,0x57,0xa7,0x8d,0x9d,0x84,
0x90,0xd8,0xab,0x00,0x8c,0xbc,0xd3,0x0a,0xf7,0xe4,0x58,0x05,0xb8,0xb3,0x45,0x06,
0xd0,0x2c,0x1e,0x8f,0xca,0x3f,0x0f,0x02,0xc1,0xaf,0xbd,0x03,0x01,0x13,0x8a,0x6b,
0x3a,0x91,0x11,0x41,0x4f,0x67,0xdc,0xea,0x97,0xf2,0xcf,0xce,0xf0,0xb4,0xe6,0x73,
0x96,0xac,0x74,0x22,0xe7,0xad,0x35,0x85,0xe2,0xf9,0x37,0xe8,0x1c,0x75,0xdf,0x6e,
0x47,0xf1,0x1a,0x71,0x1d,0x29,0xc5,0x89,0x6f,0xb7,0x62,0x0e,0xaa,0x18,0xbe,0x1b,
0xfc,0x56,0x3e,0x4b,0xc6,0xd2,0x79,0x20,0x9a,0xdb,0xc0,0xfe,0x78,0xcd,0x5a,0xf4,
0x1f,0xdd,0xa8,0x33,0x88,0x07,0xc7,0x31,0xb1,0x12,0x10,0x59,0x27,0x80,0xec,0x5f,
0x60,0x51,0x7f,0xa9,0x19,0xb5,0x4a,0x0d,0x2d,0xe5,0x7a,0x9f,0x93,0xc9,0x9c,0xef,
0xa0,0xe0,0x3b,0x4d,0xae,0x2a,0xf5,0xb0,0xc8,0xeb,0xbb,0x3c,0x83,0x53,0x99,0x61,
0x17,0x2b,0x04,0x7e,0xba,0x77,0xd6,0x26,0xe1,0x69,0x14,0x63,0x55,0x21,0x0c,0x7d,
]
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        h = a & 0x80
        a = (a << 1) & 0xff
        if h:
            a ^= 0x1b
        b >>= 1
    return r


def _sword(w):
    return [_SBOX[b] for b in w]


_XKEY_CACHE = {}


def _xkey(key):
    hit = _XKEY_CACHE.get(key)
    if hit is not None:
        return hit
    nk = len(key) // 4
    nr = {4: 10, 6: 12, 8: 14}[nk]
    w = [list(key[i*4:i*4+4]) for i in range(nk)]
    for i in range(nk, 4*(nr+1)):
        t = w[i-1][:]
        if i % nk == 0:
            t = _sword(t[1:]+t[:1])
            t[0] ^= _RCON[i//nk - 1]
        elif nk > 6 and i % nk == 4:
            t = _sword(t)
        w.append([w[i-nk][j] ^ t[j] for j in range(4)])
    rk = []
    for r in range(nr+1):
        flat = b''
        for i in range(4):
            flat += bytes(w[4*r+i])
        rk.append(flat)
    _XKEY_CACHE[key] = rk
    return rk


def _enc_block(block, rk):
    state = bytearray(block)
    def add(r):
        for i in range(16):
            state[i] ^= rk[r][i]
    def sub():
        for i in range(16):
            state[i] = _SBOX[state[i]]
    def shift():
        out = bytearray(16)
        for c in range(4):
            for r in range(4):
                out[4*c+r] = state[4*((c+r) % 4)+r]
        state[:] = out
    def mix():
        out = bytearray(16)
        for c in range(4):
            a = state[4*c:4*c+4]
            out[4*c]   = _gmul(a[0],2) ^ _gmul(a[1],3) ^ a[2] ^ a[3]
            out[4*c+1] = a[0] ^ _gmul(a[1],2) ^ _gmul(a[2],3) ^ a[3]
            out[4*c+2] = a[0] ^ a[1] ^ _gmul(a[2],2) ^ _gmul(a[3],3)
            out[4*c+3] = _gmul(a[0],3) ^ a[1] ^ a[2] ^ _gmul(a[3],2)
        state[:] = out
    add(0)
    for r in range(1, len(rk)-1):
        sub(); shift(); mix(); add(r)
    sub(); shift(); add(len(rk)-1)
    return bytes(state)


def _dec_block(block, rk):
    state = bytearray(block)
    def add(r):
        for i in range(16):
            state[i] ^= rk[r][i]
    def isub():
        for i in range(16):
            state[i] = _ISBOX[state[i]]
    def ishift():
        out = bytearray(16)
        for c in range(4):
            for r in range(4):
                out[4*c+r] = state[4*((c-r) % 4)+r]
        state[:] = out
    def imix():
        out = bytearray(16)
        for c in range(4):
            a = state[4*c:4*c+4]
            out[4*c]   = _gmul(a[0],0x0e) ^ _gmul(a[1],0x0b) ^ _gmul(a[2],0x0d) ^ _gmul(a[3],0x09)
            out[4*c+1] = _gmul(a[0],0x09) ^ _gmul(a[1],0x0e) ^ _gmul(a[2],0x0b) ^ _gmul(a[3],0x0d)
            out[4*c+2] = _gmul(a[0],0x0d) ^ _gmul(a[1],0x09) ^ _gmul(a[2],0x0e) ^ _gmul(a[3],0x0b)
            out[4*c+3] = _gmul(a[0],0x0b) ^ _gmul(a[1],0x0d) ^ _gmul(a[2],0x09) ^ _gmul(a[3],0x0e)
        state[:] = out
    add(len(rk)-1)
    for r in range(len(rk)-2, 0, -1):
        ishift(); isub(); add(r); imix()
    ishift(); isub(); add(0)
    return bytes(state)


def _pad7(data):
    n = 16 - (len(data) % 16)
    return data + bytes([n])*n


def _unpad7(data):
    return data[:-data[-1]]


def _aes_ecb(data, key):
    rk = _xkey(key)
    data = _pad7(data)
    out = b''
    for i in range(0, len(data), 16):
        out += _enc_block(data[i:i+16], rk)
    return out


def _aes_ecb_dec(data, key):
    rk = _xkey(key)
    out = b''
    for i in range(0, len(data), 16):
        out += _dec_block(data[i:i+16], rk)
    return _unpad7(out)


def _aes_cbc(data, key, iv):
    rk = _xkey(key)
    data = _pad7(data)
    prev = iv
    out = b''
    for i in range(0, len(data), 16):
        blk = bytes(a ^ b for a, b in zip(data[i:i+16], prev))
        prev = _enc_block(blk, rk)
        out += prev
    return out


def _der_len(b, i):
    l = b[i]; i += 1
    if l < 0x80:
        return l, i
    n = l & 0x7f
    v = 0
    for _ in range(n):
        v = (v << 8) | b[i]; i += 1
    return v, i


def _der_read(b, i):
    tag = b[i]; i += 1
    ln, i = _der_len(b, i)
    return tag, b[i:i+ln], i+ln


def _rsa_pub(der):
    tag, inner, _ = _der_read(der, 0)
    tag, alg, i1 = _der_read(inner, 0)
    tag, bitstr, _ = _der_read(inner, i1)
    body = bitstr[1:]
    tag, seq, _ = _der_read(body, 0)
    tag, nb, i2 = _der_read(seq, 0)
    tag, eb, _ = _der_read(seq, i2)
    return int.from_bytes(nb, 'big'), int.from_bytes(eb, 'big')


def _rsa_enc(data, pub_b64):
    der = base64.b64decode(pub_b64)
    n, e = _rsa_pub(der)
    k = (n.bit_length() + 7) // 8
    if len(data) > k - 11:
        raise ValueError("message too long")
    ps = b''
    while len(ps) < k - 3 - len(data):
        ps += bytes([_pseudo(255) + 1])
    em = b'\x00\x02' + ps + b'\x00' + data
    return pow(int.from_bytes(em, 'big'), e, n).to_bytes(k, 'big')


# ---- 上层接口（与 pycryptodome 版一致）----
def aes_ecb_b64(data, key):
    return base64.b64encode(_aes_ecb(data.encode("utf-8"), key.encode("utf-8"))).decode("utf-8")


def aes_ecb_dec_b64(data, key):
    return _aes_ecb_dec(base64.b64decode(data), key.encode("utf-8")).decode("utf-8")


def aes_cbc_hex(data, key):
    return _aes_cbc(data.encode("utf-8"), key.encode("utf-8"), key.encode("utf-8")).hex()


def rsa_encrypt(data, key_b64):
    return base64.b64encode(_rsa_enc(data.encode("utf-8"), key_b64)).decode("utf-8")


# ============================================================
# App 内置常量
# ============================================================
HOST = "http://202.189.6.51:18004"
FALLBACK = "http://103.36.167.27:18004"
COMMON_KEY = "ed5fdsgucxumegqa"                     # 16B -> AES-128 (device 加密)
DATA_IV = "OC1A06E197EF10CF3F6058CA7A803B5E"        # 32B -> AES-256 (sig2/sig3)
DATA_KEY = "OW1WBLFZCLJ0WTNJCDMYEGXWYVP3PT0="        # 32B 字符 -> AES-256 (body)
PUBLIC_KEY = ("MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCr8SzZhjYy+rsya1K09t8d2K50pWFoBkgUqMpKOiW"
              "+3IEVKd4eTdvg9RSOjQ82kypL6R9BnsmrS1V8s4PVDwjQbUtYhTPPC9Hz16qY7rpD6m0d2vr09/UpWQ5uOy9P"
              "R0QTrsioveZ+DIe9jc3C+zBCu/kZSY/R8stwJoiitki3gwIDAQAB")
VERSION = "3.0.2.3"
PKG = "com.mxj.wylcjbxyx"
UA = "okhttp/3.12.1"
APPNAME = "橘汁"
CHARS = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

VIDEO_RE = re.compile(r'(?i)\.(?:mp4|m3u8|flv|mkv|avi|ts|mov|mpd|m4a|wmv)(?:\?.*)?$')


def random_str(n):
    return "".join(CHARS[_pseudo(len(CHARS))] for _ in range(n - 1)) + "="


# ============================================================
# protobuf 工具
# ============================================================
def _varint(n):
    out = bytearray()
    while n > 127:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def pb_int(field, val):
    return _varint(field << 3) + _varint(val)


def pb_bytes(field, data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def _read_varint(b, off):
    res = 0
    shift = 0
    while True:
        byte = b[off]
        off += 1
        res |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return res, off
        shift += 7


def pb_parse(b):
    res = {}
    off = 0
    while off < len(b):
        tag, off = _read_varint(b, off)
        fnum = tag >> 3
        wt = tag & 7
        if wt == 0:
            val, off = _read_varint(b, off)
            data = str(val).encode("utf-8")
        elif wt == 1:
            data = b[off:off + 8]
            off += 8
        elif wt == 2:
            ln, off = _read_varint(b, off)
            data = b[off:off + ln]
            off += ln
        elif wt == 5:
            data = b[off:off + 4]
            off += 4
        else:
            break
        res.setdefault(fnum, []).append(data)
    return res


def first(m, f):
    return m.get(f, [b""])[0] if m.get(f) else b""


def all_(m, f):
    return m.get(f, [])


# ============================================================
# Spider
# ============================================================
class Spider(BaseSpider):
    def __init__(self):
        super().__init__()
        self.host = ""
        self.publicKey = PUBLIC_KEY
        self.dataKey = DATA_KEY
        self.dataIv = DATA_IV
        self.pkg = PKG
        self.appName = APPNAME
        self.version = VERSION
        self.dynamicKey = ""
        self._inited = False

    # ---- 设备信息 ----
    def _device(self):
        uuid = "".join("0123456789ABCDEF"[_pseudo(16)] for _ in range(32)).upper()
        return {
            "country": "CN", "vName": self.version, "cpuId": "MT6893Z%2FCZA",
            "young": 0, "facturer": "Xiaomi", "pkg": self.pkg, "uuid": uuid,
            "resolution": "1080x2272", "mac": "02%3A00%3A00%3A00%3A00%3A00",
            "abid": "397", "model": "M2012K11AC", "plat": "android", "udid": uuid,
            "dpi": "440", "net": "1", "lang": "zh", "brand": "Xiaomi",
            "density": "2.75", "appName": self.appName, "cpu": "arm64-v8a",
            "chid": "10000", "carrier": "%E8%81%94%E9%80%9A", "_vOsCode": 30,
            "vOs": "11", "v": 1, "tenantId": "",
            "vApp": self.version.replace(".", ""), "device": 0,
            "androidID": uuid[:16].lower(),
        }

    def _public_headers(self, proto):
        key = self.dynamicKey or self.publicKey
        dev = self._device()
        ts = int(time.time() * 1000)
        rs = random_str(16)
        vapp = dev["vApp"]
        dev["sig"] = rsa_encrypt(str(ts) + rs + vapp, key)
        dev["random_str"] = rs
        dev["timestamp"] = ts
        aes = aes_ecb_b64(str(ts) + rs, self.dataIv)
        dev["sig2"] = aes[:8]
        dev["sig3"] = aes[8:]
        params = aes_cbc_hex(json.dumps(dev, separators=(",", ":")), COMMON_KEY)
        headers = {
            "User-Agent": UA,
            "Accept": "application/x-protobuf" if proto else "application/json",
            "Content-Type": "application/x-protobuf" if proto else "application/json; charset=utf-8",
            "publicParams": json.dumps({"paramsData": params}),
        }
        return headers

    # ---- body 加密 ----
    def _secure_body(self, params):
        ts = int(time.time() * 1000)
        parts = "&".join(f"{k}={v}" for k, v in params.items() if v)
        body = aes_ecb_b64(parts + str(ts), self.dataKey)
        s = random_str(8) + body
        return (pb_bytes(1, s[:20]) + pb_bytes(2, s[20:]) + pb_bytes(3, random_str(20))
                + pb_int(4, ts) + pb_bytes(5, s[:8]))

    # ---- 请求 ----
    def _post(self, path, body):
        url = self.host + path
        r = requests.post(url, headers=self._public_headers(True), data=body, timeout=18)
        return r.content

    def _get_json(self, path):
        url = self.host + path
        r = requests.get(url, headers=self._public_headers(False), timeout=18)
        return r.json()

    # ---- 初始化：选可用 host + 拿动态 key ----
    def _init(self):
        if self._inited:
            return
        candidates = [HOST, FALLBACK]
        for h in candidates:
            self.host = h
            try:
                self._load_dynamic_key()
                if self.dynamicKey:
                    self._inited = True
                    return
            except Exception:
                self.dynamicKey = ""
        self.host = candidates[0]
        self._inited = True

    def _load_dynamic_key(self):
        ts = int(time.time() * 1000)
        rs = random_str(16)
        body = (pb_int(1, ts)
                + pb_bytes(2, rsa_encrypt(str(ts) + rs, self.publicKey))
                + pb_bytes(3, random_str(16))
                + pb_bytes(4, rs)
                + pb_bytes(5, random_str(16)))
        resp = self._post("/api/v5/find/app/zone", body)
        data = pb_parse(first(pb_parse(resp), 3))
        self.dynamicKey = "".join(bts(first(data, i)) for i in (2, 3, 4, 5))

    # ---- 首页 ----
    def homeContent(self, filter=False):
        self._init()
        classes = []
        try:
            d = self._get_json("/api/v3/drama/getCategory?orderBy=type_id").get("data") or []
            for it in d:
                name = it.get("name", "")
                if name == "公告":
                    continue
                tid = str(it.get("id", ""))
                if tid:
                    classes.append({"type_id": tid, "type_name": name})
        except Exception:
            classes = [{"type_id": "1", "type_name": "电影"}, {"type_id": "2", "type_name": "电视剧"},
                       {"type_id": "3", "type_name": "综艺"}, {"type_id": "4", "type_name": "动漫"}]
        return json.dumps({"class": classes}, ensure_ascii=False)

    def homeVideoContent(self):
        self._init()
        try:
            d = self._get_json("/api/ex/v3/security/tag/list").get("data")
            items = None
            if isinstance(d, list):
                items = d
            elif isinstance(d, dict):
                items = d.get("list") or [d]
            elif isinstance(d, str) and d:
                for key in (self.dataKey, self.dataIv):
                    try:
                        items = json.loads(aes_ecb_dec_b64(d, key))
                        if isinstance(items, dict):
                            items = items.get("list")
                        break
                    except Exception:
                        continue
            if not items:
                return '{"list":[]}'
            lst = []
            for sec in items:
                if not isinstance(sec, dict):
                    continue
                vods = sec.get("vodList") or [sec]
                for v in vods:
                    if isinstance(v, dict):
                        lst.append(self._append_vod(v))
            if lst:
                return json.dumps({"list": lst}, ensure_ascii=False)
        except Exception:
            pass
        return '{"list":[]}'

    def _append_vod(self, v):
        cover = v.get("coverImage") or v.get("cover") or {}
        pic = cover.get("path") or cover.get("thumb") or cover.get("url") or ""
        vid = v.get("id") or v.get("vod_id")
        name = v.get("name") or v.get("vod_name") or ""
        remark = v.get("remark") or v.get("vod_remarks") or ""
        return {"vod_id": str(vid), "vod_name": str(name), "vod_pic": str(pic),
                "vod_remarks": str(remark)}

    # ---- 分类 ----
    def categoryContent(self, tid, pg, filter, extend):
        self._init()
        tid = str(tid or "")
        pg = str(pg or "1")
        ex = extend or {}
        params = {"pagesize": "21", "typeId1": tid, "page": pg,
                  "vodOrderBy": ex.get("extend_sort") or "最新",
                  "vodArea": ex.get("area", ""), "vodLang": ex.get("lang", ""),
                  "vodClass": ex.get("class", ""), "vodYear": ex.get("year", "")}
        try:
            resp = self._post("/api/proto/v5/drama/list", self._secure_body(params))
            lst = self._parse_drama_page(resp)
            p = int(pg or 1)
            pc = (1 if len(lst) >= 21 else 0) + p
            return json.dumps({"list": lst, "page": p, "pagecount": pc,
                               "limit": 21, "total": 999999}, ensure_ascii=False)
        except Exception:
            return json.dumps({"list": [], "page": int(pg or 1), "pagecount": 1,
                               "limit": 21, "total": 0}, ensure_ascii=False)

    # ---- 详情 ----
    def detailContent(self, ids):
        self._init()
        if not ids or not ids[0]:
            return '{"list":[]}'
        vid = ids[0].strip()
        try:
            resp = self._post("/api/proto/v5/drama/getDetail", self._secure_body({"id": vid}))
            d = pb_parse(first(pb_parse(resp), 3))
            cover = pb_parse(first(d, 2))
            pic = cover.get("path", [b""])[0].decode() or cover.get("thumb", [b""])[0].decode()
            groups = {}
            for item in all_(d, 29):
                sub = pb_parse(item)
                ep = bts(first(sub, 2))
                play_url = bts(first(sub, 4))
                play_from = bts(first(sub, 9))
                src = bts(first(sub, 10)) or "橘汁"
                if not VIDEO_RE.search(play_url):
                    play_url = base64.b64encode(json.dumps({"vodPlayFrom": play_from, "playUrl": play_url}).encode()).decode()
                groups.setdefault(src, []).append((ep or "播放") + "$" + play_url)
            vod = {"vod_id": vid,
                   "vod_name": bts(first(d, 9)),
                   "vod_pic": pic,
                   "vod_actor": bts(first(d, 25)),
                   "vod_director": bts(first(d, 12)),
                   "vod_area": bts(first(d, 1)),
                   "vod_year": bts(first(d, 18)),
                   "vod_remarks": bts(first(d, 26)),
                   "vod_content": bts(first(d, 6)),
                   "vod_play_from": "$$$".join(groups.keys()),
                   "vod_play_url": "$$$".join("#".join(v for v in vs) for vs in groups.values())}
            return json.dumps({"list": [vod]}, ensure_ascii=False)
        except Exception:
            return '{"list":[]}'

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg="1"):
        self._init()
        pg = str(pg or "1")
        try:
            resp = self._post("/api/proto/v5/drama/search",
                              self._secure_body({"searchKeys": key, "page": pg, "pagesize": "21"}))
            lst = self._parse_drama_page(resp)
            return json.dumps({"list": lst}, ensure_ascii=False)
        except Exception:
            return '{"list":[]}'

    # ---- 播放 ----
    def playerContent(self, ids, flag, url):
        self._init()
        url = (url or "").strip()
        if not url:
            return '{"parse":0,"url":""}'
        if VIDEO_RE.search(url):
            return json.dumps({"parse": 0, "url": url, "header": {}, "playUrl": ""})
        try:
            info = json.loads(base64.b64decode(url))
            resp = self._post("/api/proto/v5/videoUsableUrl", self._secure_body(info))
            d = pb_parse(first(pb_parse(resp), 3))
            header = {}
            for item in all_(d, 6):
                sub = pb_parse(item)
                k = bts(first(sub, 1))
                v = bts(first(sub, 2))
                if k:
                    header[k] = v
            real = bts(first(d, 1))
            return json.dumps({"parse": 0, "url": real, "header": header, "playUrl": ""})
        except Exception:
            return json.dumps({"parse": 1, "url": url, "header": {}})

    # ---- protobuf 列表解析 ----
    def _parse_drama_page(self, resp):
        outer = pb_parse(resp)
        inner = pb_parse(first(outer, 3))
        out = []
        for item in all_(inner, 1):
            out.append(self._parse_drama(item))
        return out

    def _parse_drama(self, item):
        d = pb_parse(item)
        cover = pb_parse(first(d, 2))
        pic = cover.get("thumb", [b""])[0].decode() or cover.get("path", [b""])[0].decode()
        return {"vod_id": bts(first(d, 3)) or "0",
                "vod_name": bts(first(d, 5)),
                "vod_pic": pic,
                "vod_remarks": bts(first(d, 13)),
                "vod_year": bts(first(d, 14)),
                "vod_area": bts(first(d, 1))}


def bts(b):
    return b.decode("utf-8", "replace") if b else ""
