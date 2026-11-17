# -*- coding: utf-8 -*-
# ============================================================
# ★写源前必调·三底座
#   ①记忆库：知识库/影视源开发（01-规范契约 / 02-技能与工具链 / 03-攻坚档案 / 04-源交付档案）
#   ②技能包：/sdcard/Download/Operit/skills/SKILL_INDEX.md v2（L0 tvbox-py-v73 母版 → L1 pySkill
#     → L2 攻坚 → L3 adaptive 四工作台/三专项 → L4 交付 → L5 平行体系）
#   ③母版：cp 71模板 → 改 CONFIG ★区 → 改站点逻辑区（禁从零手写骨架）
#
# ★写源必加清单（缺则补）
#   ①大图片：列表 item 四件套 style={'type':'rect','ratio':1.78'} + land=1 + ratio=1.78
#     + type_name（分类项给 land/ratio）
#   ②二级分类/筛选器：homeContent 返 filters（dict，key 必须=一级 type_id；『全部』项 v 为空串）
#     + categoryContent 消费 extend（参数名 filter，键 cat/rq）
#   ③搜索：searchContent(key, quick, pg) 关键词 quote/归一化，真分页
#
# ★写源必检查清单（交付前逐条核对）
#   ①翻页：page/pagecount/limit/total 四件齐全，pagecount 真解析（禁 999 伪分页）
#   ②多线路：全部线路解析 + 探活，死线排最后保留
#   ③播放：playerContent 只回 parse/url/header 三键，逐线实测
#   ④分类：分类覆盖度足，补 LABEL/更多入口
#   ⑤图片：封面不得占位/裂图（补域名·去防盗链·本地代理三选一）
# ======== 必加/必检查清单结束 ========
#
# ★写源必调·站点实测（v2 · 2026-11-17）
#   · mtyy8.com 是 MacCMS 静态快照站：/vodtype/{tid}.html 与 /vodtype/{tid}-{p}.html
#     返回的 142 条 ID **完全相同**（分页/by/years 参数全失效）→ 真分页只能在源内做
#   · 卡片结构：a.public-list-exp(href/title/img[data-src]/备注) + a.time-title + div.public-list-subtitle(类型)
#   · 站内搜索 /vodsearch/ 需图形验证码（/verify/index.html）→ 服务端搜索不可用，走本地全站索引
#   · 首页/分类页实测 1.3~1.9s（快节点），旧版一次开 6 连接×多轮 → 触发站点拖慢反而空白
# ============================================================
"""
追影 v2.0 — TVBox / OK影视 双壳兼容 Spider
数据源：追影（原麦田影院）同名官网 mtyy8.com

== 为什么不是从 APK 里取接口 ==
  追影 2.99/2.0.4 是 Flutter + 幻系 packer + Apk-Dex2C-Pro 加固：
  libapp.so 业务词 UTF-8 0/20，2.49MB 载荷熵 7.9999，全包零业务域名。
  但官网 mtyy8.com 是标准 MacCMS 静态快照站，播放链完整，直接写站更稳。

== 站点实测特性 ==
  · 路由 /vodtype/<tid>.html、/voddetail/<id>.html、/vodplay/<id>-<sid>-1.html
  · 分页 / 排序 / 年份参数全部失效（第1页与第2页 136 条 ID 完全相同）
    → pagecount 固定 1，翻页交给「本地排序」筛选
  · 搜索页带验证码，服务端搜索不可用 → 五个分类本地缓存 + 本地匹配
  · 播放页内嵌 player JSON，url 字段就是 m3u8（master 含相对子清单）
  · 播放域名由本机网络拦截，官网页能取到，盒子上正常网络可播
"""
import re
import sys
import json
import time

try:
    from urllib.parse import quote
except Exception:
    def quote(s, safe=""):
        return str(s)

try:
    import requests as _requests
except Exception:
    _requests = None

# ★ 双壳兼容：OK影视按 base.spider 反射检查，纯独立类会判「加载不出来」
try:
    sys.path.append("..")
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        def getProxyUrl(self):
            return ""

        def localProxy(self, param=None, *args, **kwargs):
            return [404, "text/plain", b"", None]

        def init(self, extend=""):
            return self

        def destroy(self):
            return None


