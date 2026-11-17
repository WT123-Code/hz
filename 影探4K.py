# coding: utf-8
# 影探4K（cms.lyyytv.cn）· TVBox / FongMi Python 站源
# 站型：苹果CMS 的 app 接口（/api.php/app/*）。
#
# ===== 2026-11-17 播放修复 =====
# 关键进展：影探内置的新解析口 http://4kzj.lyyytv.cn/api/index?parsesId=2&appid=10001
#   实测能解出 4K(YD)/4K(123)/4K(BD) 三条 4K 线路的真实播放地址（baidu.con 加密串 → AES 解密），
#   解出的直链真实可访问（200，video/mp4、video/x-matroska）。
#   - CHAIN_API / PARSE_API 已全部指向该新接口；
#   - 详情页恢复展示 lyyytv.cn 的 4K 线路（不再隐藏）；
#   - 官方平台链接(qq/iqiyi/youku/bilibili)仍走小白解析兜底。
import base64
import json
import re
import time
import urllib.parse
import urllib.request

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider(object):
        pass

HOST = "http://cms.lyyytv.cn"
UA = "okhttp/4.12.0"
CHAIN_API = "http://4kzj.lyyytv.cn/api/index?parsesId=2&appid=10001&videoUrl="
PARSE_API = "http://4kzj.lyyytv.cn/api/index?parsesId=2&appid=10001&videoUrl="
CMS_KEY = "wP5bvxoc3yv7FoBQENFZuAF0EUYr4LTy"
DEC_PREFIX = "https://baidu.con/"
YT4K_HOST = re.compile(r"(?:^|\.)(?:ym4kjx|hd4kjx|sd4kjx|mm4kjx|mv4kjx|vk4kjx|lz4kjx)\.lyyytv\.cn$", re.I)
MEDIA_RE = re.compile(r"\.(?:mp4|m3u8|m3u|flv|mkv|ts|mov|webm|m4v|mpd)(?:[?#]|$)", re.I)
FILTER_KEYS = [("class", "类型"), ("area", "地区"), ("lang", "语言"), ("year", "年份"),
               ("letter", "字母"), ("by", "排序"), ("sort", "顺序"), ("star", "主演"),
               ("director", "导演"), ("state", "状态"), ("version", "版本")]

# ---- 小白解析器（配置里现成的 token，2026-11-17 实测四大平台均可解析）----
XB_API = "https://api.52xiaobai.cn/api/parse.php"
XB_TOKEN = "7159cfce627af3a2189a1e1b3cb81995"
XB_UA = "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
# 官方平台域名，命中才送小白解析
OFFICIAL_HOST = re.compile(
    r"(?:^|\.)(?:qq\.com|bilibili\.com|iqiyi\.com|youku\.com|v\.youku\.com|mgtv\.com|sohu\.com|letv\.com|kugou\.com)(?:$|\.)",
    re.I)


def _xb_parse(page_url):
    """调用小白解析器，返回 (playUrl, header_json) 或 ("", "")。"""
    if not page_url or not page_url.startswith("http"):
        return "", ""
    try:
        q = urllib.parse.urlencode({"token": XB_TOKEN, "url": page_url})
        req = urllib.request.Request(XB_API + "?" + q, headers={"User-Agent": XB_UA})
        r = urllib.request.urlopen(req, timeout=25)
        txt = r.read().decode("utf-8", "ignore")
        j = json.loads(txt)
    except Exception:
        return "", ""
    if not isinstance(j, dict) or int(j.get("code") or 0) != 200:
        return "", ""
    real = str(j.get("url") or "").strip()
    if not real.startswith("http"):
        return "", ""
    # 组装播放器需要的请求头：UA 优先用解析结果给的，其次用内置 UA
    hdr = {}
    ua = str(j.get("User-Agent") or "").strip()
    hdr["User-Agent"] = ua if ua else XB_UA
    referer = str(j.get("Referer") or "").strip()
    if referer:
        hdr["Referer"] = referer
    return real, json.dumps(hdr, ensure_ascii=False)

