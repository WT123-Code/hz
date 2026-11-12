# -*- coding: utf-8 -*-
"""
================================================================================
 秒看视频 4K · CatVod / TVBox / Newbox  Python Spider
================================================================================
 站点   : https://mk1080.top   (秒看视频 APP 同源接口)
 版本   : v1.0
 依赖   : 仅标准库（自带纯 Python AES-128-CBC，无需 pycryptodome / requests）

 链路说明（已实测跑通）
 ----------------------------------------------------------------------------
  1. 搜索   POST /api.php/getappapi.index/searchList     body: keywords=&type_id=&page=
  2. 详情   POST /api.php/getappapi.index/vodDetail      body: vod_id=<id>
            —— 无需任何鉴权，裸调即可
  3. 解析   POST /api.php/getappapi.index/vodParse       body: parse_api=&url=&token=
            —— 必须携带 app-user-token（APP 账号 token），否则返回
               {"msg":"无权请求，请登录账号!","code":0}
  4. 响应外层 {"data":"<base64 AES 密文>","msg":"...","code":1}
            AES-128-CBC / PKCS7 / key = iv = c60d88b2eep53za8
            解密得 {"json":"<内层 JSON 字符串>"}
  5. 内层 JSON 关键字段
            url    : 华为云 EOS 签名直链（X-Amz-Expires=900 或 86400）
            from   : 网盘长期直链 http://lie.yuyun4kmaopan.qijiyun.vip/d/hcy/<ID>/<文件名>
                     —— 每次访问自动 302 到新的 EOS 签名链接，永不过期，优先使用
            type   : mp4 / hls
            system : 解析线路标识（RB4K/MiNO、秒看解析 …）

 关于 4K
 ----------------------------------------------------------------------------
  站内线路极多（单个片子可达 20+ 条），带 "4K" 字样的线路才有真 4K：
    · 4K·X / 4K·壹 / 4K·叁 / 4K·肆 / 热播4K …   → 实测 1.6~2.5 GB / 单集，ftyp isom
    · 部分 "蓝光" 线路实为广告流或快手图床伪流，播放时自动跳过
  本源保留全部线路（不砍），仅把含 4K 的线路排到前面。
================================================================================
"""
# ==============================================================================
#  ↓↓↓↓↓↓↓↓↓↓        只需改下面这两行，填你自己的秒看账号密码      ↓↓↓↓↓↓↓↓↓↓
# ==============================================================================

MY_ACCOUNT = ""     # 秒看 APP 登录账号
MY_PASSWORD = ""    # 秒看 APP 登录密码

# 填好上面两行就能用了，点播放时会自动登录拿 token，不用抓包、不用填 token。
# 不填也能浏览、分类、搜索、看详情，只是点播放会提示让你填。
#
# 注意：每次登录都会换发新 token，旧的立即作废。
#       所以每个人要用自己的秒看账号，不要几个人共用一个，否则会互相挤。
# ==============================================================================

import json
import time
import base64
import threading
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


# ============================================================== 纯 Python AES-128

SBOX = [
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
0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]

INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i

RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11b
    return a & 0xff


def _gmul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r & 0xff


def _expand_key(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [SBOX[b] for b in t]
            t[0] ^= RCON[i // 4 - 1]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(11)]


def _enc_block(block, rk):
    s = [block[i] ^ rk[0][i] for i in range(16)]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]
        s = [s[0], s[5], s[10], s[15],
             s[4], s[9], s[14], s[3],
             s[8], s[13], s[2], s[7],
             s[12], s[1], s[6], s[11]]
        if rnd != 10:
            out = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c], s[4 * c + 1], s[4 * c + 2], s[4 * c + 3]
                out += [_gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3,
                        a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3,
                        a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3),
                        _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2)]
            s = out
        s = [s[i] ^ rk[rnd][i] for i in range(16)]
    return s


