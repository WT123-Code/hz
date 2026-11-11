# -*- coding: utf-8 -*-
# 影探4K：由 影探4k.js 移植到鱼壳 webhtv 站点注入使用的 Python Spider。
# 用法：把本文件放到手机 /sdcard/py/影探4K.py，站点配置 api 填 file:///sdcard/py/影探4K.py
#
# 2026-10-31 播放修复（全部结论来自真实请求实测，非推测）：
#   1) 解析接口 http://fys.lyyytv.cn/api/index 仍然活着，但 parsesId=3 这条记录已经查不到了，
#      带 videoUrl 请求直接抛 PHP 异常：HTTP 500 / "Trying to get property 'url' of non-object"
#      （Parses.php line 63）。枚举 1~12 后只有 parsesId=5 正常返回
#      {"code":200,"url":"https://baidu.con/..."}，6、7 返回 {"code":0,"msg":"解析失败"}，
#      其余全是同一个 500 错误页。所以解析主线路改为 5，并保留 6/7 作为兜底重试。
#   2) baidu.con 前缀的 AES 解密逻辑没有变（前 16 位当 key 和 iv，余下 base64 密文，AES/CBC/PKCS7），
#      实测仍能解出真实 m3u8/mpd 地址，这段保持原样。
#   3) 原 play() 把所有地址无条件丢给解析接口。但 4K(YD)/4K(BD) 两条线路的 vod_play_url
#      本身就是直链 mp4（http://ym4kjx.lyyytv.cn/d/file/xxx/片名4K.mp4），
#      就算解析接口活着，对 mp4 直链请求也只会得到「解析失败」。现在直链直接交给播放器，不再绕解析。
#   4) 4K 直链的源站 ym4kjx.lyyytv.cn 已经搬空：实测 40 部影片共 111 条该域名直链，
#      随便取多条都是 HTTP 404（https 是 502 Bad Gateway，nginx 回源失败）。
#      这不是脚本能修的，脚本改成：详情页把已确认失效的源站线路隐藏，播放时若仍命中给出明确提示，
#      避免用户点进去只看到黑屏。
import base64
import json
import re
import time
import urllib.parse

# ==== 依赖兼容层（壳内无 requests / pycryptodome 时用纯标准库顶上）====
import gzip
import zlib
import urllib.request as _urq
import ssl as _ssl

_CTX = _ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = _ssl.CERT_NONE


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


class _PureAES(object):
    _SBOX = _build_sbox()
    _RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36, 0x6C, 0xD8, 0xAB, 0x4D]

    def __init__(self, key):
        if len(key) not in (16, 24, 32):
            raise ValueError("bad key")
        self.nk = len(key) // 4
        self.nr = self.nk + 6
        self.rk = self._expand(key)

    def _expand(self, key):
        SBOX = _PureAES._SBOX
        RCON = _PureAES._RCON
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

    def dec(self, block):
        SBOX = _PureAES._SBOX
        inv = _INV_SBOX
        s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
        self._add(s, self.nr)
        for rnd in range(self.nr - 1, -1, -1):
            for r in range(1, 4):
                s[r] = s[r][-r:] + s[r][:-r]
            for r in range(4):
                for c in range(4):
                    s[r][c] = inv[s[r][c]]
            self._add(s, rnd)
            if rnd != 0:
                for c in range(4):
                    a0, a1, a2, a3 = s[0][c], s[1][c], s[2][c], s[3][c]
                    s[0][c] = _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
                    s[1][c] = _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
                    s[2][c] = _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
                    s[3][c] = _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)
        return bytes(s[r][c] for c in range(4) for r in range(4))


_INV_SBOX = [0] * 256
for _i, _v in enumerate(_PureAES._SBOX):
    _INV_SBOX[_v] = _i


class _AESCipher(object):
    def __init__(self, key, iv):
        self.key = key[:16] if len(key) > 16 else key
        self.iv = iv[:16] if len(iv) > 16 else iv

    def decrypt(self, data):
        if len(data) % 16:
            data = data[:len(data) - len(data) % 16]
        aes = _PureAES(self.key)
        out = bytearray()
        prev = self.iv
        for i in range(0, len(data), 16):
            blk = data[i:i + 16]
            dec = aes.dec(blk)
            out += bytes(dec[j] ^ prev[j] for j in range(16))
            prev = blk
        return bytes(out)