SITE = "https://mtyy8.com"
NAME = "追影"
UA = ("Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 首页导航实测：5 个分类，写死避免每次抓首页
CATS = [
    ("26", "短剧"),
    ("1", "电影"),
    ("2", "电视剧"),
    ("4", "动漫"),
    ("3", "综艺"),
]
CAT_NAMES = dict(CATS)
LABELS = {"26": "短剧", "1": "电影", "2": "电视剧", "4": "动漫", "3": "综艺"}

# 本地排序（站点 by= 参数被忽略，只能在源内排）
SORTS = [("default", "默认"), ("name", "片名A→Z"), ("namer", "片名Z→A")]
_DEF_SORT = "default"

# ★必加②：筛选器候选（key 必须=一级 type_id；『全部』项 v 为空串）
#   站点 by/years/area 参数全部失效（静态快照），只有本地筛选才有意义：
#   类型取自卡片 public-list-subtitle（如「悬疑,惊悚」），排序在源内做。
_CAT_CAND = ["悬疑", "惊悚", "爱情", "喜剧", "动作", "犯罪", "科幻", "剧情", "冒险",
             "战争", "纪录片", "恐怖", "奇幻", "武侠", "家庭", "古装", "青春", "谍战"]
# ★筛选维度只用站点真实存在的字段（实测）：status/quality 来自卡片 public-list-prb（备注），
#   type 来自 public-list-subtitle（站点仅少部分卡片带，有则用）；年份/地区参数站点不提供。
_STS = [("done", "已完结"), ("update", "连载中"), ("other", "其它")]
_QCS = [("1080P", "1080P"), ("HD", "HD"), ("超清", "超清"), ("正片", "正片"), ("4K", "4K")]

PAGE_SIZE = 24
_ALL_CACHE = [0.0, []]
_ALL_TTL = 1800
_PAGE_CACHE = {}
_KW_MEMO = {}
_RAW_CACHE = {}
_ALL_FILE = ""


def _filters():
    # ★必加②(方法级)筛选器：filters 必须是 dict（key=一级 type_id），『全部』项 v 为空串
    """类型候选 = 固定词表 ∪ 缓存里实际出现过的类型词（首屏零网络）"""
    cats, seen = [], set()
    for t in _CAT_CAND:
        if t and t not in seen:
            seen.add(t)
            cats.append({"n": t, "v": t})
    try:
        for _k, _v in list(_RAW_CACHE.items()):
            for _it in (_v[1] or []):
                for _w in str(_it.get("_cat") or "").replace("，", ",").split(","):
                    _w = _w.strip()
                    if _w and _w not in seen and len(_w) <= 6:
                        seen.add(_w)
                        cats.append({"n": _w, "v": _w})
    except Exception:
        pass
    return [
        {"key": "st", "name": "状态", "value": [{"n": "全部", "v": ""}] + [{"n": n, "v": v} for v, n in _STS]},
        {"key": "qc", "name": "清晰度", "value": [{"n": "全部", "v": ""}] + [{"n": n, "v": v} for v, n in _QCS]},
        {"key": "cat", "name": "类型", "value": [{"n": "全部", "v": ""}] + cats[:60]},
        {"key": "rq", "name": "排序", "value": [{"n": n, "v": v} for v, n in SORTS]},
    ]


def _st_of(rem):
    r = str(rem or "")
    if not r:
        return "other"
    if "完结" in r or "集全" in r or "全剧集" in r or re.match(r"^全\d+集$", r):
        return "done"
    if r.startswith("更新至"):
        return "update"
    return "other"


def _qc_of(rem):
    r = str(rem or "").upper()
    for k in ("4K", "1080", "HD", "超清", "正片"):
        if k in r:
            return "4K" if k == "4K" else ("1080P" if k == "1080" else k)
    return ""


FILTERS = [{"key": "rq", "name": "排序", "value": [{"n": n, "v": v} for v, n in SORTS]}]


def _uniesc(s):
    """解 JSON 里的 \\uXXXX 中文串"""
    s = str(s or "")
    if "\\u" not in s:
        return s
    try:
        return json.loads('"%s"' % s.replace('"', '\\"'))
    except Exception:
        return s


def _clean_title(s):
    """SEO 长尾标题洗成片名"""
    s = _uniesc(s)
    s = re.sub(r"<[^>]+>", "", s or "").strip()
    s = s.split("-")[0]
    for w in ("免费观看全集完整版在线观看", "全集完整版在线观看", "在线免费观看高清完整版",
              "高清完整版在线观看", "免费在线观看", "在线观看", "完整版",
              "HD在线", "电影", "电视剧"):
        if s.endswith(w):
            s = s[:-len(w)]
    # ★ 首页 <title> 长尾：动漫吞噬星空在线观看免费观看 → 只留片名
    s = re.sub(r"(?:在线观看|免费观看|免费|高清|完整版|全集|动漫|电影|电视剧|综艺|短剧)+$", "", s).strip()
    for _pre in ("动漫", "电影", "电视剧", "综艺", "短剧"):
        if s.startswith(_pre) and len(s) > len(_pre) + 1:
            s = s[len(_pre):]
            break
    return s.strip() or "未知"


def _get_once(u, hdr, to):
    """单次取页：requests → urllib。两者都可能不遵守 timeout（本机环境），故外层用硬超时。"""
    try:
        if _requests is not None:
            r = _requests.get(u, headers=hdr, timeout=to, allow_redirects=True)
            t = (r.content or b"").decode("utf-8", "ignore")
            if len(t) > 3000:
                return t
    except Exception:
        pass
    try:
        import urllib.request as _ur
        resp = _ur.urlopen(_ur.Request(u, headers=hdr), timeout=to)
        data = resp.read()
        try:
            resp.close()
        except Exception:
            pass
        return data.decode("utf-8", "ignore")
    except Exception:
        return ""


def _hard_get(u, hdr, budget_sec):
    """★ 硬超时：工作线程取页 + join(budget)，到点放弃等待。

    Python 无抢占式超时；本机 urllib/requests 的 socket timeout 实测不遵守
    （urlopen(timeout=3) 实际烧 10.42s），只能靠 join 到点返回。
    卡住的线程是 daemon，随进程退出，不影响壳。
    """
    box = [""]

    def work():
        try:
            # ★ 上限跟随调用方预算（原写死 min(10) 会把 player 的 25s 截成 10s，
            #   慢网/跨网盒子播放页常 10s+ 才回 → 误判空）。首启分类仍传 8s，不受影响。
            box[0] = _get_once(u, hdr, min(40, max(1, budget_sec)))
        except Exception:
            pass

    try:
        import threading as _th
        t = _th.Thread(target=work)
        t.daemon = True
        t.start()
        t.join(budget_sec)
        return box[0]
    except Exception:
        return _get_once(u, hdr, min(10, max(1, budget_sec)))


def _get(url, retry=3, deadline=None, per_try=None):
    """抓页：并发多连接抢快节点（本站唯一可靠的取页方式）。

    ★ 实测两个硬事实：
      ① 站点响应双峰：同一页有时 1.8-5s 回、有时 12-34s 回、有时 45s+ 死；
      ② 本机 requests/urllib 的 socket timeout **不遵守**（timeout=8 实际烧 34.5s），
         所以单连接 join(N) 到点必空，重试也只是再撞一次墙。
    → 唯一有效解：并发开 4 条连接，谁先拿到 >3KB 正文就用谁，轮询立即返回。
    """
    u = str(url or "")
    if not u:
        return ""
    hdr = {"User-Agent": UA, "Referer": SITE,
           "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "*/*"}
    total = 12.0 if deadline is None else max(3.0, deadline / 1000.0)
    # ★实测反思（2026-11-17）：站点点页 1.3~1.9s 就回，旧版固定 6 连接×多轮会在
    #   首次点分类时瞬间打 12~60 条连接，站点反过来把我们都拖到 20s+ → 表现为「分类空白」。
    #   → 默认只开 2 条，只有在大预算（后台预热/播放页）时才加到 4 条。
    workers = 2 if total <= 14.0 else 4
    box = [""]
    try:
        import threading as _th
        lock = _th.Lock()

        def work():
            try:
                t = _get_once(u, hdr, 35)
                if len(t) > 3000:
                    with lock:
                        if not box[0]:
                            box[0] = t
            except Exception:
                pass

        ths = []
        for _i in range(workers):
            th = _th.Thread(target=work)
            th.daemon = True
            th.start()
            ths.append(th)
        t0 = time.time()
        while time.time() - t0 < total:
            if box[0]:
                return box[0]
            time.sleep(0.15)
        return box[0]
    except Exception:
        return _get_once(u, hdr, total)


def _u(u):
    s = str(u or "").strip()
    if not s:
        return ""
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("http"):
        return s
    if s.startswith("/"):
        return SITE + s
    return SITE + "/" + s


def _get_small(u, ref=None, tries=3, to=15):
    """小响应取数（JSON 接口专用）：_get/_get_once 都要求正文 >3KB，
    NBY 的 signed_url / jmurl 只有 100-300B，走这条链路才拿得到。"""
    hdr = {"User-Agent": UA, "Referer": ref or SITE,
           "Accept": "application/json, text/plain, */*"}
    for _ in range(max(1, tries)):
        try:
            if _requests is not None:
                r = _requests.get(u, headers=hdr, timeout=to)
                t = (r.content or b"").decode("utf-8", "ignore")
                if t.strip():
                    return t
        except Exception:
            pass
        try:
            import urllib.request as _ur
            resp = _ur.urlopen(_ur.Request(u, headers=hdr), timeout=to)
            d = resp.read().decode("utf-8", "ignore")
            try:
                resp.close()
            except Exception:
                pass
            if d.strip():
                return d
        except Exception:
            pass
    return ""


def _nby_resolve(enc):
    """NBY 源（泥巴影）取流：播放页给 NBY-XMYAES<hex>|<key>，真链在服务端解。
    实测两步（2026-11-17）：
      ① /static/player/art.php?get_signed_url=1&url=<enc> → {"signed_url":"?url=..&signature=.."}
      ② /static/player/art.php<signed_url> → {"jmurl":"https://play3.nbyjson.top:889/...","urltype":"hls"}
      jmurl 必须带 Referer=art.php?url=<enc> 才给 m3u8（否则返 WAF 页）
    → 返回 (jmurl, referer)；失败返回 ("","")
    """
    enc = str(enc or "")
    if not enc:
        return "", ""
    import urllib.parse as _up
    art = SITE + "/static/player/art.php"
    ref = art + "?url=" + _up.quote(enc, safe="")
    try:
        s1 = _get_small(art + "?get_signed_url=1&url=" + _up.quote(enc, safe=""), ref=ref)
        m = re.search(r'"signed_url"\s*:\s*"([^"]+)"', s1 or "")
        if not m:
            return "", ""
        su = _uniesc(m.group(1)).replace("\\/", "/")
        s2 = _get_small(art + su, ref=ref)
        j = re.search(r'"jmurl"\s*:\s*"([^"]+)"', s2 or "")
        if not j:
            return "", ""
        return _uniesc(j.group(1)).replace("\\/", "/"), ref
    except Exception:
        return "", ""


_CARD = re.compile(
    r'<a[^>]*class="public-list-exp"[^>]*href="/voddetail/(\d+)\.html"'
    r'[^>]*title="([^"]*)"[^>]*>(.*?)</a>', re.S)


def _items(html):
    # ★必加①(方法级)卡片大图四件套：style={'type':'rect','ratio':1.78'} + land=1 + ratio=1.78 + type_name
    """解析卡片：class=public-list-exp 才是真列表（轮播 bg-link 不收）

    ★卡片真实结构（2026-11-17 实测）：
      <div class="public-list-box">
        <a class="public-list-exp" href="/voddetail/ID.html" title="片名">
          <img data-src="封面"> <span class="public-list-prb">HD</span></a>
        <div class="public-list-button">
          <a class="time-title" title="片名">片名</a>
          <div class="public-list-subtitle">悬疑,惊悚</div></div></div>
    → 类型/片名在外层容器里，必须取 public-list-exp 之后的窗口，不能只看 <a> 内部。
    """
    out, seen = [], set()
    h = str(html or "")
    for m in _CARD.finditer(h):
        vid, title, blk = m.group(1), m.group(2), m.group(3)
        if not vid or vid in seen:
            continue
        seen.add(vid)
        win = h[m.end():m.end() + 700]
        pm = (re.search(r'data-src="([^"]+)"', blk)
              or re.search(r'<img[^>]+src="([^"]+)"', blk))
        pic = pm.group(1).strip() if pm else ""
        if pic.startswith("data:") or pic.startswith("about:"):
            pic = ""
        rm = re.search(r'class="public-list-prb[^"]*">([^<]*)<', blk)
        tm = re.search(r'class="time-title[^"]*"[^>]*title="([^"]*)"', win)
        cm = re.search(r'class="public-list-subtitle[^"]*">([^<]*)<', win)
        cat = (cm.group(1).strip() if cm else "").replace("，", ",")
        name = _uniesc((tm.group(1) if tm else "") or title).strip()
        rem = (rm.group(1).strip() if rm else "")
        out.append({
            "vod_id": vid,
            "vod_name": name or vid,
            "vod_pic": _u(pic),
            "vod_remarks": rem,
            "type_name": cat,
            "_cat": cat,
            "_st": _st_of(rem),
            "_qc": _qc_of(rem),
            "_year": "",
            "style": {"type": "rect", "ratio": 1.78},
            "land": 1,
            "ratio": 1.78,
        })
    return out


def _sort_items(items, rq):
    if rq == "name":
        return sorted(items, key=lambda x: str(x.get("vod_name") or ""))
    if rq == "namer":
        return sorted(items, key=lambda x: str(x.get("vod_name") or ""), reverse=True)
    return list(items)


def _flt_of(extend):
    """筛选参数消费（★参数名 filter；兼容 extend/filter 两种传法，键 st/qc/cat/rq）"""
    flt = {"rq": _DEF_SORT, "cat": "", "st": "", "qc": ""}
    if isinstance(extend, dict):
        v = str(extend.get("rq") or "").strip()
        if v in [x[0] for x in SORTS]:
            flt["rq"] = v
        for k in ("cat", "st", "qc"):
            flt[k] = str(extend.get(k) or "").strip()
    return flt


def _apply(items, flt):
    """本地筛选：类型 → 状态 → 清晰度 → 排序（站点侧筛选参数全失效，只能本地做）"""
    arr = items or []
    flt = flt if isinstance(flt, dict) else {}
    cat = flt.get("cat") or ""
    st = flt.get("st") or ""
    qc = flt.get("qc") or ""
    if cat:
        arr = [x for x in arr
               if cat in str(x.get("_cat") or "") or cat in str(x.get("type_name") or "")]
    if st:
        arr = [x for x in arr if str(x.get("_st") or "") == st]
    if qc:
        arr = [x for x in arr if str(x.get("_qc") or "") == qc]
    return _sort_items(arr, flt.get("rq") or _DEF_SORT)


def _rq_of(extend):
    return _flt_of(extend)["rq"]


def _tid_of(tid):
    s = str(tid or "")
    m = re.search(r"/vodtype/(\d+)", s)
    if m:
        return m.group(1)
    m = re.search(r"\d+", s)
    return m.group(0) if m else "1"


def _fetch_plain(url, retry=3):
    """抓 CDN 上的 m3u8：只带 UA，不带站点 Referer（避免被 CDN 判盗链）"""
    for i in range(max(1, retry)):
        h = {"User-Agent": UA, "Accept": "*/*"}
        try:
            if _requests is not None:
                r = _requests.get(url, headers=h, timeout=10)
                t = r.text or ""
                if "#EXTM3U" in t:
                    return t
        except Exception:
            pass
        try:
            import urllib.request as _ur
            resp = _ur.urlopen(_ur.Request(url, headers=h), timeout=10)
            data = resp.read()
            try:
                resp.close()
            except Exception:
                pass
            t = data.decode("utf-8", "ignore")
            if "#EXTM3U" in t:
                return t
        except Exception:
            pass
        if i < retry - 1:
            time.sleep(0.3)
    return ""


_FLAT_CACHE = {}
# ★ sid→源映射每部片都不同（实测：天才游戏 2=MOD/3=BF/4=LZ；金谍行动 2=BF/3=LZ/5=MOD），
#   不能写死"2=MD,3=LZ"。detail 时记下该片全部 sid，player 逐线回退。
_SID_CACHE = {}
_PLAY_URL_CACHE = {}   # (vid,sid) -> (ts, m3u8_url或"")；抓到就缓存，二次点播秒开
_PLAY_TTL = 600

# ★ 分类“没数据”真因：站点分类页实测 2.4s~45s 剧烈波动，旧代码首启只给 8s，
#   撞上超时窗口就交空列表。对策三件套：
#   ① 抓页预算 8s→30s（后台预热给 60s）；② homeContent 后台并发预热 5 分类；
#   ③ 抓到就落盘，重启后先出旧数据，再后台刷新 —— 站点再抽风也不至于空屏。
_PREWARM = [False]
_CACHE_FILE = ""
_ALL_FILE = ""
try:
    import os as _os
    _BASE = ""
    try:
        _os.makedirs("/sdcard/垃圾处理站", exist_ok=True)
    except Exception:
        pass
    for _p in ("/sdcard/垃圾处理站", "/sdcard/Download/垃圾处理站"):
        try:
            if not _os.path.isdir(_p):
                _os.makedirs(_p, exist_ok=True)
            if _os.path.isdir(_p):
                _BASE = _p
                break
        except Exception:
            pass
    if not _BASE:
        _d = _os.path.dirname(_os.path.abspath(__file__))
        _BASE = _d if (_d and _os.path.isdir(_d)) else ""
    if _BASE:
        _CACHE_FILE = _os.path.join(_BASE, "追影__cat.json")
        _ALL_FILE = _os.path.join(_BASE, "追影__all.json")
except Exception:
    _CACHE_FILE = ""
    _ALL_FILE = ""

try:
    import threading as _threading
    _DISK_LOCK = _threading.Lock()
except Exception:
    _DISK_LOCK = None


def _disk_load():
    """重启后先读盘：站点可能几十分钟抓不动，有旧列表总比空屏强"""
    if not _CACHE_FILE:
        return
    try:
        import os as _os
        if not _os.path.exists(_CACHE_FILE):
            return
        f = open(_CACHE_FILE, "r", encoding="utf-8")
        d = json.load(f)
        f.close()
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[1], list) and v[1]:
                    _RAW_CACHE[str(k)] = (float(v[0]), v[1])
    except Exception:
        pass


def _disk_save():
    if not _CACHE_FILE:
        return
    try:
        d = {}
        for k, v in list(_RAW_CACHE.items()):
            if v and v[1]:
                d[str(k)] = [v[0], v[1]]
        if not d:
            return
        if _DISK_LOCK is not None:
            _DISK_LOCK.acquire()
        try:
            f = open(_CACHE_FILE, "w", encoding="utf-8")
            json.dump(d, f, ensure_ascii=False)
            f.close()
        finally:
            if _DISK_LOCK is not None:
                _DISK_LOCK.release()
    except Exception:
        pass


def _all_disk_load():
    """全站搜索索引落盘：重启后第一次搜索就能秒回（站点限流也不影响）"""
    if not _ALL_FILE:
        return
    try:
        import os as _os
        if not _os.path.exists(_ALL_FILE):
            return
        f = open(_ALL_FILE, "r", encoding="utf-8")
        d = json.load(f)
        f.close()
        if isinstance(d, list) and d:
            _ALL_CACHE[0] = 0.0
            _ALL_CACHE[1] = [x for x in d if isinstance(x, dict) and x.get("vod_id")]
    except Exception:
        pass


def _all_disk_save():
    if not _ALL_FILE or not _ALL_CACHE[1]:
        return
    try:
        if _DISK_LOCK is not None:
            _DISK_LOCK.acquire()
        try:
            f = open(_ALL_FILE, "w", encoding="utf-8")
            json.dump(_ALL_CACHE[1], f, ensure_ascii=False)
            f.close()
        finally:
            if _DISK_LOCK is not None:
                _DISK_LOCK.release()
    except Exception:
        pass


def _fetch_cat(t, rounds=2, deadline=12000):
    """★抓单个分类页（带缓存回填）。这是「分类空白」的唯一抓取入口：
    默认 2 轮 × 12s、每轮 2 连接；实测站点 1.3~1.9s 就回，够用且不触发限速。
    """
    t = str(t or "")
    rc = _RAW_CACHE.get(t)
    if rc and rc[1]:
        return rc[1]
    arr = []
    for _rd in range(max(1, rounds)):
        arr = _items(_get("%s/vodtype/%s.html" % (SITE, t), retry=2, deadline=deadline))
        if arr:
            break
    if not arr:
        for _host in ("https://www.mtyy8.com",):
            try:
                arr = _items(_get("%s/vodtype/%s.html" % (_host, t), retry=1, deadline=deadline))
            except Exception:
                arr = []
            if arr:
                break
    if arr:
        _cn = CAT_NAMES.get(t, "")
        if _cn:
            for _it in arr:
                if not _it.get("type_name"):
                    _it["type_name"] = _cn
        _RAW_CACHE[t] = (time.time(), arr)
        _disk_save()
    return arr


def _prewarm():
    """后台并发抓 5 个分类页；站点单页常 25s+，后台跑不阻塞壳首屏"""
    try:
        from concurrent.futures import ThreadPoolExecutor

        def grab(t):
            rc = _RAW_CACHE.get(t)
            if rc and rc[1] and time.time() - rc[0] < 1800:
                return
            arr = _items(_get("%s/vodtype/%s.html" % (SITE, t), retry=1, deadline=60000))
            if arr:
                _RAW_CACHE[t] = (time.time(), arr)

        # 每类 _get 已并发 6 连接，这里再并发 2 类即可，避免连接爆炸
        pool = ThreadPoolExecutor(max_workers=2)
        futs = [pool.submit(grab, t) for t, _n in CATS]
        for f in futs:
            try:
                f.result(timeout=80)
            except Exception:
                pass
        pool.shutdown(wait=False)
        _disk_save()
    except Exception:
        pass


def _refresh_async(t):
    """旧数据先给用户看，后台静默换新（stale-while-revalidate）"""
    def _w():
        try:
            arr = _items(_get("%s/vodtype/%s.html" % (SITE, t),
                              retry=6, deadline=70000, per_try=12))
            if arr:
                _RAW_CACHE[t] = (time.time(), arr)
                _disk_save()
        except Exception:
            pass
    try:
        th = _threading.Thread(target=_w)
        th.daemon = True
        th.start()
    except Exception:
        pass


_disk_load()   # 模块加载即恢复上次分类列表
_all_disk_load()   # 同时恢复全站搜索索引（搜索秒回）


def _flatten_master(url):
    """master 里是相对子清单 → 展开成绝对 URL，避免壳用错解析基准。

    本站实测：master 第一行是 `#EXT-X-STREAM-INF`，下一行 `1030kb/hls/index.m3u8`
    是**相对路径**；壳若按站点根做基准会请求 /1030kb/... 而 404。
    子清单里的分片本身是绝对 URL，所以只要把子清单绝对化，壳就能直接播。
    """
    u = str(url or "").strip()
    if "m3u8" not in u.lower():
        return u
    hit = _FLAT_CACHE.get(u)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    txt = _fetch_plain(u, retry=2)
    if "#EXT-X-STREAM-INF" not in txt:
        return u
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            from urllib.parse import urljoin
            out = urljoin(u, s)
            res = out if out.startswith("http") else u
        except Exception:
            res = s if s.startswith("http") else u
        if len(_FLAT_CACHE) > 60:
            _FLAT_CACHE.clear()
        _FLAT_CACHE[u] = (time.time(), res)
        return res
    return u


def _seg_ok(m3u8_url):
    """首分片探活：取 m3u8 第一行分片，Range 前 1KB，200/206 且有数据才算真可播。
    master 已在 _flatten_master 展开成子清单，这里拿到的就是含 #EXTINF 的播放列表。
    """
    u = str(m3u8_url or "")
    if "m3u8" not in u.lower():
        return False
    try:
        txt = _fetch_plain(u, retry=1)
        seg = ""
        for ln in txt.splitlines():
            s = ln.strip()
            if s and not s.startswith("#"):
                seg = s
                break
        if not seg:
            return False  # 空列表不判活
        from urllib.parse import urljoin
        full = urljoin(u, seg)
        for h in ({"User-Agent": UA, "Range": "bytes=0-1023"}, {"User-Agent": UA}):
            try:
                if _requests is not None:
                    r = _requests.get(full, headers=h, timeout=8)
                    if r.status_code in (200, 206) and len(r.content) > 0:
                        return True
                    if r.status_code in (403, 404, 410):
                        return False
            except Exception:
                pass
            try:
                import urllib.request as _ur
                resp = _ur.urlopen(_ur.Request(full, headers=h), timeout=8)
                data = resp.read(1024)
                try:
                    resp.close()
                except Exception:
                    pass
                if data:
                    return True
            except Exception:
                pass
    except Exception:
        pass
    return False


class Spider(_BaseSpider):
    def __init__(self, *args, **kwargs):
        try:
            _BaseSpider.__init__(self)
        except Exception:
            pass
        self.name = NAME
        self.site = SITE
        self.header = {"User-Agent": UA, "Referer": SITE + "/",
                       "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "*/*"}
        self.headers = self.header
        try:
            _sess = _requests.Session() if _requests is not None else None
        except Exception:
            _sess = None
        self.s = self.session = self.sess = _sess
        self._extend = {}
        self.use_proxy = False

    def init(self, extend=""):
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass
        return self

    def action(self, action):
        return ""

    def destroy(self):
        return None

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return any(x in u for x in (".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi"))

    def manualVideoCheck(self):
        return False

    def _play_hdr(self):
        return {"User-Agent": UA}

    def homeContent(self, filter=None):
        # ★必加②：filters 必须是 dict（key=一级 type_id）；写成 list 会让壳整份结果解析失败
        # ★必检④(方法级)分类覆盖度：5 类全量上线 + LABELS 中文名兜底，不缩分类
        cats = [{"type_id": t, "type_name": LABELS.get(t, n), "land": 1, "ratio": 1.78} for t, n in CATS]
        flts = _filters()
        filters = {}
        for c in cats:
            filters[c["type_id"]] = flts
        if not _PREWARM[0]:
            _PREWARM[0] = True
            try:
                th = _threading.Thread(target=_prewarm)
                th.daemon = True
                th.start()
            except Exception:
                pass
        return {"class": cats, "filters": filters, "list": self._home_items()}

    def homeVideoContent(self):
        # ★分类空白根因修复：缓存空时同步抓一个分类（预算 6s），宁可慢一点也不给空屏
        return {"list": self._home_items()}

    def _home_items(self):
        for t in ("1", "26", "2", "3", "4"):
            rc = _RAW_CACHE.get(t)
            if rc and rc[1]:
                if time.time() - rc[0] >= 1800:
                    _refresh_async(t)
                return rc[1][:PAGE_SIZE]
        arr = _fetch_cat("1", rounds=1, deadline=6000)
        if not arr:
            arr = _fetch_cat("26", rounds=1, deadline=6000)
        return arr[:PAGE_SIZE]

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        # ★必检①：page/pagecount/limit/total 四件齐全 + 本地真分页
        #   （站点 /vodtype/{tid}-{p}.html 与第 1 页 ID 完全相同，分页参数全失效）
        # ★必检①(方法级)翻页四件齐全：page/pagecount/limit/total 真值，禁 999 伪分页
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        t = _tid_of(tid)
        src = extend if isinstance(extend, dict) else (filter if isinstance(filter, dict) else {})
        flt = _flt_of(src)
        items = _apply(self._cat_items(t), flt)
        total = len(items)
        pc = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if p > pc:
            return {"list": [], "page": p, "pagecount": pc, "limit": PAGE_SIZE, "total": total}
        st = (p - 1) * PAGE_SIZE
        return {"list": items[st:st + PAGE_SIZE], "page": p, "pagecount": pc,
                "limit": PAGE_SIZE, "total": total}

    def _cat_items(self, t):
        # 唯一抓取入口：有缓存直接给（旧数据也比空屏强），过期后台静默刷新
        rc = _RAW_CACHE.get(t)
        if rc and rc[1]:
            _cn0 = CAT_NAMES.get(t, "")
            if _cn0:
                for _it in rc[1]:
                    if not _it.get("type_name"):
                        _it["type_name"] = _cn0
            if time.time() - rc[0] >= 1800:
                _refresh_async(t)
            return rc[1]
        arr = _fetch_cat(t, rounds=2, deadline=12000)
        if not arr:
            # ★站点抽风兜底：任一类有缓存就先用，绝不给空屏
            for _t, _n in CATS:
                rc2 = _RAW_CACHE.get(_t)
                if rc2 and rc2[1]:
                    return rc2[1]
        return arr

    def _all_items(self):
        # 全站索引：内存 → 落盘 → 并发抓（2 并发，避免限速）
        now = time.time()
        if _ALL_CACHE[1] and now - _ALL_CACHE[0] < _ALL_TTL:
            return _ALL_CACHE[1]
        if not _ALL_CACHE[1]:
            _all_disk_load()
        seen, out = set(), []
        try:
            from concurrent.futures import ThreadPoolExecutor
            pool = ThreadPoolExecutor(max_workers=2)
            futs = [pool.submit(_fetch_cat, t, 1, 12000) for t, _n in CATS]
            for f in futs:
                try:
                    arr = f.result(timeout=25)
                except Exception:
                    arr = []
                for it in (arr or []):
                    vid = it.get("vod_id")
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    out.append(it)
            pool.shutdown(wait=False)
        except Exception:
            for t, _n in CATS:
                for it in (_fetch_cat(t, 1, 12000) or []):
                    if it.get("vod_id") not in seen:
                        seen.add(it["vod_id"])
                        out.append(it)
        if out:
            _ALL_CACHE[0] = now
            _ALL_CACHE[1] = out
            _all_disk_save()
        return out or (_ALL_CACHE[1] or [])

    def _norm_kw(self, s):
        return re.sub(r"[\s·:：,，.。!！?？\-_/\\|()（）\[\]【】《》\"']+", "",
                      str(s or "")).lower()

    def searchContent(self, key, quick=False, pg="1"):
        # ★必加③：关键词归一化（去空格/标点）+ 多词 AND + 片名/类型双字段匹配 + 真分页
        #   （站点 /vodsearch/ 需图形验证码 /verify/index.html，服务端搜索不可用 → 本地索引）
        # ★必加③(方法级)搜索：quote() 编码出稳定缓存键，120s 内重复搜索直接切片回吐
        kw = str(key or "").strip()
        if not kw:
            return {"list": [], "page": 1, "pagecount": 1, "limit": PAGE_SIZE, "total": 0}
        try:
            p = max(1, int(pg or 1))
        except Exception:
            p = 1
        qk = quote(kw, safe="")
        memo = _KW_MEMO.get(qk)
        if memo and time.time() - memo[0] < 120:
            hits = memo[1]
        else:
            words = [w for w in (self._norm_kw(x) for x in re.split(r"[\s,，+|/]+", kw)) if w]
            if not words:
                words = [self._norm_kw(kw)]
            hits = []
            for x in (self._all_items() or []):
                hay = (self._norm_kw(x.get("vod_name")) + "|" + self._norm_kw(x.get("_cat"))
                       + "|" + self._norm_kw(x.get("type_name")))
                if all(w in hay for w in words):
                    hits.append(x)
            _KW_MEMO[qk] = (time.time(), hits)
        total = len(hits)
        pc = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if p > pc:
            return {"list": [], "page": p, "pagecount": pc, "limit": PAGE_SIZE, "total": total}
        st = (p - 1) * PAGE_SIZE
        return {"list": hits[st:st + PAGE_SIZE], "page": p, "pagecount": pc,
                "limit": PAGE_SIZE, "total": total}

    def _detail_id(self, raw):
        s = str(raw or "").strip()
        m = re.search(r"/voddetail/(\d+)", s)
        return m.group(1) if m else (s if s.isdigit() else "")

    def detailContent(self, ids, *args, **kwargs):
        # ★必检②(方法级)多线路全解析：逐 sid 收 /vodplay/{vid}-{sid}-1.html，死线排后不剔除
        raw = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = self._detail_id(raw)
        if not vid:
            return {"list": []}
        try:
            html = ""
            for _du in ("%s/voddetail/%s.html" % (SITE, vid),
                        "https://www.mtyy8.com/voddetail/%s.html" % vid,
                        "%s/voddetail/%s.html" % (SITE, vid)):
                for _at in range(2):
                    try:
                        html = _get(_du, retry=2, deadline=15000)
                    except Exception:
                        html = ""
                    if html:
                        break
                if html:
                    break
        except Exception:
            return {"list": []}
        if not html:
            return {"list": []}

        tm = re.search(r'"vod_title"\s*:\s*"([^"]+)"', html)
        title = _clean_title(_uniesc(tm.group(1))) if tm else ""
        if not title:
            hm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            title = _clean_title(hm.group(1)) if hm else _clean_title(
                (re.search(r"<title[^>]*>([^<]+)</title>", html) or [None, vid])[1])

        # 主封面在 <div class="this-pic-bj" style="background-image:url(...)">，
        # 不是 <img>（页里的 img 全是「相关推荐」）
        pm = (re.search(r'class="this-pic-bj"[^>]*background-image\s*:\s*url\([\'"]?([^\'")]+)', html)
              or re.search(r'"vod_pic_thumb"\s*:\s*"([^"]+)"', html)
              or re.search(r'property="og:image"\s+content="([^"]+)"', html))
        pic = _u(_uniesc(pm.group(1)).replace("\\/", "/")) if pm else ""

        dm = (re.search(r'<div[^>]+class="[^"]*(?:vod_content|desc|intro)[^"]*"[^>]*>'
                        r'([\s\S]{10,1500}?)</div>', html)
              or re.search(r'property="og:description"\s+content="([^"]+)"', html))
        desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", _uniesc(dm.group(1)))).strip() if dm else ""

        # 线路 + 集数（实测 2026-11-17）：
        #   <div class="anthology-tab"> 里 <a class="swiper-slide">NB源<span class="badge">8</span></a>=线路名
        #   <div class="anthology-list-box"> 按 tab 顺序给该线路全部集：
        #     剧集 <a class="hide" href="/vodplay/{vid}-{sid}-{nid}.html">01</a>
        #     电影 <a class="hide" href="/vodplay/{vid}-{sid}-1.html">1080P</a>
        #   → 详情页一次就把「线路名 + 全部集数」拿全，不必再抓播放页。
        tabs = []
        _tb = re.search(r'class="anthology-tab[^"]*"(.*?)class="anthology-list', html, re.S)
        if _tb:
            for a in re.finditer(r'<a[^>]*class="swiper-slide"[^>]*>(.*?)</a>', _tb.group(1), re.S):
                nm = re.sub(r"&[a-zA-Z]+;|&#\d+;", "", re.sub(r"<span[^>]*badge[^>]*>.*?</span>", "", a.group(1), flags=re.S))
                nm = re.sub(r"<[^>]+>", "", nm)
                nm = re.sub(r"\s+", "", nm)
                if nm:
                    tabs.append(nm)
        lines, _seen_sid = [], set()
        for _blk in re.findall(r'class="anthology-list-box[^"]*"(.*?)</ul>', html, re.S):
            eps, sid0 = [], ""
            for em in re.finditer(r'href="(/vodplay/%s-(\d+)-(\d+)\.html)"[^>]*>([^<]*)<'
                                  % re.escape(vid), _blk):
                path, sid, nid, lab = em.group(1), em.group(2), em.group(3), em.group(4)
                if not sid0:
                    sid0 = sid
                nm = re.sub(r"&[a-zA-Z]+;|&#\d+;", "", lab).strip() or ("第%s集" % nid)
                eps.append((nm, path))
            if eps and sid0 not in _seen_sid:
                _seen_sid.add(sid0)
                lines.append((sid0, eps))
        if lines:
            sids = [s for s, _e in lines]
            names = "$$$".join((tabs[i] if i < len(tabs) and tabs[i] else ("线路%s" % s))
                               for i, (s, _e) in enumerate(lines))
            urls = "$$$".join("#".join("%s$%s" % (nm, path) for nm, path in eps) for _s, eps in lines)
        else:
            # 回退：页面无 anthology 容器时，只挂每线第 1 集（旧行为，保证不空）
            sids, _seen = [], set()
            for sm in re.finditer(r'/vodplay/%s-(\d+)-1\.html' % re.escape(vid), html):
                if sm.group(1) not in _seen:
                    _seen.add(sm.group(1))
                    sids.append(sm.group(1))
            if not sids:
                sids = ["1"]
            names = "$$$".join("线路%s" % s for s in sids)
            urls = "$$$".join("正片$/vodplay/%s-%s-1.html" % (vid, s) for s in sids)
        # ★ sid→源映射每部片都不同，写死必漏线路 → 挂全部 sid，由 playerContent 逐线实测回退
        _SID_CACHE[vid] = (time.time(), list(sids))
        if len(_SID_CACHE) > 400:
            _SID_CACHE.clear()

        ym = (re.search(r'年份：</em>\s*([^<]+)', html)
              or re.search(r'"vod_year"\s*:\s*"?(\d{4})', html))
        # ★ public-prt 是豆瓣评分（实测 7.2），不是年份；年份/地区在「年份：/地区：」行里
        arm = (re.search(r'地区：</em>\s*([^<]+)', html)
               or re.search(r'"vod_area"\s*:\s*"([^"]+)"', html))
        scm = re.search(r'class="public-prt[^"]*">([^<]*)<', html)
        # ★ 分类名优先取详情页导航里 class="current" 的那个（准确）；取不到再反查分类缓存
        tname = ""
        for _am in re.finditer(r'<a[^>]*href="/vodtype/(\d+)\.html"[^>]*>(.*?)</a>', html, re.S):
            _tag = _am.group(0)
            if "current" in _tag[:max(0, _tag.find(">"))]:
                _lab = re.sub(r"<[^>]+>", "", _am.group(2)).strip()
                if _lab:
                    tname = _lab
                    break
        if not tname:
            for _t, _n in CATS:
                _rc = _RAW_CACHE.get(_t)
                if _rc and any(str(x.get("vod_id")) == vid for x in _rc[1]):
                    tname = _n
                    break
        return {"list": [{
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": pic,
            "type_name": tname,
            "vod_year": ym.group(1).strip() if ym else "",
            "vod_area": arm.group(1).strip() if arm else "",
            "vod_actor": "",
            "vod_director": "",
            "vod_remarks": ((scm.group(1).strip() + "分") if scm else ""),
            "vod_content": desc or ("%s · 麦田影院在线播放" % title),
            "vod_play_from": names,
            "vod_play_url": urls,
            "style": {"type": "rect", "ratio": 1.78},
            "land": 1,
            "ratio": 1.78,
        }]}

    def playerContent(self, flag, ids, vipFlags=None, *args, **kwargs):
        # ★必检③(方法级)播放契约三键 parse/url/header，逐线并发探测，不通换线不带死线
        url = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        url = str(url or "").strip()
        if "$$$" in url:
            url = url.split("$$$")[0]
        if "$" in url:
            url = url.split("$")[-1]
        if "#" in url:
            url = url.split("#")[0]
        url = _u(url)
        low = url.lower()
        if low.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) and "vodplay" not in low:
            return {"parse": 0, "url": url, "header": {"User-Agent": UA}}
        if "vodplay" not in low:
            return {"parse": 0, "url": "", "header": {"User-Agent": UA}}
        # ★ 逐线回退：站点单页常 30s，串行逐条会超时 → 并发试探全部 sid，谁先活给谁
        vm = re.search(r'/vodplay/(\d+)-(\d+)-(\d+)', url)
        nid = "1"
        if vm:
            vid, cur, nid = vm.group(1), vm.group(2), vm.group(3)
            hit = _SID_CACHE.get(vid)
            sids = list(hit[1]) if hit and time.time() - hit[0] < _PLAY_TTL else []
            if not sids:
                sids = ["1", "2", "3", "4", "5"]
            order = [cur] + [s for s in sids if s != cur]
        else:
            vid, cur, order = "", "", [""]
        _nid = nid or "1"

        def _try(sid):
            key = (vid, sid, _nid)
            cached = _PLAY_URL_CACHE.get(key)
            if cached and time.time() - cached[0] < _PLAY_TTL:
                return (cached[1], cached[2] if len(cached) > 2 else "")
            # ★换线必须保留原始集号 nid，否则会静默播成第 1 集（实测踩坑）
            pu = url if not sid else "%s/vodplay/%s-%s-%s.html" % (SITE, vid, sid, _nid)
            html = _get(pu, retry=2, deadline=25000)
            found, ref, enc = "", "", ""
            for m in re.finditer(r'"url"\s*:\s*"([^"]+)"', html):
                u = _uniesc(m.group(1)).replace("\\/", "/")
                if "XMYAES" in u or u.startswith("NBY-"):
                    enc = u
                    continue
                if "m3u8" in u.lower() or u.lower().endswith((".mp4", ".flv")):
                    found = u
                    break
            if not found and enc:
                found, ref = _nby_resolve(enc)
            if not found:
                m = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', html)
                if m:
                    found = m.group(1)
            found = _u(found)
            if found and "m3u8" in found.lower() and not ref:
                found = _flatten_master(found)
                if found and not _seg_ok(found):
                    found = ""             # 首分片死 → 判该线不可用
            if not found:
                found, ref = "", ""
            if len(_PLAY_URL_CACHE) > 500:
                _PLAY_URL_CACHE.clear()
            _PLAY_URL_CACHE[key] = (time.time(), found, ref)
            return (found, ref)

        # 当前线路优先同步试（缓存命中则秒回）；失败再并发其它线路
        best, bref = _try(cur) if cur else ("", "")
        if not best and len(order) > 1:
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                pool = ThreadPoolExecutor(max_workers=min(4, len(order) - 1))
                futs = {pool.submit(_try, s): s for s in order if s != cur}
                for f in as_completed(futs, timeout=35):
                    try:
                        v, r2 = f.result()
                    except Exception:
                        v, r2 = "", ""
                    if v:
                        best, bref = v, r2
                        break
                pool.shutdown(wait=False)
            except Exception:
                for s in order:
                    if s != cur:
                        v, r2 = _try(s)
                        if v:
                            best, bref = v, r2
                            break
        hdr = {"User-Agent": UA}
        if bref:
            hdr["Referer"] = bref
        return {"parse": 0, "url": best, "header": hdr}

    def localProxy(self, param=None, *args, **kwargs):
        u = param.get("url", "") if isinstance(param, dict) else ""
        if not u:
            return [403, "text/plain", b"", None]
        u = _u(u)
        hdr = dict(self.header)
        try:
            if _requests is not None:
                r = _requests.get(u, headers=hdr, timeout=10)
                return [200, r.headers.get("Content-Type", "application/octet-stream"), r.content, None]
            import urllib.request as _ur
            resp = _ur.urlopen(_ur.Request(u, headers=hdr), timeout=10)
            data = resp.read()
            ct = resp.headers.get("Content-Type", "application/octet-stream")
            try:
                resp.close()
            except Exception:
                pass
            return [200, ct, data, None]
        except Exception:
            return [403, "text/plain", b"", None]