def _dec_block(block, rk):
    s = [block[i] ^ rk[10][i] for i in range(16)]
    for rnd in range(9, -1, -1):
        s = [s[0], s[13], s[10], s[7],
             s[4], s[1], s[14], s[11],
             s[8], s[5], s[2], s[15],
             s[12], s[9], s[6], s[3]]
        s = [INV_SBOX[b] for b in s]
        s = [s[i] ^ rk[rnd][i] for i in range(16)]
        if rnd != 0:
            out = []
            for c in range(4):
                a0, a1, a2, a3 = s[4 * c], s[4 * c + 1], s[4 * c + 2], s[4 * c + 3]
                out += [_gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9),
                        _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13),
                        _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11),
                        _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)]
            s = out
    return s


def _cbc_encrypt(plain, key, iv):
    rk = _expand_key(key)
    out, prev = [], list(iv)
    for i in range(0, len(plain), 16):
        blk = [plain[i + j] ^ prev[j] for j in range(16)]
        enc = _enc_block(blk, rk)
        out += enc
        prev = enc
    return bytes(out)


def _cbc_decrypt(cipher, key, iv):
    rk = _expand_key(key)
    out, prev = [], list(iv)
    for i in range(0, len(cipher), 16):
        blk = list(cipher[i:i + 16])
        dec = _dec_block(blk, rk)
        out += [dec[j] ^ prev[j] for j in range(16)]
        prev = blk
    return bytes(out)


def aes_encrypt(text, key, iv):
    n = 16 - len(text) % 16
    data = text.encode("utf-8") + bytes([n]) * n
    return base64.b64encode(_cbc_encrypt(data, key, iv)).decode()


def aes_decrypt(b64, key, iv):
    raw = _cbc_decrypt(base64.b64decode(b64), key, iv)
    pad = raw[-1]
    if 1 <= pad <= 16:
        raw = raw[:-pad]
    return raw.decode("utf-8", "replace")


# ---------- 播放标识：短标识 vid|集序|线路名 ----------
# 内存里的 _marks 提供即用信息；进程重启/历史直播时用 vid 重新拉详情恢复。
def _rand_device_id():
    """没填 device_id 时随机生成一个，格式和 APP 一致：32 位十六进制"""
    import random
    return "".join(random.choice("0123456789abcdef") for _ in range(32))


def _mk_pid(vid, idx, name):
    n = str(name or "").replace("|", "/").replace("$", "").replace("#", "")
    return "%s|%d|%s" % (vid, idx, n)


def _split_pid(pid):
    parts = str(pid or "").split("|", 2)
    if len(parts) < 3:
        return None
    try:
        return {"vid": parts[0], "i": int(parts[1]), "name": parts[2]}
    except Exception:
        return None


# ============================================================== Spider