class _AESModule(object):
    MODE_CBC = 2
    block_size = 16

    @staticmethod
    def new(key, mode, iv=None):
        return _AESCipher(key, iv or key)


def unpad(data, block_size=16):
    if not data:
        return data
    n = data[-1]
    if 0 < n <= block_size:
        return data[:-n]
    return data


class _FakeResponse(object):
    def __init__(self, body, status, url, headers):
        self._body = body
        self.status_code = status
        self.url = url
        self.headers = headers
        self.encoding = 'utf-8'

    @property
    def content(self):
        return self._body

    @property
    def text(self):
        return self._body.decode('utf-8', 'replace')

    def json(self):
        return json.loads(self.text)


def _raw_request(url, headers=None, timeout=15, method='GET'):
    req = _urq.Request(url, headers=headers or {}, method=method)
    try:
        with _urq.urlopen(req, context=_CTX, timeout=timeout) as r:
            body = r.read()
            hdr = dict(r.headers)
            if body[:2] == b'\x1f\x8b':
                try:
                    body = gzip.decompress(body)
                except Exception:
                    pass
            elif hdr.get('Content-Encoding', '').lower() == 'deflate':
                try:
                    body = zlib.decompress(body, -zlib.MAX_WBITS)
                except Exception:
                    pass
            return _FakeResponse(body, r.status, url, hdr)
    except _urq.HTTPError as e:
        body = b''
        try:
            body = e.read() or b''
        except Exception:
            pass
        return _FakeResponse(body, e.code, url, dict(e.headers or {}))


class _RequestsShim(object):
    def get(self, url, headers=None, timeout=15, allow_redirects=True, **kw):
        return _raw_request(url, headers, timeout, 'GET')

    def head(self, url, headers=None, timeout=15, allow_redirects=False, **kw):
        return _raw_request(url, headers, timeout, 'HEAD')

    def post(self, url, headers=None, timeout=15, **kw):
        return _raw_request(url, headers, timeout, 'POST')


try:
    import requests
except ImportError:
    requests = _RequestsShim()
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    AES = _AESModule()
# ==== 兼容层结束 ====

try:
    from base.spider import Spider
except ImportError:
    import sys
    sys.path.append('..')
    from base.spider import Spider

KEY = 'yingtan4k'
HOST = 'http://cms.lyyytv.cn'
CMS_KEY = 'wP5bvxoc3yv7FoBQENFZuAF0EUYr4LTy'

# 解析接口（2026-10-31 实测：parsesId=3 已失效返回 HTTP 500，parsesId=5 可用）
PARSE_API = 'http://fys.lyyytv.cn/api/index'
PARSE_APPID = '10001'
# 解析线路优先级：5 是当前唯一稳定出地址的；6、7 会快速返回「解析失败」，留作兜底
PARSE_IDS = (5, 6, 7)
HEADERS = {'User-Agent': 'okhttp/4.12.0'}
# 解析请求/回源头：对齐 JS 的 PH，避免 gzip 花屏
PARSE_HEADERS = {'User-Agent': 'okhttp/4.12.0', 'Accept-Encoding': 'identity'}

# baidu.con 前缀加密常量（对齐 yt4k.js）
DEC_PREFIX = 'https://baidu.con/'
# 解析重试轮数与退避基数（秒）
PARSE_ROUNDS = 2
PARSE_BACKOFF = 0.3
# 同一原始地址解析结果缓存窗口（秒）
PLAY_CACHE_TTL = 120

PAGE_LIMIT = 20
# 2026-10-31：nav 的 type_extend 实际还带 star/director/state/version，补上映射
FILTER_NAMES = {
    'class': '类型', 'area': '地区', 'lang': '语言', 'year': '年份',
    'letter': '字母', 'by': '排序', 'sort': '顺序',
    'star': '主演', 'director': '导演', 'state': '状态', 'version': '版本',
}
HOME_CACHE_TTL = 6 * 3600

