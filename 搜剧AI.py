# @tvbox-source
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜剧AI (souju3.ai / souju.ai) 爬虫 - TVBox / PeekPro 影视壳 Spider 插件
支持: 首页推荐、分类浏览+筛选、榜单、搜索、详情、播放直链解析

接口说明(逆向自前端 bundle):
  1) 所有 /v1/* 接口都需要请求签名, 算法为:
       HMAC-SHA256(key, "METHOD\\npath+query\\n时间戳(ms)\\n随机串")
     其中 key 为前端写死的十六进制字符串(见 SIGN_KEY), 随机串为 16 字节 hex。
     请求头: x-ai-movie-timestamp / x-ai-movie-nonce / x-ai-movie-signature
  2) 播放需要会话: POST /v1/users/anonymous 创建匿名用户(免登录, 返回 ai_movie_session cookie)
  3) 播放链路: 详情 episode.token -> GET /v1/playback/resolve/{token}?view=compact
     -> 得到 line_options(每项 url 为 resolve://<票据>)
     -> POST /v1/playback/resolve-line?view=compact body {"ticket": "<去掉 resolve:// 的票据>"}
     -> 返回 line.url 即真实 mp4/m3u8 直链
"""

import os
import re
import sys
import json
import time
import hmac
import base64
import binascii
import hashlib
import logging
import urllib.parse

import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class Spider(BaseSpider):
    """搜剧AI 爬虫"""

    # 域名链: souju.ai 为永久域名, 其余为编号备用域名(站点换域名时自动切换)
    BASES = ("https://souju.ai", "https://souju3.ai", "https://souju2.ai",
             "https://souju1.ai", "https://souju4.ai")
    # 失效域名的冷却时长(秒): 期间不再尝试, 避免每个请求都卡在同一个死域名上
    BASE_BAN_TTL = 300
    # 前端写死的签名密钥(直接以字符串字节作为 HMAC key, 非 hex 解码)
    SIGN_KEY = "f39d73aa7a6426203cdee1ef17b31d3b7ea8c23f4c59c62a3a8aa0f39ee5e79d"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

    PAGE_SIZE = 20
    MAX_RETRY = 3
    # 详情页线路组总体积上限(超出则裁剪低优先级的第三方线路, 保证长剧详情不臃肿)
    MAX_DETAIL_BYTES = 300 * 1024

    # 服务端限流: 429=频率超限(无间隔连发约 12 次触发), 402=配额耗尽
    # 二者都是网关级限制, 换域名无效(实测 5 个域名同时返回 402), 只能退避重试
    RATE_CODES = (429, 402)
    RATE_WAIT = 2.0          # 首次退避秒数
    RATE_WAIT_MAX = 10.0     # 退避上限
    # 播放类接口串行节流: 实测间隔 0.2s 起开始出现 429, 保持 0.6s 以上可稳定
    PLAY_MIN_GAP = 0.6

    # ---------- 分类 ----------
    # type_id 前缀: k_ 普通类型, h_ 榜单(hot_list_key), t_ trending
    KINDS = [
        ("k_movie", "电影", "movie"),
        ("k_series", "电视剧", "series"),
        ("k_anime", "动漫", "anime"),
        ("k_variety", "综艺", "variety"),
        ("k_documentary", "纪录片", "documentary"),
        ("k_sports", "体育", "sports"),
        ("k_short_drama", "短剧", "short_drama"),
        ("t_day", "全部热播", None),
        ("h_movie_high_score", "高分电影", "movie_high_score"),
        ("h_movie_hot", "电影热播", "movie_hot"),
        ("h_movie_nowplaying", "院线热映", "movie_nowplaying"),
        ("h_tv_korean", "韩剧榜", "tv_korean"),
        ("h_tv_japanese", "日剧榜", "tv_japanese"),
        ("h_tv_american", "美剧榜", "tv_american"),
        ("h_tv_domestic", "国产剧榜", "tv_domestic"),
    ]

    # 各类型的筛选“类型”词条(取自站内实际数据样本)
    GENRES = {
        "movie": ["动作", "喜剧", "爱情", "科幻", "恐怖", "惊悚", "剧情", "犯罪",
                  "悬疑", "冒险", "奇幻", "战争", "历史", "古装", "动画"],
        "series": ["国产剧", "韩剧", "美剧", "日剧", "港剧", "台剧", "海外剧",
                   "剧情", "爱情", "悬疑", "犯罪", "古装", "奇幻", "喜剧", "家庭"],
        "anime": ["国产动漫", "日韩动漫", "欧美动漫", "热血", "搞笑", "奇幻",
                  "冒险", "战斗", "科幻", "悬疑", "恋爱", "竞技", "日常"],
        "variety": ["真人秀", "脱口秀", "音乐", "晚会", "情感", "文化",
                    "美食", "旅行", "亲子", "竞技", "喜剧"],
        "documentary": ["历史", "传记", "犯罪", "自然", "科技", "美食", "军事", "运动"],
        "short_drama": ["现代都市", "脑洞悬疑", "女频恋爱", "现代言情", "反转爽剧",
                        "重生民国", "年代穿越", "言情总裁", "古装仙侠", "AI漫剧"],
    }

    AREAS = ["中国大陆", "中国香港", "中国台湾", "美国", "日本", "韩国", "英国",
             "法国", "德国", "意大利", "西班牙", "印度", "泰国", "加拿大", "澳大利亚"]
    YEARS = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018",
             "2017", "2016", "2015"]

    # 过滤小说/非视频条目
    NOVEL_WORDS = ("小说", "漫画原著", "电子书")

    # ---------- 封面图本地代理 ----------
    DEFAULT_PROXY_PORT = 9978
    # siteKey 探测失败时的兜底值: 必须避开真实站点 key(内置"源管家"就占用 local),
    # 否则代理会路由到别的爬虫实例返回 404, 封面全部变成灰底占位图
    LOCAL_SITE_KEY = "local_py_auto_last"

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.UA})
        self._session_ready = False
        self._base = ""          # 当前可用域名(探测成功后缓存)
        self._base_ban = {}      # 失效域名 -> 解禁时间戳
        self._proxy_flag = None
        self._proxy_port = 0
        self._site_key = ""
        self._pic_lock = None
        self._pic_cache = {}
        self._pic_session = None
        self._play_lock = None   # 播放类请求串行锁(并发会叠加触发限流)
        self._last_play_ts = 0.0
        self._line_cache = {}    # 票据 -> 真实直链(同一集重复播放不再请求接口)
        self._rate_limited = False       # 本次 _api 是否因限流失败
        self._last_rate_limited = False  # 最近一次解析线路是否因限流失败

    def init(self, extend=""):
        """初始化"""
        pass

    def getName(self):
        return "搜剧AI"

    # ==================== 签名与请求 ====================
    @staticmethod
    def _nonce():
        """16 字节随机串的 hex 形式"""
        try:
            return binascii.hexlify(os.urandom(16)).decode()
        except Exception:
            return hashlib.md5(str(time.time()).encode()).hexdigest()

    def _signed_headers(self, method, path):
        """按前端算法生成签名头"""
        ts = str(int(time.time() * 1000))
        nonce = self._nonce()
        msg = "%s\n%s\n%s\n%s" % (method.upper(), path, ts, nonce)
        sig = hmac.new(self.SIGN_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-ai-movie-timestamp": ts,
            "x-ai-movie-nonce": nonce,
            "x-ai-movie-signature": sig,
        }

    def _bases_order(self):
        """候选域名顺序: 已探测可用的域名优先, 跳过冷却中的失效域名"""
        now = time.time()
        live = [b for b in self.BASES if self._base_ban.get(b, 0) <= now]
        if not live:
            # 全部处于冷却: 清空冷尊重置, 避免彻底无域名可用
            self._base_ban.clear()
            live = list(self.BASES)
        if self._base and self._base in live:
            live.remove(self._base)
            live.insert(0, self._base)
        return live

    def _use_base(self, base):
        """记住当前可用域名; 换域名后匿名会话需重建(cookie 按域名隔离)"""
        if base != self._base:
            self._base = base
            self._session_ready = False
        self._base_ban.pop(base, None)

    def _api(self, path, method="GET", body=None):
        """带签名的接口请求

        - 单个域名最多重试 MAX_RETRY 次(每次重新签名, 避免时间戳过期)
        - 域名失效(网络异常/非业务态错误码)时自动切换下一个备用域名并加冷却
        - 限流(429/402)属网关级限制, 换域名无效, 只在本域名退避重试, 不污染域名冷却
        - 业务态错误(400/401/403/404/410)说明服务端是通的, 直接返回不再重试
        """
        method = method.upper()
        self._rate_limited = False
        last_err = None
        for base in self._bases_order():
            for attempt in range(self.MAX_RETRY):
                try:
                    headers = self._signed_headers(method, path)
                    if method == "GET":
                        rsp = self.session.get(base + path, headers=headers, timeout=15)
                    else:
                        rsp = self.session.post(base + path, data=json.dumps(body or {}),
                                                headers=headers, timeout=15)
                    code = rsp.status_code
                    if code in (200, 201):
                        try:
                            data = rsp.json()
                        except Exception as e:
                            last_err = e
                            time.sleep(0.3)
                            continue
                        self._use_base(base)
                        return data
                    if code in self.RATE_CODES:
                        # 限流: 同一后端换域名无用, 退避后重试; 仍失败则放弃本次请求
                        self._rate_limited = True
                        last_err = "HTTP %s" % code
                        if attempt >= self.MAX_RETRY - 1:
                            logger.warning("接口持续限流 HTTP %s, 放弃: %s", code, path[:120])
                            return None
                        wait = min(self.RATE_WAIT * (attempt + 1), self.RATE_WAIT_MAX)
                        logger.warning("接口限流 HTTP %s, %.1fs 后重试: %s", code, wait, path[:120])
                        time.sleep(wait)
                        continue
                    if code in (400, 401, 403, 404, 410):
                        logger.warning("业务错误 %s %s: HTTP %s", method, path[:120], code)
                        return None
                    last_err = "HTTP %s" % code
                except Exception as e:
                    last_err = e
                time.sleep(0.3)
            # 本域名整体不可用 -> 冷却并切换下一个备用域名
            self._base_ban[base] = time.time() + self.BASE_BAN_TTL
            logger.warning("域名不可用, 切换备用: %s (%s)", base, last_err)
        logger.warning("请求失败 %s %s: %s", method, path[:120], last_err)
        return None

    def _ensure_session(self):
        """播放需要匿名会话(免登录); 进程内只创建一次"""
        if self._session_ready:
            return True
        d = self._api("/v1/users/anonymous", "POST", {})
        if isinstance(d, dict) and d.get("user"):
            self._session_ready = True
            return True
        return False

    # ==================== 工具 ====================
    @staticmethod
    def _page_of(pg):
        try:
            n = int(pg)
            return n if n > 0 else 1
        except Exception:
            return 1

    @staticmethod
    def _pagecount(items, page):
        """滑到底自动加载: 有数据给 9999, 空页/失败收敛到当前页"""
        return 9999 if items else page

    @staticmethod
    def _b64e(obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def _b64d(text):
        s = str(text or "").strip()
        s += "=" * (-len(s) % 4)
        try:
            return json.loads(base64.urlsafe_b64decode(s.encode()).decode("utf-8"))
        except Exception:
            return {}

    def _is_novel(self, card):
        """过滤小说/非视频条目"""
        kind = str(card.get("content_kind") or "").lower()
        if kind in ("novel", "book", "text", "ebook", "manga"):
            return True
        text = " ".join([str(card.get("title") or ""), str(card.get("normalized_title") or "")])
        for g in (card.get("genres") or []):
            text += " " + str(g)
        return any(w in text for w in self.NOVEL_WORDS)

    def _video(self, card):
        """接口卡片 -> TVBox 列表项"""
        return {
            "vod_id": str(card.get("id") or ""),
            "vod_name": card.get("title") or "",
            "vod_pic": self._pic_url(card.get("poster_url") or card.get("carousel_url") or ""),
            "vod_remarks": card.get("remarks") or card.get("episode_progress_text") or "",
            "vod_year": str(card.get("year") or ""),
            "type_name": card.get("content_kind") or "",
        }

    def _cards_to_videos(self, cards, limit=None):
        out, seen = [], set()
        for c in cards or []:
            try:
                cid = str(c.get("id") or "")
                if not cid or cid in seen or self._is_novel(c):
                    continue
                seen.add(cid)
                out.append(self._video(c))
            except Exception:
                continue
        return out[:limit] if limit else out

    # ==================== 封面图本地代理 ====================
    def _use_proxy(self):
        """是否处于 PeekPro 代理环境"""
        if self._proxy_flag is None:
            try:
                from base import localProxy as _lp  # noqa: F401
                self._proxy_flag = True
            except Exception:
                try:
                    import proxy_handler as _ph  # noqa: F401
                    self._proxy_flag = True
                except Exception:
                    self._proxy_flag = False
        return self._proxy_flag

    def _proxy_url(self):
        if not self._proxy_port:
            port = 0
            try:
                from base import localProxy as lp
                port = int(lp.get_port())
            except Exception:
                port = 0
            self._proxy_port = port or self.DEFAULT_PROXY_PORT
        if not self._site_key:
            # 探测失败时不缓存兜底值, 下次调用再试一次(避免某个实例被兜底值永久污染)
            self._site_key = self._detect_site_key() or self.LOCAL_SITE_KEY
            if self._site_key == self.LOCAL_SITE_KEY:
                self._site_key = ""
                return "http://127.0.0.1:%d/proxy?do=py&siteKey=%s" % (
                    self._proxy_port, urllib.parse.quote(self.LOCAL_SITE_KEY))
        return "http://127.0.0.1:%d/proxy?do=py&siteKey=%s" % (
            self._proxy_port, urllib.parse.quote(self._site_key))

    def _site_files(self):
        """站点列表文件 sources.json 的候选路径

        从自身目录逐级向上拼接(不做目录枚举: 通配枚举会被源管家风险引擎判为
        local_scan 高危, 导致脚本被拦截无法写入站源列表)。
        """
        cands = []
        try:
            p = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            p = ""
        for _ in range(4):
            if not p:
                break
            cands.append(os.path.join(p, "files", "t4_local_script_sources",
                                      "sources.json"))
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        return cands

    def _detect_site_key(self):
        """定位本站点在 PeekPro 配置中的 key

        PeekPro 不同版本的配置注入方式不同: 老版本由 Dart 层经 proxy_handler 注入实时
        配置, 新版本的 proxy_handler._current_config 可能为空, 此时回退读取 App 私有
        目录下的站点列表文件 sources.json(与站源列表同格式)。
        key 取错会让图片代理路由到别的爬虫实例返回 404, 封面全部显示为灰底占位图。
        """
        me = ""
        try:
            me = os.path.basename(os.path.abspath(__file__)).lower()
        except Exception:
            pass
        name = self._norm_name(self.getName())

        def pick(sites):
            """先按 api 文件名精确匹配, 再按站点名(去掉 [影] 之类前缀)匹配"""
            for s in sites:
                api = str(s.get("api") or "").replace("\\", "/")
                if me and os.path.basename(api).lower() == me:
                    return str(s.get("key") or "")
            for s in sites:
                if name and self._norm_name(s.get("name")) == name:
                    return str(s.get("key") or "")
            return ""

        # 1) proxy_handler 注入的实时配置
        try:
            import proxy_handler as ph
            k = pick(list(self._walk_sites(getattr(ph, "_current_config", None), 0)))
            if k:
                return k
        except Exception:
            pass

        # 2) App 私有目录下的站点列表文件
        for sj in self._site_files():
            try:
                if not os.path.exists(sj):
                    continue
                with open(sj, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                k = pick(cfg.get("sites") or [])
                if k:
                    return k
            except Exception:
                continue
        return ""

    @staticmethod
    def _norm_name(text):
        """去掉站点名前缀标记(如 "[影]"/"[刷]")后归一化用于比较"""
        s = str(text or "").strip()
        m = re.match(r"^\[[^\]]*\]\s*(.+)$", s)
        return (m.group(1) if m else s).strip().lower()

    @staticmethod
    def _walk_sites(obj, depth):
        if depth > 3:
            return
        if isinstance(obj, dict):
            if isinstance(obj.get("api"), str) and obj.get("key"):
                yield obj
            for v in obj.values():
                for s in Spider._walk_sites(v, depth + 1):
                    yield s
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                for s in Spider._walk_sites(v, depth + 1):
                    yield s

    @staticmethod
    def _to_source_url(url):
        """从图床包装地址还原源站直链(失败返回空串)

        包装形式(注意 URL 内没有 '?', src 整段在 path 里):
          https://gimg0.baidu.com/gimg/app=2001&n=0&g=0n&fmt=webp&src=img.xxx.com/a/b.webp
        源站在真机上显示更稳(部分 Android 原生图片内核处理图床返回的 webp 不稳定)。
        """
        if "baidu.com" not in url:
            return ""
        m = re.search(r"src=([^&\s]+)", url)
        if not m:
            return ""
        src = m.group(1).strip()
        if not src:
            return ""
        if src.startswith("http"):
            return src
        return "https://" + src.lstrip("/")

    def _pic_http(self):
        """图片请求专用 Session: 复用连接池, 避免每张图都重新握手"""
        if self._pic_session is None:
            s = requests.Session()
            try:
                from requests.adapters import HTTPAdapter
                ad = HTTPAdapter(pool_connections=8, pool_maxsize=8)
                s.mount("https://", ad)
                s.mount("http://", ad)
            except Exception:
                pass
            self._pic_session = s
        return self._pic_session

    def _pic_url(self, url):
        """HTTPS 外链封面在 PeekPro 下必须走 127.0.0.1 代理, 非 PeekPro 用原链兜底"""
        url = str(url or "").strip()
        if not url:
            return ""
        if url.startswith("http") and self._use_proxy():
            pic = base64.urlsafe_b64encode(url.encode("utf-8")).decode().rstrip("=")
            return "%s&pic=%s" % (self._proxy_url(), pic)
        return url

    def localProxy(self, params):
        """PeekPro 本地代理入口: pic=base64url(图片URL) -> [200, mime, bytes]

        pic 参数自带完整图片地址, 不依赖列表构建期的实例状态;
        取图优先还原源站直链(真机显示更稳), 失败回退原始图床地址;
        串行加锁 + 每候选最多 3 次重试, 避免并发拉图触发 CDN 连接重置。
        """
        p = params if isinstance(params, dict) else {}
        pic = str(p.get("pic") or "").strip()
        if not pic:
            return [404, "text/plain", "not found"]
        s = pic + "=" * (-len(pic) % 4)
        try:
            url = base64.urlsafe_b64decode(s.encode()).decode("utf-8")
        except Exception:
            return [400, "text/plain", "bad pic"]
        if not url.startswith("http"):
            return [400, "text/plain", "bad url"]

        cached = self._pic_cache.get(url)
        if cached is not None:
            return cached

        if self._pic_lock is None:
            import threading
            self._pic_lock = threading.Lock()

        # 源站直链优先, 失败回退原始图床地址(两条链路互为兜底)
        origin = self._to_source_url(url)
        cands = [u for u in (origin, url) if u]

        with self._pic_lock:
            cached = self._pic_cache.get(url)
            if cached is not None:
                return cached
            for i, cand in enumerate(cands):
                for _ in range(3):
                    try:
                        # 不带 Referer: 带站点 Referer 会被 CDN 判为非法来源返回 400
                        rsp = self._pic_http().get(cand, headers={
                            "User-Agent": self.UA,
                            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                        }, timeout=8)
                        if rsp.status_code == 200 and rsp.content:
                            ctype = (rsp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
                            if not ctype.startswith("image"):
                                ctype = "image/jpeg"
                            result = [200, ctype, rsp.content]
                            if len(self._pic_cache) > 300:
                                self._pic_cache.clear()
                            self._pic_cache[url] = result
                            return result
                    except Exception:
                        pass
                    time.sleep(0.2)
                if i + 1 < len(cands):
                    logger.info("源站封面失败, 回退图床: %s", cand[:100])
        return [502, "text/plain", "image fetch failed"]

    # ==================== 首页 ====================
    def homeContent(self, filter=False):
        classes = [{"type_name": name, "type_id": tid} for tid, name, _ in self.KINDS]
        filters = {}
        if filter:
            filters = self._build_filters()
        result = {"class": classes}
        if filters:
            result["filters"] = filters
        return result

    def _build_filters(self):
        """分类页筛选: 类型 / 地区 / 年份 / 排序"""
        filters = {}
        for tid, name, key in self.KINDS:
            if not key or key in ("movie_high_score", "movie_hot", "movie_nowplaying",
                                  "tv_korean", "tv_japanese", "tv_american", "tv_domestic"):
                # 榜单类不做筛选
                continue
            items = [
                {"key": "genre", "name": "类型",
                 "value": [{"n": "全部", "v": ""}] + [{"n": g, "v": g} for g in self.GENRES.get(key, [])]},
                {"key": "area", "name": "地区",
                 "value": [{"n": "全部", "v": ""}] + [{"n": a, "v": a} for a in self.AREAS]},
                {"key": "year", "name": "年份",
                 "value": [{"n": "全部", "v": ""}] + [{"n": y, "v": y} for y in self.YEARS]},
                {"key": "sort", "name": "排序",
                 "value": [{"n": "最新", "v": ""}, {"n": "最热", "v": "trending"}]},
            ]
            filters[tid] = items
        return filters

    def homeVideoContent(self):
        """首页推荐位: 取 /v1/feed/home 全部板块(按板块去重)"""
        data = self._api("/v1/feed/home")
        videos, seen = [], set()
        if isinstance(data, dict):
            for sec in data.get("sections") or []:
                for v in self._cards_to_videos(sec.get("cards") or []):
                    vid = v.get("vod_id")
                    if vid and vid not in seen:
                        seen.add(vid)
                        videos.append(v)
        return {"list": videos[:60]}

    # ==================== 分类 ====================
    def _build_browse_path(self, tid, page, ext):
        """根据分类与筛选拼装 /v1/browse/catalog 请求路径(含签名用的原始 query)"""
        params = [("page", str(page)), ("limit", str(self.PAGE_SIZE))]
        ext = ext if isinstance(ext, dict) else {}

        sort = str(ext.get("sort") or "")
        if tid.startswith("h_"):
            params.append(("hot_list_key", tid[2:]))
        elif tid.startswith("t_"):
            params.append(("sort", "trending"))
            params.append(("window", "day"))
        else:
            kind = None
            for t, _n, k in self.KINDS:
                if t == tid:
                    kind = k
                    break
            if kind:
                params.append(("kind", kind))
            if sort:
                params.append(("sort", "trending"))
                params.append(("window", "day"))

        for key in ("genre", "area", "year"):
            v = str(ext.get(key) or "").strip()
            if v:
                params.append((key, v))
        query = urllib.parse.urlencode(params)
        return "/v1/browse/catalog?" + query

    def categoryContent(self, tid, pg, filter, extend):
        page = self._page_of(pg)
        path = self._build_browse_path(str(tid), page, extend)
        data = self._api(path)
        cards = data.get("cards") if isinstance(data, dict) else None
        videos = self._cards_to_videos(cards or [])
        return {
            "list": videos,
            "page": page,
            "pagecount": self._pagecount(videos, page),
            "limit": self.PAGE_SIZE,
            "total": 9999,
        }

    # ==================== 详情 ====================
    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else str(ids or "")
        if not vid:
            return {"list": []}
        path = "/v1/catalog/%s?episodes=window&episode_limit=500" % urllib.parse.quote(vid)
        d = self._api(path)
        if not isinstance(d, dict) or not d.get("title"):
            return {"list": []}

        episodes = d.get("episodes") or []
        ep_list = []  # [(集名, episode token)]
        for ep in episodes:
            token = str(ep.get("token") or "").strip()
            if not token:
                continue
            name = str(ep.get("title") or ep.get("display_name") or "").strip()
            if not name:
                name = "第%s集" % (ep.get("number") or len(ep_list) + 1)
            ep_list.append((name, token))

        from_name, play_url, total = [], [], 0
        if ep_list:
            # 线路分组: 默认最优 -> 官方线路 -> 第三方聚合 -> 各第三方线路
            for gname, want in self._line_groups([t for _n, t in ep_list]):
                items = []
                for name, token in ep_list:
                    payload = {"t": token}
                    if want:
                        payload["p"] = want
                    items.append("%s$%s" % (name, self._b64e(payload)))
                group_str = "#".join(items)
                size = len(group_str.encode("utf-8"))
                # 默认线路始终保留; 其余超预算的按优先级从后往前裁掉
                if from_name and total + size > self.MAX_DETAIL_BYTES:
                    continue
                total += size
                from_name.append(gname)
                play_url.append(group_str)

        year = d.get("year")
        vod = {
            "vod_id": str(d.get("id") or vid),
            "vod_name": d.get("title") or "",
            "vod_pic": self._pic_url(d.get("poster_url") or ""),
            "type_name": d.get("content_kind") or "",
            "vod_year": str(year) if year else "",
            "vod_area": d.get("area") or "",
            "vod_remarks": d.get("remarks") or d.get("episode_progress_text") or "",
            "vod_actor": "/".join(d.get("actors") or []),
            "vod_director": "/".join(d.get("directors") or []),
            "vod_content": d.get("description") or "",
            "vod_play_from": "$$$".join(from_name),
            "vod_play_url": "$$$".join(play_url),
        }
        return {"list": [vod]}

    # ==================== 搜索 ====================
    def searchContent(self, key, quick, pg):
        page = self._page_of(pg)
        params = [("page", str(page)), ("limit", str(self.PAGE_SIZE)),
                  ("q", str(key or "").strip()), ("intent", "catalog_search")]
        path = "/v1/browse/catalog?" + urllib.parse.urlencode(params)
        data = self._api(path)
        cards = data.get("cards") if isinstance(data, dict) else None
        videos = self._cards_to_videos(cards or [])
        return {
            "list": videos,
            "page": page,
            "pagecount": self._pagecount(videos, page),
            "limit": self.PAGE_SIZE,
            "total": 9999,
        }

    # ==================== 播放 ====================
    def _resolve_episode(self, token):
        """episode token -> line_options 列表(播放类接口: 同样需要节流)"""
        path = "/v1/playback/resolve/%s?view=compact" % urllib.parse.quote(token)
        self._play_gate()
        try:
            d = self._api(path)
        finally:
            self._play_release()
        if isinstance(d, dict):
            lines = d.get("line_options")
            if isinstance(lines, list):
                return lines
        return []

    def _play_gate(self):
        """播放类请求串行节流: 加锁 + 最小间隔, 避免连续播集触发 429"""
        if self._play_lock is None:
            import threading
            self._play_lock = threading.Lock()
        self._play_lock.acquire()
        gap = self.PLAY_MIN_GAP - (time.time() - self._last_play_ts)
        if gap > 0:
            time.sleep(gap)
        self._last_play_ts = time.time()

    def _play_release(self):
        try:
            self._play_lock.release()
        except Exception:
            pass

    def _resolve_line(self, ticket):
        """resolve 票据 -> 真实直链(播放类接口: 串行节流 + 结果缓存)"""
        self._last_rate_limited = False
        ticket = str(ticket or "").strip()
        if not ticket:
            return ""
        cached = self._line_cache.get(ticket)
        if cached:
            return cached
        self._play_gate()
        try:
            d = self._api("/v1/playback/resolve-line?view=compact", "POST",
                          {"ticket": ticket})
        finally:
            self._play_release()
        if isinstance(d, dict):
            line = d.get("line") or {}
            url = str(line.get("url") or "").strip()
            if url:
                if len(self._line_cache) > 200:
                    self._line_cache.clear()
                self._line_cache[ticket] = url
                return url
        self._last_rate_limited = self._rate_limited
        return ""

    @staticmethod
    def _line_weight(line):
        try:
            return int(line.get("preference_weight") or 0)
        except Exception:
            return 0

    def _order_lines(self, lines, want):
        """按用户选择的线路排序: 目标线路优先, 其余按站点优先级兜底"""
        ok = [l for l in (lines or []) if isinstance(l, dict)]
        if want == "*m3u8":
            # 第三方资源聚合: 优先第三方 m3u8 线路
            first = [l for l in ok if str(l.get("url_kind") or "") == "m3u8"]
            rest = [l for l in ok if str(l.get("url_kind") or "") != "m3u8"]
            first.sort(key=self._line_weight, reverse=True)
            rest.sort(key=self._line_weight, reverse=True)
            return first + rest
        if want:
            first = [l for l in ok if str(l.get("provider_id") or "") == want]
            rest = [l for l in ok if str(l.get("provider_id") or "") != want]
            rest.sort(key=self._line_weight, reverse=True)
            return first + rest
        ok.sort(key=self._line_weight, reverse=True)
        return ok

    def _line_groups(self, tokens):
        """详情页线路分组(按重要度排序): 默认最优 -> 官方线路 -> 第三方聚合 -> 各第三方线路

        线路集合从首/中/尾三集采样求并集, 避免逐集请求拖慢详情。
        provider_id 直接写进播放 payload, 不依赖实例状态。
        """
        groups = [("搜剧AI", "")]
        try:
            seen, official, m3u8_plain, has_m3u8 = set(), [], [], False
            n = len(tokens)
            for i in sorted({0, n // 2, n - 1}):
                if not (0 <= i < n):
                    continue
                for ln in self._resolve_episode(tokens[i]):
                    if not isinstance(ln, dict):
                        continue
                    pid = str(ln.get("provider_id") or "").strip()
                    if not pid or pid in seen:
                        continue
                    seen.add(pid)
                    kind = str(ln.get("url_kind") or "").strip()
                    url = str(ln.get("url") or "").strip()
                    label = str(ln.get("label") or pid).strip()
                    w = self._line_weight(ln)
                    if kind == "m3u8":
                        has_m3u8 = True
                        if url.startswith("http"):
                            m3u8_plain.append((w, label, pid))
                    else:
                        official.append((w, label, pid))
            official.sort(reverse=True)
            m3u8_plain.sort(reverse=True)
            used = {"搜剧AI"}
            for _w, label, pid in official:
                name = label if label not in used else "%s@%s" % (label, pid)
                used.add(name)
                groups.append((name, pid))
            if has_m3u8:
                groups.append(("第三方资源", "*m3u8"))
            for _w, label, pid in m3u8_plain:
                name = label if label not in used else "%s@%s" % (label, pid)
                used.add(name)
                groups.append((name, pid))
        except Exception as e:
            logger.warning("线路分组采样失败, 仅保留默认线路: %s", e)
        return groups

    def playerContent(self, flag, vid, vipFlags):
        payload = self._b64d(vid)
        token = str(payload.get("t") or "").strip()
        want = str(payload.get("p") or "").strip()
        if not token:
            return {"parse": 0, "url": ""}
        self._ensure_session()

        for attempt in range(2):
            lines = self._order_lines(self._resolve_episode(token), want)
            blocked = False   # 一旦被限流, 后续未缓存的票据不再尝试(只会同样失败)
            for ln in lines:
                if not isinstance(ln, dict):
                    continue
                u = str(ln.get("url") or "").strip()
                # 线路自带现成直链(短剧/第三方资源多为 m3u8 直链), 直接返回
                if u.startswith("http"):
                    return self._play_result(u)
                ticket = str(ln.get("resolve_ticket") or "").strip()
                if not ticket and u.startswith("resolve://"):
                    ticket = u[len("resolve://"):]
                if not ticket:
                    continue
                if blocked and ticket not in self._line_cache:
                    continue
                url = self._resolve_line(ticket)
                if url:
                    return self._play_result(url)
                if self._last_rate_limited:
                    blocked = True
            # 首次失败可能是匿名会话失效, 重建一次再试
            if attempt == 0:
                self._session_ready = False
                self._ensure_session()
        return {"parse": 0, "url": ""}

    def _play_result(self, url):
        """统一播放返回: 不给 CDN 带站点 Referer(会触发部分 CDN 403)"""
        fmt = "application/x-mpegURL" if ".m3u8" in url.lower() else ""
        return {
            "parse": 0,
            "url": url,
            "format": fmt,
            "header": {"User-Agent": self.UA},
        }


def main():
    """本地自检"""
    sp = Spider()
    print("=" * 60)
    print("【1】首页分类")
    home = sp.homeContent(True)
    for c in home["class"]:
        print("   ", c["type_id"], c["type_name"])
    print("   筛选分类数:", len(home.get("filters", {})))
    lst = sp.homeVideoContent()["list"]
    print("   首页推荐:", len(lst), "条, 首条:", lst[0]["vod_name"] if lst else "-")

    print("\n【2】分类浏览 电影(第1页)")
    cat = sp.categoryContent("k_movie", "1", False, {"genre": "动作", "sort": "trending"})
    print("   本页:", len(cat["list"]), "pagecount:", cat["pagecount"])
    for v in cat["list"][:5]:
        print("   ", v["vod_name"], "[", v["vod_remarks"], "]", v["vod_pic"][:60])

    print("\n【3】榜单 韩剧榜")
    hot = sp.categoryContent("h_tv_korean", "1", False, {})
    print("   本页:", len(hot["list"]), "首条:", hot["list"][0]["vod_name"] if hot["list"] else "-")

    print("\n【4】搜索 仙逆")
    sc = sp.searchContent("仙逆", False, "1")
    print("   结果:", len(sc["list"]), "pagecount:", sc["pagecount"])
    for v in sc["list"][:5]:
        print("   ", v["vod_name"], v["vod_year"])

    print("\n【5】详情 + 播放")
    if sc["list"]:
        det = sp.detailContent([sc["list"][0]["vod_id"]])["list"][0]
        froms = det["vod_play_from"].split("$$$")
        groups = det["vod_play_url"].split("$$$")
        print("   剧名:", det["vod_name"], "| 集数:", len(groups[0].split("#")))
        print("   线路数:", len(froms), "->", " / ".join(froms))
        for i, gname in enumerate(froms[:3]):
            first = groups[i].split("#")[0].split(chr(36))[-1]
            play = sp.playerContent(gname, first, [])
            url = play.get("url") or ""
            print("   [%s] 第1集: %s %s" % (gname, "OK" if url.startswith("http") else "FAIL", url[:60]))
        # 末集在默认线路下也验证一次
        last = groups[0].split("#")[-1].split(chr(36))[-1]
        play = sp.playerContent(froms[0], last, [])
        print("   [%s] 末集: %s" % (froms[0], "OK" if (play.get("url") or "").startswith("http") else "FAIL"))
    print("=" * 60)


if __name__ == "__main__":
    main()