class Spider(BaseSpider):
    CONFIG = {
        "base": "https://mk1080.top/api.php/getappapi.",
        # 账号密码取文件顶部常量；配置里给 ext 也能覆盖。
        # token 恒为空，运行时由自动登录填入。
        "token": "",
        "device_id": "",
        "account": MY_ACCOUNT,
        "password": MY_PASSWORD,
        "aes_key": "c60d88b2eep53za8",
        "version_code": "135",
        "user_agent": "okhttp/3.14.9",
        "timeout": 25,
        # 4K 线路优先：含这些词的线路排在最前
        "prefer_words": ["4K", "4k", "蓝光4K", "高码"],
    }

    def __init__(self):
        super().__init__()
        self.cfg = dict(self.CONFIG)
        self.base = str(self.CONFIG["base"]).rstrip("/")
        self._key = bytes(self.CONFIG.get("aes_key") or "c60d88b2eep53za8", "utf-8")
        self._iv = self._key
        self._marks = {}     # 播放标识 -> {"parse","url"}
        self._lines = []     # 上次详情的线路（含未选中线路，用于降级）
        self._dcache = {}    # vid -> (时间戳, 结果, marks, lines)
        self._home_cache = None   # (时间戳, homeContent 结果)
        self._cat_cache = {}      # "tid|pg|year" -> (时间戳, 结果)
        # ---- 防封禁闸门 ----
        # 站点会按请求频率封 IP（443 超时 / 备用端口 444 掐断）。
        # 这里做三件事：全局最小请求间隔、连续失败熔断、熔断期内不再发请求。
        self._gate_lock = threading.Lock()
        self._last_req = 0.0      # 上次请求时间
        self._cool_until = 0.0    # 熔断截止时间
        self._fail_cnt = 0        # 连续失败计数
        self._min_gap = 0.8       # 相邻两次请求的最小间隔（秒）

    def getName(self):
        return "秒看4K"

    def init(self, extend=""):
        """extend 支持三种写法，随便选一种：
        1) JSON： {"token":"xxx","device_id":"yyy"}
        2) 键值： token=xxx&device_id=yyy   或  token=xxx,device_id=yyy
        3) 光填一串 token，device_id 留空也行
        """
        self.cfg = dict(self.CONFIG)
        if isinstance(extend, dict):
            self.cfg.update(extend)
        elif isinstance(extend, str) and extend.strip():
            t = extend.strip()
            try:
                self.cfg.update(json.loads(t))
            except Exception:
                if "=" in t:
                    for sep in ("&", ","):
                        t = t.replace(sep, "\n")
                    for ln in t.split("\n"):
                        if "=" in ln:
                            k, v = ln.split("=", 1)
                            self.cfg[k.strip().strip('"')] = v.strip().strip('"')
                elif len(t) >= 32:
                    # 没有键名、又足够长，直接当成 token
                    self.cfg["token"] = t
        self.base = str(self.cfg["base"]).rstrip("/")
        try:
            self._key = bytes(self.cfg["aes_key"], "utf-8")
        except Exception:
            self._key = bytes("c60d88b2eep53za8", "utf-8")
        self._iv = self._key

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".mkv", "cmecloud", "qijiyun"))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass

    def localProxy(self, param):
        return [404, "text/plain", "", None]

    # ---------------------------------------------------------------- 自动登录
    def _login(self):
        """用账号密码换 token。成功返回 token 字符串，失败返回 None。
        appLogin 不校验 app-api-verify-sign，裸调就能过。"""
        acct = str(self.cfg.get("account") or "").strip()
        pwd = str(self.cfg.get("password") or "").strip()
        if not acct or not pwd:
            return None
        dev = str(self.cfg.get("device_id") or "").strip() or _rand_device_id()
        body = urllib.parse.urlencode({
            "password": pwd,
            "code": "",
            "device_id": dev,
            "user_name": acct,
            "invite_code": "",
            "is_emulator": "1",
        })
        # 登录接口不用带 token，单独发一次请求
        url = self.base + "index/appLogin"
        req = urllib.request.Request(url, data=body.encode("utf-8"),
                                     headers={
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": str(self.cfg.get("user_agent") or "okhttp/3.14.9"),
            "app-version-code": str(self.cfg.get("version_code") or "135"),
            "app-ui-mode": "light",
            "app-user-device-id": dev,
        }, method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=int(self.cfg.get("timeout") or 25))
            outer = json.loads(resp.read().decode("utf-8", "replace"))
            if outer.get("code") != 1 or not outer.get("data"):
                return None
            d = self._decode(outer["data"])
            tok = str(((d.get("user") or {}).get("auth_token")) or "")
            if tok:
                # 登录会换发新 token，旧的作废：立刻用新的，并记住 device_id
                self.cfg["token"] = tok
                self.cfg["device_id"] = dev
            return tok or None
        except Exception:
            return None

    def _ensure_token(self, force=False):
        """保证手里有个可用的 token。
        已有 token 且不强制刷新时直接沿用；没有就尝试用账号密码登录。"""
        cur = str(self.cfg.get("token") or "").strip()
        if cur and not force:
            return cur
        if str(self.cfg.get("account") or "").strip():
            return self._login()
        return cur or None

    # ---------------------------------------------------------------- HTTP
    def _headers(self):
        return {
            "content-type": "application/x-www-form-urlencoded",
            "user-agent": str(self.cfg.get("user_agent") or "okhttp/3.14.9"),
            "app-version-code": str(self.cfg.get("version_code") or "135"),
            "app-ui-mode": "light",
            "app-user-device-id": str(self.cfg.get("device_id") or ""),
            "app-user-token": str(self.cfg.get("token") or ""),
        }

    def _post(self, path, data):
        url = self.base + path
        body = data.encode("utf-8") if isinstance(data, str) else data
        # 所有出站请求都过闸门：熔断期内直接返回，不碰服务器
        if not self._gate_wait():
            return {"code": 0, "msg": "站点限流中，请稍后再试"}
        req = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=int(self.cfg.get("timeout") or 25))
            txt = resp.read().decode("utf-8", "replace")
            r = json.loads(txt)
            # 业务层正常（code 1）才清零失败计数；返回"无权请求"不算 IP 封禁
            self._gate_ok()
            return r
        except Exception as e:
            hard = any(k in str(e) for k in ("444", "ConnectionReset", "RemoteDisconnected", "timed out"))
            self._gate_fail(hard=hard)
            return {"code": 0, "msg": "请求失败: %s" % e}

    def _decode(self, b64):
        """响应 data -> 内层 dict"""
        try:
            outer = json.loads(aes_decrypt(b64, self._key, self._iv))
            inner = outer.get("json")
            if isinstance(inner, str) and inner.strip():
                return json.loads(inner)
            return outer
        except Exception as e:
            return {"code": 0, "msg": "解密失败: %s" % e}

    def _api(self, path, data):
        r = self._post(path, data)
        if r.get("code") != 1:
            return {"code": 0, "msg": r.get("msg") or "接口异常"}
        d = r.get("data")
        if isinstance(d, str) and d:
            return self._decode(d)
        return {"code": 0, "msg": "无数据"}

    # ------------------------------------------------------------- 广告识别
    # 站内大量线路挂着"蓝光"名头，实际返回的是快手广告流或图床伪流，
    # 下面这些特征命中即判为广告，直接换线路，绝不交给播放器。
    AD_HOSTS = (
        "yximgs.com", "kwimgs.com", "kuaishou.com",
        "v1-ad", "adVideoLp", "ad.video",
        "imageGameZone", "static.yximgs",
    )
    AD_SYSTEM = ("酷云解析",)
    # 已知的伪流容器：内容其实是 png 序列，但后缀写成 m3u8
    FAKE_HLS_HOSTS = ("mk1080p.top/cache_ghg",)

    def _is_ad(self, url, system=""):
        u = str(url or "").lower()
        if not u:
            return True
        for h in self.AD_HOSTS:
            if h in u:
                return True
        for s in self.AD_SYSTEM:
            if s and s in str(system or ""):
                return True
        for h in self.FAKE_HLS_HOSTS:
            if h in u:
                return True
        return False

    # 伪链前缀：返回里若还带着这些，说明解析接口其实没解开（多见于
    # gzjx / kxjx / omo / jp 这类"直连解析地址"，服务器原样回吐伪链）
    FAKE_PREFIX = ("qf_vdo-", "qf_mp4-", "seven-", "mksp", "rb4k-", "xin4k-",
                   "aclg-", "gztv-", "co4k_", "mk ") 

    def _is_valid(self, url):
        """必须是 http(s) 开头的真实地址，且不是伪链残留"""
        u = str(url or "").strip()
        if not u.startswith("http"):
            return False
        low = u.lower()
        tail = low.split("://", 1)[-1]
        for p in self.FAKE_PREFIX:
            if tail.startswith(p):
                return False
        return True

    # ---------------------------------------------------------------- 列表
    # 分类表（已实测 type_id -> 总量）：
    #   1 电影 99182 / 2 电视剧 64576 / 3 综艺 29544 / 4 动漫 74096
    #   5 纪录片 4862 / 6 短剧 167906 / 7 少儿 7878 / 0 全部 448660
    CATS = [
        ("1", "电影"), ("2", "电视剧"), ("3", "综艺"), ("4", "动漫"),
        ("6", "短剧"), ("7", "少儿"), ("5", "纪录片"),
    ]
    # 分类列表走 maccms 的 ac=detail（不带斜杠；带斜杠会被 WAF 444 断连）。
    # ac=list 虽然也通，但不返回 vod_pic，会导致整页没有海报，所以用 detail。
    MAC_LIST = "api.php/provide/vod?ac=detail"
    MAC_BASES = ("https://mk1080.top/", "http://154.201.81.41:1688/")

    # 实测只有 year 参数生效（class/area/lang 后端直接忽略）
    YEARS = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018"]

    @staticmethod
    def _pack_one(it):
        """单条 -> TVBox 视频对象（首页/分类通用）"""
        if not isinstance(it, dict):
            return None
        vid = it.get("vod_id")
        if vid in (None, "", 0):
            return None
        return {
            "vod_id": str(vid),
            "vod_name": str(it.get("vod_name") or ""),
            "vod_pic": str(it.get("vod_pic") or it.get("vod_pic_slide") or ""),
            "vod_remarks": str(it.get("vod_remarks") or ""),
            "vod_year": str(it.get("vod_year") or ""),
            "vod_area": str(it.get("vod_area") or ""),
            "vod_lang": str(it.get("vod_lang") or ""),
        }

    def homeContent(self, filter):
        """按 APP 首页接口 initV119 还原：分类表 + 轮播 + 推荐"""
        # initV119 返回 85KB 密文，解密约 2-3s；内容变动慢，缓存 30 分钟
        if self._home_cache and time.time() - self._home_cache[0] < 1800:
            return self._home_cache[1]

        cats, videos, seen = [], [], set()
        try:
            r = self._api("index/initV119", "")
        except Exception:
            r = {}

        types = r.get("type_list") or []
        for t in types:
            if not isinstance(t, dict):
                continue
            tid = str(t.get("type_id") if t.get("type_id") is not None else "")
            name = str(t.get("type_name") or "").strip()
            if not tid or not name:
                continue
            cats.append({"type_id": tid, "type_name": name})

        # 首页推荐：轮播 -> 热门推荐 -> 各分类推荐（每类取 8 条）
        for key in ("banner_list", "recommend_list"):
            for it in (r.get(key) or []):
                o = self._pack_one(it)
                if o and o["vod_id"] not in seen:
                    seen.add(o["vod_id"])
                    videos.append(o)
        for t in types:
            if not isinstance(t, dict):
                continue
            for it in (t.get("recommend_list") or [])[:8]:
                o = self._pack_one(it)
                if o and o["vod_id"] not in seen:
                    seen.add(o["vod_id"])
                    videos.append(o)
        for it in (r.get("update") or []):
            o = self._pack_one(it)
            if o and o["vod_id"] not in seen:
                seen.add(o["vod_id"])
                videos.append(o)

        # 筛选：只开实测有效的年份
        yv = [{"n": y, "v": y} for y in self.YEARS]
        filters = {c["type_id"]: [{"key": "year", "name": "年份", "value": yv}]
                   for c in cats if c["type_id"] != "0"}

        res = {"class": cats, "list": videos, "filters": filters}
        self._home_cache = (time.time(), res)
        return res

    # ------------------------------------------------------- 防封禁 请求闸门
    def _gate_wait(self):
        """所有出站请求都先过这道闸：
        1) 熔断期内直接拒绝发送（返回 False），不发请求就不加深封禁
        2) 保证相邻两次请求至少间隔 _min_gap 秒，避免像爬虫一样连发
        """
        with self._gate_lock:
            if self._cool_until and time.time() < self._cool_until:
                return False
            gap = time.time() - self._last_req
            if gap < self._min_gap:
                time.sleep(self._min_gap - gap)
            self._last_req = time.time()
            return True

    def _gate_ok(self):
        """一次成功，清零失败计数"""
        with self._gate_lock:
            self._fail_cnt = 0

    def _gate_fail(self, hard=False):
        """一次失败：累计计数，连续失败就熔断一段时间，期间不再请求。
        hard=True 表示收到 444 / 连接被掐断这类明确的封禁信号，立即熔断。"""
        with self._gate_lock:
            self._fail_cnt += 1
            if hard or self._fail_cnt >= 3:
                # 首次 90 秒，之后翻倍，封顶 15 分钟
                back = min(90 * (2 ** (self._fail_cnt - 1)), 900)
                self._cool_until = time.time() + back

    def _mac_get(self, query, timeout=15):
        """maccms 列表接口。改为单路请求，避免同一台服务器被打两次导致封 IP。
        主站失败才走备用，且备用同样过闸门。"""
        for base in self.MAC_BASES:
            if not self._gate_wait():
                return {}
            try:
                url = base + self.MAC_LIST + query
                req = urllib.request.Request(
                    url, headers={"User-Agent": str(self.cfg.get("user_agent") or "okhttp/3.14.9")})
                resp = urllib.request.urlopen(req, timeout=timeout)
                data = json.loads(resp.read().decode("utf-8", "replace"))
                if isinstance(data, dict) and (data.get("list") or data.get("total")):
                    self._gate_ok()
                    return data
                self._gate_fail()
            except Exception as e:
                # 444 / ConnectionReset / RemoteDisconnected 都是封禁信号
                hard = any(k in str(e) for k in ("444", "ConnectionReset", "RemoteDisconnected", "timed out"))
                self._gate_fail(hard=hard)
                if hard:
                    break
        return {}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except Exception:
            page = 1

        q = ""
        t = str(tid or "").strip()
        if t and t != "0":
            q += "&t=%s" % urllib.parse.quote(t)
        if isinstance(extend, dict):
            y = str(extend.get("year") or "").strip()
            if y.isdigit():
                q += "&year=%s" % y
        q += "&pg=%d" % page

        # 分类页缓存 12 分钟：来回翻同一页不再重复打服务器，降低被封概率
        ck = "%s|%d|%s" % (t, page, str((extend or {}).get("year") or "") if isinstance(extend, dict) else "")
        ch = self._cat_cache.get(ck)
        if ch and time.time() - ch[0] < 720:
            return ch[1]

        r = self._mac_get(q)
        lst = []
        for it in (r.get("list") or []):
            o = self._pack_one(it)
            if o:
                lst.append(o)
        pc = r.get("pagecount")
        res = {
            "list": lst,
            "page": page,
            "pagecount": int(pc) if str(pc).isdigit() else 9999,
            "total": int(r.get("total") or len(lst)),
        }
        # 只有真拿到数据才缓存，空结果不缓存（避免一次失败被记住 12 分钟）
        if lst:
            if len(self._cat_cache) > 120:
                for k in list(self._cat_cache)[:60]:
                    self._cat_cache.pop(k, None)
            self._cat_cache[ck] = (time.time(), res)
        return res

    @staticmethod
    def _pack(items):
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            out.append({
                "vod_id": str(it.get("vod_id") or ""),
                "vod_name": str(it.get("vod_name") or ""),
                "vod_pic": str(it.get("vod_pic") or it.get("vod_pic_slide") or ""),
                "vod_remarks": str(it.get("vod_remarks") or ""),
                "vod_year": str(it.get("vod_year") or ""),
                "vod_area": str(it.get("vod_area") or ""),
                "vod_lang": str(it.get("vod_lang") or ""),
                "vod_class": str(it.get("vod_class") or ""),
                "vod_actor": str(it.get("vod_actor") or ""),
                "vod_content": str(it.get("vod_blurb") or ""),
            })
        return out

    def searchContent(self, key, quick, pg="1"):
        p = str(pg).strip()
        if not p.isdigit():
            p = "1"
        r = self._api("index/searchList",
                      "keywords=%s&type_id=0&page=%s" % (urllib.parse.quote(str(key)), p))
        lst = self._pack(r.get("search_list") or r.get("list") or [])
        return {"list": lst, "page": int(p), "pagecount": 9999, "total": len(lst)}

    def searchContentPage(self, key, quick, pg):
        return self.searchContent(key, quick, pg)

    # ---------------------------------------------------------------- 详情
    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = str(ids[0]).split(",")[0]
        # 详情缓存 180s：vodDetail 返回 180KB+，重复进入同一片子不必重拉
        h = self._dcache.get(vid)
        if h and time.time() - h[0] < 180:
            self._marks, self._lines = dict(h[2]), list(h[3])
            return h[1]
        r = self._api("index/vodDetail", "vod_id=%s" % vid)
        if r.get("code") != 200 and not isinstance(r.get("vod"), dict):
            return {"list": []}
        v = r.get("vod") or {}
        play_from, play_url = [], []
        self._marks = {}
        self._lines = []

        prefer = [str(w) for w in (self.cfg.get("prefer_words") or [])]
        lines = list(r.get("vod_play_list") or [])
        # 含 4K 的线路排前面（不删除任何线路）
        def rank(ln):
            nm = str((ln.get("player_info") or {}).get("show") or "")
            for i, w in enumerate(prefer):
                if w in nm:
                    return i
            return len(prefer)
        lines.sort(key=rank)

        for li, ln in enumerate(lines):
            pi = ln.get("player_info") or {}
            name = str(pi.get("show") or "线路%d" % (li + 1))
            parse_api = str(pi.get("parse") or "")
            urls = ln.get("urls") or []
            if not urls:
                continue
            eps = []
            for ep in urls:
                if not isinstance(ep, dict):
                    continue
                # TVBox 用 $ 分隔集名与标识、# 分隔集数，这两个字符必须清掉
                ep_name = str(ep.get("name") or "").strip().replace("$", "").replace("#", "")
                furl = str(ep.get("url") or "")
                if not ep_name or not furl:
                    continue
                mk = _mk_pid(vid, len(eps), name)
                self._marks[mk] = {"parse": parse_api, "url": furl, "name": name}
                eps.append("%s$%s" % (ep_name, mk))
            if not eps:
                continue
            self._lines.append({"name": name, "parse": parse_api,
                                "urls": [e.get("url") for e in urls if isinstance(e, dict)]})
            play_from.append(name)
            play_url.append("#".join(eps))

        res = {"list": [{
            "vod_id": vid,
            "vod_name": str(v.get("vod_name") or ""),
            "vod_pic": str(v.get("vod_pic") or ""),
            "vod_actor": str(v.get("vod_actor") or ""),
            "vod_director": str(v.get("vod_director") or ""),
            "vod_year": str(v.get("vod_year") or ""),
            "vod_area": str(v.get("vod_area") or ""),
            "vod_lang": str(v.get("vod_lang") or ""),
            "vod_class": str(v.get("vod_class") or ""),
            "vod_state": str(v.get("vod_state") or ""),
            "vod_total": str(v.get("vod_total") or ""),
            "vod_serial": str(v.get("vod_serial") or ""),
            "vod_remarks": str(v.get("vod_remarks") or ""),
            "vod_content": str(v.get("vod_content") or v.get("vod_blurb") or ""),
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }]}
        self._dcache[vid] = (time.time(), res, dict(self._marks), list(self._lines))
        if len(self._dcache) > 60:
            for k in list(self._dcache)[:30]:
                self._dcache.pop(k, None)
        return res

    # ---------------------------------------------------------------- 播放
    def _parse_once(self, parse_api, fake_url):
        """发一次 vodParse，返回解密后的字典"""
        body = urllib.parse.urlencode({
            "parse_api": parse_api,
            "url": aes_encrypt(fake_url, self._key, self._iv),
            "token": "",
        })
        return self._api("index/vodParse", body)

    def _parse_ep(self, parse_api, fake_url):
        """伪链 -> 播放地址，返回 (url, headers, err)。命中广告一律判失败。"""
        tok = self._ensure_token()
        if not tok:
            return None, {}, ("没账号也没 token，播不了 4K。"
                              "打开这个 py 文件，把顶部的 MY_ACCOUNT / MY_PASSWORD "
                              "填成你的秒看账号密码即可（会自动登录）。")
        r = self._parse_once(parse_api, fake_url)
        # token 过期（被别处登录顶掉 / 服务端过期）时自动重新登录再试一次
        if r.get("code") != 200 and "登录" in str(r.get("msg") or ""):
            if str(self.cfg.get("account") or "").strip():
                if self._login():
                    r = self._parse_once(parse_api, fake_url)
        if r.get("code") != 200:
            return None, {}, str(r.get("msg") or "解析失败")
        system = str(r.get("system") or "")
        # 优先用 url（华为云 EOS 直链，实测 20+ MB/s，秒开 4K）
        # from 是网盘长期直链，但要多跳一次 302 且常被限速，仅作兜底。
        u = str(r.get("url") or "")
        if self._is_valid(u) and not self._is_ad(u, system):
            return u, (r.get("headers") if isinstance(r.get("headers"), dict) else {}), ""
        frm = str(r.get("from") or "")
        if self._is_valid(frm) and not self._is_ad(frm, system):
            return frm, {}, ""
        if self._is_ad(u or frm, system):
            return None, {}, "广告源，已跳过"
        return None, {}, "该线路未返回有效地址"

    def playerContent(self, flag, pid, vipFlags=None):
        if not pid:
            return {"parse": 0, "url": "", "header": {}}
        cur = self._marks.get(pid)
        if not cur:
            # 冷启动 / 从历史记录直接播：用 pid 里的 vid 回拉详情重建映射
            info = _split_pid(pid)
            if not info:
                return {"parse": 0, "url": "", "header": {}, "msg": "标识失效，请重新进入详情"}
            try:
                _d = self.detailContent([info["vid"]])
                cur = self._marks.get(pid)
            except Exception:
                cur = None
            if not cur:
                return {"parse": 0, "url": "", "header": {}, "msg": "标识失效，请重新进入详情"}
        idx = int(cur.get("i") or 0)

        url, hdr, err = self._parse_ep(cur.get("parse"), cur.get("url"))

        # 当前线路失败/是广告 -> 按序试其它线路的同一集（4K 线路排在前面）
        # 限制最多试 4 条，避免解析接口逐个超时把播放等待拉到几十秒
        if not url:
            tried = 0
            for ln in self._lines:
                if tried >= 4:
                    break
                if ln.get("name") == cur.get("name"):
                    continue
                urls = ln.get("urls") or []
                if idx >= len(urls) or not urls[idx]:
                    continue
                tried += 1
                u2, h2, _e2 = self._parse_ep(ln.get("parse"), urls[idx])
                if u2:
                    url, hdr, err = u2, h2, ""
                    break

        if not url:
            return {"parse": 0, "url": "", "header": {}, "msg": err or "播放失败"}

        header = {
            "User-Agent": "okhttp/4.12.0",
            "Accept-Encoding": "identity",
        }
        if hdr:
            header.update(hdr)
        return {"parse": 0, "url": url, "header": header}
