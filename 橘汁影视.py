# @tvbox-source
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
橘汁影视 免扫4K - 自托管 py 源
逆向自 EasyTV 新版 jar 的 AppJZ，把 App 内部接口与加密链路完整搬到 py。
接口域名写死在 App 里（主 202.189.6.51:18004 / 备用 103.36.167.27:18004），
旧 COS app.txt(451 封禁) 已不再使用。
加密: RSA 签名 + AES-CBC 加密设备头 + AES-ECB 加密 body + protobuf 封装 + 动态 key。
"""

import re
import json
import time
import base64
import random

import requests

# 加密库（drpy/TVBox py 环境预装 pycryptodome）
try:
    from Crypto.Cipher import AES, PKCS1_v1_5
    from Crypto.PublicKey import RSA
    from Crypto.Util.Padding import pad, unpad
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object


# ---------- App 内置常量 ----------
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
    return "".join(random.choice(CHARS) for _ in range(n - 1)) + "="


# ---------- AES ----------
def _aes_ecb(data, key):
    c = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    return c.encrypt(pad(data.encode("utf-8"), 16))


def aes_ecb_b64(data, key):
    return base64.b64encode(_aes_ecb(data, key)).decode("utf-8")


def aes_ecb_dec_b64(data, key):
    c = AES.new(key.encode("utf-8"), AES.MODE_ECB)
    return unpad(c.decrypt(base64.b64decode(data)), 16).decode("utf-8")


def aes_cbc_hex(data, key):
    kb = key.encode("utf-8")
    c = AES.new(kb, AES.MODE_CBC, iv=kb)
    return c.encrypt(pad(data.encode("utf-8"), 16)).hex()


# ---------- RSA ----------
def rsa_encrypt(data, key_b64):
    pub = RSA.import_key(base64.b64decode(key_b64))
    c = PKCS1_v1_5.new(pub)
    return base64.b64encode(c.encrypt(data.encode("utf-8"))).decode("utf-8")


# ---------- protobuf ----------
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


# ---------- Spider ----------
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
        uuid = "".join(random.choice("0123456789ABCDEF") for _ in range(32)).upper()
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
        # 兜底用第一个 host
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
            # 详情主体直接就是 drama 结构
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
            # 播放地址是 base64 封装的 {vodPlayFrom, playUrl}
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