# 直链源站健康检查缓存（秒）：避免每个详情页都重复探测
HOST_CHECK_TTL = 600
# 探测时只认这两个状态码为「源站已失效」，其余一律放行，避免误杀
HOST_DEAD_STATUS = (404, 502)

_BASE64_RE = re.compile(r'(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?')
_LDMAX_RE = re.compile(r'^https?://ldmax\.cooom/', re.I)
_MEDIA_RE = re.compile(r'\.(?:mp4|m3u8?|flv|avi|mkv|ts|mov|wmv|webm|m4v|mpd)$', re.I)
_HOST_RE = re.compile(r'^https?://([^/]+)', re.I)

_home_cache = {}
_play_cache = {}
_host_cache = {}


def text(value):
    return '' if value is None else str(value).strip()


def page_of(value):
    m = re.match(r'\s*[+-]?\d+', '' if value is None else str(value))
    n = int(m.group(0)) if m else 0
    return max(1, n) if n else 1


def list_of(value):
    return value if isinstance(value, list) else []


def object_of(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def get_json(url, headers=None, timeout=15):
    headers = HEADERS if headers is None else headers
    rsp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    try:
        data = object_of(rsp.json())
    except Exception:
        data = {}
    if not data:
        raise Exception('影探4K：接口未返回有效 JSON')
    return data


def cms(path, params=None):
    params = params or {}
    query = urllib.parse.urlencode(params)
    data = get_json('%s/api.php/app/%s?%s' % (HOST, path, query))
    code = data.get('code')
    if code is not None:
        try:
            ok = int(code) in (1, 200)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise Exception('影探4K：CMS 请求失败')
    return data


def decode_base64(value):
    clean = re.sub(r'\s+', '', text(value))
    if not clean or not _BASE64_RE.fullmatch(clean):
        return None
    try:
        return base64.b64decode(clean)
    except Exception:
        return None


def decrypt_lvdou(value):
    """对齐 JS decUrlOne：lvdou+ → 前16 key/后16 iv AES/CBC/PKCS7"""
    original = text(value)
    if not original.startswith('lvdou+'):
        return original
    if not CMS_KEY:
        return original
    try:
        encrypted = decode_base64(original[6:])
        if not encrypted:
            return original
        key = CMS_KEY[:16].encode('utf-8')
        iv = CMS_KEY[16:32].encode('utf-8') if len(CMS_KEY) >= 32 else key
        cipher = AES.new(key, AES.MODE_CBC, iv)
        plain = unpad(cipher.decrypt(encrypted), AES.block_size)
        result = plain.decode('utf-8', errors='replace').strip()
        if result.startswith('http'):
            return result
    except Exception:
        pass
    return original


def is_http_url(value):
    try:
        parsed = urllib.parse.urlparse(text(value))
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


def is_site_url(value):
    if not is_http_url(value):
        return False
    host = (urllib.parse.urlparse(text(value)).hostname or '').lower()
    return host == 'lyyytv.cn' or host.endswith('.lyyytv.cn')


def is_ldmax_url(value):
    return bool(_LDMAX_RE.match(text(value)))


def decrypt_ldmax(value, depth=0):
    """兼容老加密：ldmax.cooom 前缀"""
    if depth > 5:
        return ''
    url = text(value)
    decoded = decode_base64(url)
    if decoded:
        url = re.sub(r'\s+', '', decoded.decode('utf-8', errors='replace'))
    if not is_ldmax_url(url):
        return url
    path = _LDMAX_RE.sub('', url)
    if len(path) <= 16:
        return ''
    try:
        key = path[:16][::-1].encode('utf-8')
        encrypted = decode_base64(path[16:])
        if not encrypted or len(encrypted) % 16:
            return ''
        cipher = AES.new(key, AES.MODE_CBC, key)
        plain = bytearray(cipher.decrypt(encrypted))
        pad = plain[-1]
        if 0 < pad <= 16:
            del plain[-pad:]
        result = bytes(plain).decode('utf-8', errors='replace').strip()
        return decrypt_ldmax(result, depth + 1) if is_ldmax_url(result) else result
    except Exception:
        return ''


def find_url(value):
    """对齐 JS findUrl：从解析响应 JSON 中挑出 url/playUrl/link/data.url"""
    if not isinstance(value, dict):
        return ''
    for key in ('url', 'playUrl', 'link'):
        v = value.get(key)
        if v:
            return text(v)
    return find_url(value.get('data'))


def resolve_parse(body):
    """
    对齐 JS resolveParse：
      1) JSON 包裹 → 取出 url
      2) https://baidu.con/ 前缀 → 前16位 key=iv，余下 base64 密文 AES/CBC/PKCS7
      3) 明文 URL
    """
    body = text(body)
    if not body:
        return ''

    candidate = body
    if body.startswith('{'):
        try:
            parsed = json.loads(body)
            found = find_url(parsed)
            if found:
                candidate = found
        except Exception:
            pass

    if candidate.startswith(DEC_PREFIX):
        rest = candidate[len(DEC_PREFIX):]
        if len(rest) <= 16:
            return ''
        key = rest[:16].encode('utf-8')
        cipher_b64 = rest[16:]
        # 优先按 base64 密文解密（实测这条路径有效）
        try:
            encrypted = base64.b64decode(cipher_b64 + '=' * (-len(cipher_b64) % 4), validate=False)
            cipher = AES.new(key, AES.MODE_CBC, key)
            plain = unpad(cipher.decrypt(encrypted), AES.block_size)
            result = plain.decode('utf-8', errors='replace').strip()
            if result.startswith('http'):
                return result
        except Exception:
            pass
        # 兜底：密文本身是 raw bytes
        try:
            raw = cipher_b64.encode('latin-1', errors='ignore')
            if raw and len(raw) % 16 == 0:
                cipher = AES.new(key, AES.MODE_CBC, key)
                plain = unpad(cipher.decrypt(raw), AES.block_size)
                result = plain.decode('utf-8', errors='replace').strip()
                if result.startswith('http'):
                    return result
        except Exception:
            pass
        return ''

    return candidate


def parse_round(raw, parse_id):
    """按指定 parsesId 解析一次，返回解出的真实地址（失败返回空串）。"""
    target = '%s?parsesId=%s&appid=%s&videoUrl=%s' % (
        PARSE_API, parse_id, PARSE_APPID, urllib.parse.quote(raw, safe="!'()*"))
    try:
        rsp = requests.get(target, headers=PARSE_HEADERS, timeout=20)
        # 2026-10-31：parsesId 失效时这里回的是 HTTP 500 的 ThinkPHP 错误页，
        # 直接跳过，不做任何解析，避免把 HTML 当成地址。
        if rsp.status_code != 200 or not rsp.text:
            return ''
        if 'System Error' in rsp.text[:2000]:
            return ''
        resolved = resolve_parse(rsp.text)
        if resolved and resolved.startswith('http'):
            return resolved
    except Exception:
        pass
    return ''


def parse_url(raw):
    """对齐 JS play 内部：把原始地址拼到解析基址后请求，解出真实 URL。
    多 parsesId + 多轮退避，任一成功即返回。"""
    if not raw:
        return ''
    for rnd in range(PARSE_ROUNDS):
        if rnd > 0:
            time.sleep(rnd * PARSE_BACKOFF)
        for parse_id in PARSE_IDS:
            resolved = parse_round(raw, parse_id)
            if resolved:
                return resolved
    return ''


def is_media_url(url):
    if not is_http_url(url):
        return False
    return bool(_MEDIA_RE.search(urllib.parse.urlparse(text(url)).path))


def host_of(url):
    m = _HOST_RE.match(text(url))
    return m.group(1).lower() if m else ''


def host_dead(url):
    """探测直链源站是否还活着。
    2026-10-31 实测 ym4kjx.lyyytv.cn 下 111 条 4K 直链全部 404（https 502），
    这类线路点进去必然黑屏，提前隐藏比让用户等超时好。
    只按 404/502 判定，其余状态码一律认为可用，避免误杀正常但拒绝目录列表的源站。"""
    host = host_of(url)
    if not host:
        return False
    cached = _host_cache.get(host)
    now = time.time()
    if cached and cached[0] > now:
        # 缓存里存的就是「是否失效」，直接返回
        return cached[1]
    dead = False
    try:
        rsp = requests.head('http://%s/d/file/' % host, headers=HEADERS, timeout=8,
                            allow_redirects=False)
        if rsp.status_code in HOST_DEAD_STATUS:
            dead = True
    except Exception:
        # 探测本身失败（超时/DNS）不当作失效，交给播放器实际请求去判定
        dead = False
    _host_cache[host] = (now + HOST_CHECK_TTL, dead)
    return dead


def home(extend=''):
    cache_key = '%s_home_%s' % (KEY, text(extend))
    cached = _home_cache.get(cache_key)
    if cached and cached[0] > time.time():
        return cached[1]
    data = cms('nav', {'token': ''})
    classes = []
    filters = {}
    for item in list_of(data.get('list')):
        if not isinstance(item, dict):
            continue
        if item.get('type_id') is None or not text(item.get('type_name')):
            continue
        tid = text(item['type_id'])
        classes.append({'type_id': tid, 'type_name': text(item['type_name'])})
        ext = object_of(item.get('type_extend'))
        groups = []
        for key, name in FILTER_NAMES.items():
            values = [v for v in (text(x) for x in text(ext.get(key)).split(',')) if v]
            values = list(dict.fromkeys(values))
            if values:
                groups.append({
                    'key': key,
                    'name': name,
                    'init': '',
                    'value': [{'n': '全部', 'v': ''}] + [{'n': v, 'v': v} for v in values],
                })
        if groups:
            filters[tid] = groups
    result = {'class': classes, 'filters': filters}
    if classes:
        _home_cache[cache_key] = (time.time() + HOME_CACHE_TTL, result)
    return result


def home_vod():
    data = cms('index_video', {'token': ''})
    vlist = []
    for item in list_of(data.get('list')):
        if isinstance(item, dict):
            vlist.extend(list_of(item.get('vlist')))
    return {'list': vlist}


def paginated(data, requested_page):
    lst = list_of(data.get('list'))
    raw_page = data.get('page')
    page = page_of(raw_page if raw_page is not None else requested_page)
    try:
        limit = int(data.get('limit') or 0)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        limit = PAGE_LIMIT
    try:
        raw_pagecount = int(data.get('pagecount') or 0)
    except (TypeError, ValueError):
        raw_pagecount = 0
    has_pagecount = raw_pagecount > 0
    pagecount = raw_pagecount if has_pagecount else page + (1 if len(lst) >= limit else 0)
    try:
        raw_total = data.get('total')
        has_total = raw_total is not None and int(raw_total) >= 0
    except (TypeError, ValueError):
        has_total = False
    if has_pagecount and has_total:
        total = int(data.get('total'))
    else:
        total = (page - 1) * limit + len(lst) + (1 if pagecount > page else 0)
    data['page'] = page
    data['pagecount'] = pagecount
    data['limit'] = limit
    data['total'] = total
    data['list'] = lst
    return data


def category(tid, pg, extend):
    page = page_of(pg)
    tid = text(tid)
    if not tid:
        return paginated({'list': []}, page)
    extend = extend if isinstance(extend, dict) else {}
    params = {'tid': tid, 'pg': str(page), 'limit': '18'}
    for key in FILTER_NAMES:
        value = text(extend.get(key))
        if value and value != 'all':
            params[key] = value
    return paginated(cms('video', params), page)


def playlist(value):
    parts = []
    for entry in text(value).split('#'):
        sep = entry.find('$')
        if sep <= 0 or not text(entry[sep + 1:]):
            continue
        parts.append('%s$%s' % (text(entry[:sep]), decrypt_lvdou(entry[sep + 1:])))
    return '#'.join(parts)


def detail(ids):
    if not isinstance(ids, (list, tuple)):
        ids = [ids]
    lst = []
    for vid in ids:
        vid = text(vid)
        if not vid:
            continue
        data = cms('video_detail', {'id': vid}).get('data')
        if not isinstance(data, dict):
            continue
        players = data.get('vod_url_with_player')
        vod = {k: v for k, v in data.items() if k != 'vod_url_with_player'}
        names = text(vod.get('vod_play_from')).split('$$$')
        if isinstance(players, list):
            sources = players
        else:
            sources = [
                {'name': names[i] if i < len(names) else '', 'url': u}
                for i, u in enumerate(text(vod.get('vod_play_url')).split('$$$'))
            ]
        froms = []
        urls = []
        for index, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            url = playlist(source.get('url'))
            if not url:
                continue
            # 2026-10-31：源站整域失效（实测 4K 直链域名全 404）的线路不上架，
            # 否则用户点进去只会黑屏。健康检查结果按域名缓存，不影响其它线路。
            first_ep = text(url.split('#')[0].split('$')[-1])
            if is_media_url(first_ep) and host_dead(first_ep):
                continue
            name = text(source.get('name')) or text(source.get('code')) or '线路%d' % (index + 1)
            froms.append(re.sub(r'[$#]', ' ', name))
            urls.append(url)
        vod['vod_play_from'] = '$$$'.join(froms)
        vod['vod_play_url'] = '$$$'.join(urls)
        lst.append(vod)
    return {'list': lst}


def search(key, pg):
    wd = text(key)
    page = page_of(pg)
    if not wd:
        return paginated({'list': []}, page)
    data = cms('search', {'text': wd, 'pg': str(page)})
    lst = []
    for item in list_of(data.get('list')):
        if isinstance(item, dict):
            lst.append({k: v for k, v in item.items() if k != 'type'})
    data['list'] = lst
    return paginated(data, page)


def play(play_id):
    """对齐 JS play：解析出真实地址再交播放器。
    2026-10-31 修复要点：
      - 直链（mp4/m3u8/mpd…）不再绕解析接口：解析接口对 mp4 直链只会回「解析失败」；
      - 解析线路从 parsesId=3 换成 5（3 已 500），并保留 6/7 兜底；
      - 任何失败都返回结构合法的 dict 并带 msg，让壳能显示原因而不是白屏。
    """
    original = decrypt_lvdou(play_id)
    if not original:
        return {'parse': 0, 'url': '', 'header': dict(PARSE_HEADERS),
                'msg': '影探4K：播放地址为空'}

    # 兼容老加密：ldmax 前缀先本地解密
    if is_ldmax_url(original):
        decrypted = decrypt_ldmax(original)
        if decrypted:
            original = decrypted

    # 直链优先：已经是可播媒体文件就不必解析
    if is_media_url(original):
        if host_dead(original):
            return {'parse': 0, 'url': '', 'header': dict(PARSE_HEADERS),
                    'msg': '影探4K：该线路源站已失效（HTTP 404），请换其它线路'}
        return {'parse': 0, 'url': original, 'header': dict(PARSE_HEADERS)}

    # 解析结果缓存
    now = time.time()
    cached = _play_cache.get(original)
    if cached and cached[0] > now:
        return {'parse': 0, 'url': cached[1], 'header': dict(PARSE_HEADERS)}

    resolved = parse_url(original)
    if resolved:
        _play_cache[original] = (now + PLAY_CACHE_TTL, resolved)
        return {'parse': 0, 'url': resolved, 'header': dict(PARSE_HEADERS)}

    # 解析整条链路失败：给出可读原因，等用户反馈具体线路
    return {'parse': 0, 'url': '', 'header': dict(PARSE_HEADERS),
            'msg': '影探4K：解析失败（解析接口返回异常或该线路暂不可用），请换线路重试'}


class Spider(Spider):
    extend = ''

    def getName(self):
        return '🎬 探影4K'

    def init(self, extend=''):
        self.extend = extend or ''

    def isVideoFormat(self, url):
        return is_media_url(url)

    def manualVideoCheck(self):
        return False

    def homeContent(self, filter):
        return home(self.extend)

    def homeVideoContent(self):
        return home_vod()

    def categoryContent(self, tid, pg, filter, extend):
        return category(tid, pg, extend)

    def detailContent(self, ids):
        return detail(ids)

    def searchContent(self, key, quick, pg='1'):
        return search(key, pg)

    def playerContent(self, flag, id, vipFlags):
        return play(id)

    def localProxy(self, param):
        return None

    def destroy(self):
        pass