# ---------------------------------------------------------------- AES（解密用）
def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _build_sbox():
    inv = [0] * 256
    for i in range(1, 256):
        r, base, e = 1, i, 254
        while e:
            if e & 1:
                r = _gmul(r, base)
            base = _gmul(base, base)
            e >>= 1
        inv[i] = r

    def rotl(x, n):
        return ((x << n) | (x >> (8 - n))) & 0xFF

    return [inv[i] ^ rotl(inv[i], 1) ^ rotl(inv[i], 2) ^ rotl(inv[i], 3) ^ rotl(inv[i], 4) ^ 0x63
            for i in range(256)]


SBOX = _build_sbox()
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]


class _AES(object):
    def __init__(self, key):
        if len(key) not in (16, 24, 32):
            raise ValueError("bad key")
        self.nk = len(key) // 4
        self.nr = self.nk + 6
        self.rk = self._expand(key)

    def _expand(self, key):
        w = [list(key[i:i + 4]) for i in range(0, len(key), 4)]
        for i in range(self.nk, 4 * (self.nr + 1)):
            t = list(w[i - 1])
            if i % self.nk == 0:
                t = t[1:] + t[:1]
                t = [SBOX[b] for b in t]
                t[0] ^= RCON[i // self.nk - 1]
            elif self.nk > 6 and i % self.nk == 4:
                t = [SBOX[b] for b in t]
            w.append([w[i - self.nk][j] ^ t[j] for j in range(4)])
        return w

    def _add(self, s, rnd):
        for c in range(4):
            for r in range(4):
                s[r][c] ^= self.rk[rnd * 4 + c][r]

    def enc(self, block):
        s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add(s, 0)
        for rnd in range(1, self.nr + 1):
            for r in range(4):
                for c in range(4):
                    s[r][c] = SBOX[s[r][c]]
            for r in range(1, 4):
                s[r] = s[r][r:] + s[r][:r]
            if rnd != self.nr:
                for c in range(4):
                    a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
                    s[0][c] = _gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3
                    s[1][c] = a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3
                    s[2][c] = a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3)
                    s[3][c] = _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2)
            self._add(s, rnd)
        return bytes(s[r][c] for c in range(4) for r in range(4))

    def dec(self, block):
        s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add(s, self.nr)
        for rnd in range(self.nr - 1, -1, -1):
            for r in range(1, 4):
                s[r] = s[r][-r:] + s[r][:-r]
            for r in range(4):
                for c in range(4):
                    s[r][c] = INV_SBOX[s[r][c]]
            self._add(s, rnd)
            if rnd != 0:
                for c in range(4):
                    a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
                    s[0][c] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
                    s[1][c] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
                    s[2][c] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
                    s[3][c] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)
        return bytes(s[r][c] for c in range(4) for r in range(4))


def _aes_cbc_enc(data, key, iv):
    aes = _AES(key)
    n = 16 - len(data) % 16
    data = data + bytes([n]) * n
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        blk = bytes(data[i + j] ^ prev[j] for j in range(16))
        enc = aes.enc(blk)
        out += enc
        prev = enc
    return bytes(out)


def _aes_cbc_dec(data, key, iv):
    aes = _AES(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        dec = aes.dec(blk)
        out += bytes(dec[j] ^ prev[j] for j in range(16))
        prev = blk
    n = out[-1]
    return bytes(out[:-n])

# ---------------------------------------------------------------- 工具


def _clean(s):
    s = str(s or "")
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;nbsp;", " ").replace("&nbsp;", " ").replace("&amp;", "&")
    return " ".join(s.split()).strip()


def _safe(s):
    return _clean(s).replace("$", " ").replace("#", " ").strip()


def _fix(u):
    u = str(u or "").strip()
    if u.startswith("//"):
        u = "http:" + u
    return u


def _decrypt_baidu(url):
    """https://baidu.con/<16 chars key><base64(ct)> → AES-CBC(key,key) 明文"""
    if not url or not url.startswith(DEC_PREFIX):
        return ""
    body = url[len(DEC_PREFIX):]
    if len(body) <= 16:
        return ""
    key = body[:16].encode()
    ct = body[16:]
    try:
        raw = base64.b64decode(ct + "=" * (-len(ct) % 4))
    except Exception:
        return ""
    if not raw or len(raw) % 16:
        return ""
    try:
        text = _aes_cbc_dec(raw, key, key).decode("utf-8", "ignore")
    except Exception:
        return ""
    return text if text.startswith("http") else ""


class Spider(BaseSpider):
    def getName(self):
        return "影探4K"

    def getDependence(self):
        return []

    def setExtendInfo(self, extend):
        pass

    def init(self, extend=""):
        self.host = HOST
        try:
            if isinstance(extend, str) and extend.strip().startswith("{"):
                cfg = json.loads(str(extend))
                if cfg.get("host"):
                    self.host = str(cfg["host"]).rstrip("/")
        except Exception:
            pass

    # ---------------------------------------------------------------- HTTP
    def _get(self, url, timeout=20):
        h = {"User-Agent": UA, "Accept-Encoding": "identity", "Accept": "application/json"}
        for _ in range(2):
            try:
                r = urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)
                txt = r.read().decode("utf-8", "ignore")
                try:
                    return json.loads(txt)
                except Exception:
                    return {"__raw": txt[:200]}
            except Exception:
                time.sleep(0.4)
        return {}

    def _cms(self, action, params):
        q = urllib.parse.urlencode(params or {})
        return self._get("%s/api.php/app/%s?%s" % (self.host, action, q))

    # ---------------------------------------------------------------- 首页
    def homeContent(self, filter):
        j = self._cms("nav", {"token": ""})
        classes, filters = [], {}
        for c in (j.get("list") or []):
            tid = str(c.get("type_id") or "")
            name = _clean(c.get("type_name"))
            if not tid or not name:
                continue
            classes.append({"type_id": tid, "type_name": name})
            fl = []
            ext = c.get("type_extend") or {}
            if filter:
                for key, label in FILTER_KEYS:
                    raw = _clean(ext.get(key))
                    if not raw:
                        continue
                    vals = []
                    seen = set()
                    for v in raw.split(","):
                        v = v.strip()
                        if not v or v in seen:
                            continue
                        seen.add(v)
                        vals.append({"n": v, "v": v})
                    if len(vals) > 1:
                        fl.append({"key": key, "name": label,
                                   "value": [{"n": "全部", "v": ""}] + vals})
            filters[tid] = fl or []
        if not classes:
            classes = [{"type_id": "1", "type_name": "电影"}]
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        j = self._cms("index_video", {"token": ""})
        out = []
        for block in (j.get("list") or []):
            for it in (block.get("vlist") or []) if isinstance(block, dict) else []:
                v = self._item(it)
                if v:
                    out.append(v)
        return {"list": out}

    def _item(self, it):
        if not isinstance(it, dict):
            return None
        vid = str(it.get("vod_id") or it.get("id") or "")
        name = _clean(it.get("vod_name") or it.get("name"))
        if not vid or not name:
            return None
        pic = _fix(it.get("vod_pic") or it.get("vod_pic_thumb") or "")
        remarks = _clean(it.get("vod_remarks") or "")
        if not remarks and it.get("vod_score") and str(it.get("vod_score")) not in ("0.0", "0"):
            remarks = "评分 %s" % it.get("vod_score")
        return {"vod_id": vid, "vod_name": name, "vod_pic": pic, "vod_remarks": remarks}

    # ---------------------------------------------------------------- 分类
    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(str(pg).strip() or 1))
        except Exception:
            page = 1
        ext = extend if isinstance(extend, dict) else {}
        params = {"tid": str(tid), "pg": str(page), "limit": "18"}
        for key, _ in FILTER_KEYS:
            v = str(ext.get(key) or "").strip()
            if v and v != "all":
                params[key] = v
        j = self._cms("video", params)
        lst = [self._item(x) for x in (j.get("list") or [])]
        lst = [x for x in lst if x]
        try:
            pages = int(j.get("pagecount") or 0)
        except Exception:
            pages = 0
        if pages <= 0:
            pages = page + 1 if lst else page
        return {"page": page, "pagecount": pages, "limit": 18,
                "total": int(j.get("total") or pages * 18), "list": lst}

    # ---------------------------------------------------------------- 详情
    def detailContent(self, ids):
        vid = str(ids[0] or "")
        if not vid:
            return {"list": []}
        j = self._cms("video_detail", {"id": vid})
        d = j.get("data") or {}
        if not d:
            return {"list": []}
        froms = [x for x in str(d.get("vod_play_from") or "").split("$$$") if x]
        raw_urls = [x for x in str(d.get("vod_play_url") or "").split("$$$")]
        urls = []
        for grp in raw_urls:
            eps = []
            for part in grp.split("#"):
                part = part.strip()
                if not part:
                    continue
                if "$" in part:
                    t, u = part.split("$", 1)
                else:
                    t, u = "正片", part
                t = _safe(t) or "正片"
                u = u.strip()
                if u:
                    eps.append("%s$%s" % (t, u))
            urls.append("#".join(eps))
        while len(froms) < len(urls):
            froms.append("线路%d" % (len(froms) + 1))
        # 2026-11-18：4K(YD) 线路解析出的是移动云 EOS 的 AWS S3 V4 签名链
        # （X-Amz-Expires=900，仅 15 分钟有效），TVBox 只在开局解析一次 URL，
        # 播到 15~24 分钟签名过期就断流，且客户端无法延长（密钥在服务端）。
        # 实测 4K(BD) 与 4K(YD) 是同一个文件（同为 4013547923 字节），BD 走天翼云
        # 长期有效链、支持 Range。故此处把 YD 线路的播放地址替换为同片的 BD 地址，
        # 线路名保持不变——用户点"4K(YD)"实际拿到不过期的 BD 链接，彻底消除中途断流。
        try:
            bd_url = None
            for i, f in enumerate(froms):
                if "BD" in str(f).upper() and i < len(urls) and urls[i]:
                    bd_url = urls[i]
                    break
            if bd_url:
                for i, f in enumerate(froms):
                    if "YD" in str(f).upper() and i < len(urls):
                        urls[i] = bd_url
        except Exception:
            pass
        # 4kzj.lyyytv.cn 新解析口(parsesId=2)解出 4K 直链真实地址，展示全部线路
        pairs = []
        for f, u in zip(froms, urls):
            if not u:
                continue
            pairs.append((f, u))
        vod = {
            "vod_id": vid,
            "vod_name": _clean(d.get("vod_name")),
            "vod_pic": _fix(d.get("vod_pic") or d.get("vod_pic_thumb")),
            "type_name": _clean(d.get("vod_class")),
            "vod_year": str(d.get("vod_year") or ""),
            "vod_area": _clean(d.get("vod_area")),
            "vod_lang": _clean(d.get("vod_lang")),
            "vod_remarks": _clean(d.get("vod_remarks")),
            "vod_actor": _clean(d.get("vod_actor")),
            "vod_director": _clean(d.get("vod_director")),
            "vod_content": _clean(d.get("vod_content") or d.get("vod_blurb")),
            "vod_play_from": "$$$".join([p[0] for p in pairs]),
            "vod_play_url": "$$$".join([p[1] for p in pairs]),
        }
        if not pairs:
            vod["vod_play_from"] = ""
            vod["vod_play_url"] = ""
            vod["vod_remarks"] = (
                (_clean(d.get("vod_remarks")) + " ") if _clean(d.get("vod_remarks")) else ""
            ) + "（本站直链已失效，暂无可用线路）"
        return {"list": [vod]}

    # ---------------------------------------------------------------- 搜索
    def searchContent(self, key, quick, pg="1"):
        try:
            page = max(1, int(str(pg).strip() or 1))
        except Exception:
            page = 1
        j = self._cms("search", {"text": str(key or ""), "pg": str(page)})
        lst = [self._item(x) for x in (j.get("list") or [])]
        return {"list": [x for x in lst if x], "page": page}

    # ---------------------------------------------------------------- 播放
    def playerContent(self, flag, id, vipFlags):
        url = str(id or "").strip()
        try:
            # 1) 老加密串先本地解
            if url.startswith("lvdou+"):
                url = self._decrypt_lvdou(url) or url

            # 2) 已是媒体直链：失效源站给提示，其余直出
            if MEDIA_RE.search(url):
                host = urllib.parse.urlparse(url).hostname or ""
                if YT4K_HOST.search(host) or host.endswith("lyyytv.cn"):
                    # 源站已搬空，先试一次老 fys 专线；不行再试小白
                    real = self._chain(url)
                    if real:
                        return {"parse": 0, "playUrl": "", "url": real,
                                "header": '{"User-Agent":"%s"}' % UA}
                    real, hdr = _xb_parse(url)
                    if real:
                        return {"parse": 0, "playUrl": "", "url": real, "header": hdr}
                    return {"parse": 0, "playUrl": "", "url": url,
                            "header": '{"User-Agent":"%s"}' % UA,
                            "msg": "该 4K 直链源站已失效，请切换其它线路"}
                return {"parse": 0, "playUrl": "", "url": url,
                        "header": '{"User-Agent":"%s"}' % UA}

            # 3) 官方平台页面链接 → 优先小白解析（本次修复核心）
            host = urllib.parse.urlparse(url).hostname or ""
            if OFFICIAL_HOST.search(host):
                real, hdr = _xb_parse(url)
                if real:
                    return {"parse": 0, "playUrl": "", "url": real, "header": hdr}

            # 4) 兜底：老 fys 解析（baidu.con 链）
            real = self._parse(url)
            if real:
                return {"parse": 0, "playUrl": "", "url": real,
                        "header": '{"User-Agent":"%s"}' % UA}
            # 5) 再兜底：任意 http 链接也送小白试一次
            if url.startswith("http"):
                real, hdr = _xb_parse(url)
                if real:
                    return {"parse": 0, "playUrl": "", "url": real, "header": hdr}
                return {"parse": 1, "playUrl": "", "url": url, "header": ""}
        except Exception:
            pass
        return {"parse": 1, "playUrl": "", "url": url, "header": ""}

    def _decrypt_lvdou(self, s):
        """lvdou+<b64> → AES-CBC(key=CMS_KEY[0:16], iv=CMS_KEY[16:32])"""
        key = CMS_KEY[:16].encode()
        iv = (CMS_KEY[16:32] if len(CMS_KEY) >= 32 else CMS_KEY[:16]).encode()
        body = s[6:].strip()
        try:
            raw = base64.b64decode(body + "=" * (-len(body) % 4))
            out = _aes_cbc_dec(raw, key, iv).decode("utf-8", "ignore")
            return out if out.startswith("http") else ""
        except Exception:
            return ""

    def _chain(self, media_url):
        j = self._get(CHAIN_API + urllib.parse.quote(media_url, safe=""), timeout=25)
        return _decrypt_baidu(str(j.get("url") or ""))

    def _parse(self, page_url):
        j = self._get(PARSE_API + urllib.parse.quote(page_url, safe=""), timeout=25)
        url = str(j.get("url") or "")
        if url.startswith(DEC_PREFIX):
            return _decrypt_baidu(url)
        return url if url.startswith("http") else ""
