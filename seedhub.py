# -*- coding: utf-8 -*-
"""
SeedHub（种子）· CatVod / TVBox / NewBox Python Spider
------------------------------------------------------------------
数据来源：SeedHub 源站自身（列表 /movies/<id>/ 详情里的网盘链接，data-link 分夸克/UC/百度/迅雷/阿里）
站点池：seeduck.cc、seedhub.cc、sidhub.cc、hubdog.cc、seedog.cc（同一套站，互为备用）
关键点：源站挂了 Cloudflare「托管验证」，只放行浏览器 TLS 指纹；
        curl_cffi（impersonate）可稳定 200，标准库 requests/urllib 一律 403。
        => 优先 curl_cffi；没有该库时退回 requests/urllib（大概率被 403，返回空）
依赖：curl_cffi（推荐）或 requests / 标准库
"""
import re
import json
import urllib.parse

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

try:
    from curl_cffi import requests as _cf
except Exception:
    _cf = None

try:
    import requests as _rq
except Exception:
    _rq = None


SITES = [
    "https://seeduck.cc",
    "https://seedhub.cc",
    "https://sidhub.cc",
    "https://hubdog.cc",
    "https://seedog.cc",
]

IMPS = ["chrome131", "safari17_0", "edge101", "chrome124", "chrome120"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CATS = [
    ("1", "电影"),
    ("2", "剧集"),
    ("3", "动漫"),
]

PAN_NAME = {
    "quark": "夸克",
    "uc": "UC",
    "baidu": "百度",
    "xunlei": "迅雷",
    "ali": "阿里",
}
PAN_ORDER = ["quark", "uc", "baidu", "xunlei", "ali"]


def _txt(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"')
    s = s.replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
    s = re.sub(r"[ \t\r\n]+", " ", s)
    return s.strip()


def _pan_key(dom):
    d = (dom or "").lower()
    for k in PAN_ORDER:
        if k in d:
            return k
    return "other"


class Spider(BaseSpider):
    def __init__(self):
        self.site = SITES[0]
        self.imp = IMPS[0]
        self.extend = ""
        self.session = None
        if _cf is not None:
            self.session = self._new_session()

    def init(self, extend=""):
        self.extend = extend or ""
        raw = self.extend
        site = ""
        if isinstance(raw, dict):
            t = raw.get("site") or raw.get("url")
            if isinstance(t, list) and t:
                t = t[0]
            site = t or ""
        else:
            s = str(raw).strip()
            if s.startswith("{"):
                try:
                    o = json.loads(s)
                    t = o.get("site") or o.get("url")
                    if isinstance(t, list) and t:
                        t = t[0]
                    site = t or ""
                except Exception:
                    site = ""
            elif s.startswith("http"):
                site = s
        site = (site or "").strip().rstrip("/")
        if site:
            if site not in SITES:
                SITES.insert(0, site)
            self.site = site
        return None

    # ---------------- 网络 ----------------
    def _new_session(self):
        if _cf is None:
            return None
        try:
            return _cf.Session(impersonate=self.imp)
        except Exception:
            try:
                return _cf.Session(impersonate=IMPS[0])
            except Exception:
                return None

    def _rotate(self):
        i = IMPS.index(self.imp) if self.imp in IMPS else 0
        self.imp = IMPS[(i + 1) % len(IMPS)]
        self.session = self._new_session()

    def _raw_get(self, url):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": self.site + "/",
        }
        if self.session is not None:
            try:
                r = self.session.get(url, headers=headers, timeout=9, allow_redirects=True)
                return r.text if r.status_code == 200 else ""
            except Exception:
                self._rotate()
                return ""
        if _rq is not None:
            try:
                r = _rq.get(url, headers=dict(headers, **{"User-Agent": UA}), timeout=12)
                if r.status_code == 200 and "Just a moment" not in r.text:
                    return r.text
            except Exception:
                pass
            return ""
        import urllib.request
        req = urllib.request.Request(url, headers=dict(headers, **{"User-Agent": UA}))
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            return ""

    def _fetch(self, path, need=1500):
        """站点池 + 指纹轮换，任一命中即返回 (html, base)"""
        if path.startswith("http"):
            html = self._raw_get(path)
            return html, path.rsplit("/", 1)[0]
        order = [self.site] + [s for s in SITES if s != self.site]
        for base in order:
            for _try in range(3):
                html = self._raw_get(base + path)
                if html and len(html) >= need and "Just a moment" not in html:
                    self.site = base
                    return html, base
        return "", self.site

    # ---------------- 解析 ----------------
    @staticmethod
    def _parse_list(html, base):
        out = []
        seen = set()
        for b in re.split(r'<div class="cover">', html)[1:]:
            m = re.search(r'href="/movies/(\d+)/"', b)
            if not m:
                continue
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            pic = ""
            p = re.search(r'<img[^>]+src="([^"]+)"', b)
            if p:
                pic = p.group(1).replace("&amp;", "&")
            name = ""
            n = re.search(r'<h2>.*?class="header-anchor">#</a>(.*?)</h2>', b, re.S)
            if n:
                name = _txt(n.group(1))
            if not name:
                a = re.search(r'<img[^>]+alt="([^"]*)"', b)
                name = _txt(a.group(1)) if a else vid
            info = ""
            li = re.findall(r"<li>(.*?)</li>", b, re.S)
            for x in li:
                t = _txt(x)
                if "/" in t and re.search(r"\d{4}", t):
                    info = t
                    break
            note = ""
            sc = re.search(r"豆瓣评分:.*?>(\d+\.?\d*)<", b, re.S)
            if sc:
                note = "豆瓣 " + sc.group(1)
            out.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": note,
                "vod_content": info,
            })
        return out

    # ---------------- 接口 ----------------
    def getName(self):
        return "种子"

    def homeContent(self, filter=False):
        videos = []
        cls = [{"type_id": t, "type_name": n} for t, n in CATS]
        html, base = self._fetch("/categories/1/movies/?page=1")
        if not html:
            html, base = self._fetch("/")
        try:
            videos = self._parse_list(html, base)
        except Exception:
            pass
        return {"class": cls, "list": videos, "filters": {}}

    def homeVideoContent(self):
        try:
            html, base = self._fetch("/categories/1/movies/?page=1")
            return {"list": self._parse_list(html, base)}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or "1")
        page = int(pg or 1)
        path = "/categories/%s/movies/?page=%d" % (tid, page)
        html, base = self._fetch(path)
        vlist = self._parse_list(html, base) if html else []
        return {
            "list": vlist,
            "page": page,
            "pagecount": page + 1 if vlist else page,
            "limit": len(vlist),
            "total": 999999,
        }

    def searchContent(self, key, quick=False, pg="1"):
        page = int(pg or 1)
        kw = urllib.parse.quote(str(key or "").strip())
        html, base = self._fetch("/s/%s/?page=%d" % (kw, page), need=1000)
        vlist = self._parse_list(html, base) if html else []
        return {"list": vlist, "page": page,
                "pagecount": page + 1 if vlist else page,
                "limit": len(vlist), "total": 999999}

    def detailContent(self, array):
        vid = str(array[0]).split("$")[0]
        html, base = self._fetch("/movies/%s/" % vid)
        name = ""
        m = re.search(r'<h1 id="cover">.*?header-anchor">#</a>(.*?)</h1>', html, re.S)
        if m:
            name = _txt(m.group(1))
        if not name:
            m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            name = _txt(m.group(1)) if m else vid
        pic = ""
        p = re.search(r'<div class="cover-container">.*?<img[^>]+src="([^"]+)"', html, re.S)
        if p:
            pic = p.group(1).replace("&amp;", "&")
        desc = ""
        d = re.search(r'<meta name="description" content="([^"]*)"', html)
        if d:
            desc = _txt(d.group(1))
        director = ""
        dd = re.search(r'<li>导演:\s*(.*?)</li>', html, re.S)
        if dd:
            director = _txt(re.sub(r"<a[^>]*>", "", dd.group(1)).replace("</a>", ""))
        writer = ""
        ww = re.search(r'<li>编剧:\s*(.*?)</li>', html, re.S)
        if ww:
            writer = _txt(re.sub(r"<a[^>]*>", "", ww.group(1)).replace("</a>", ""))
        actor = ""
        aa = re.search(r'<li>主演:\s*(.*?)</li>', html, re.S)
        if aa:
            actor = _txt(re.sub(r"<a[^>]*>", "", aa.group(1)).replace("</a>", ""))
        remark = ""
        rt = re.search(r'资源更新于:.*?<code[^>]*>(.*?)</code>', html, re.S)
        if rt:
            remark = _txt(rt.group(1))
        year = ""
        y = re.search(r"<li>首播:.*?(\d{4})", html, re.S) or re.search(r"<li>\s*(\d{4})\s*/\s*", html)
        if y:
            year = y.group(1)
        area = ""
        ar = re.search(r"<li>制片国家/地区:.*?</li>", html, re.S)
        if ar:
            area = _txt(re.sub(r"<a[^>]*>", "", ar.group(0)).replace("</a>", ""))
            area = area.split(":", 1)[-1].strip()
        vote = ""
        vv = re.search(r"<li>豆瓣评分:.*?>(\d+\.?\d*)<", html, re.S)
        if vv:
            vote = "豆瓣 " + vv.group(1)

        links = {}
        urls = set()
        for a_tag in re.findall(r"<a [^>]*>", html):
            if "link_start" not in a_tag:
                continue
            hm = re.search(r'href="([^"]+)"', a_tag)
            dm = re.search(r'data-link="([^"]+)"', a_tag)
            tm = re.search(r'title="([^"]*)"', a_tag)
            if not hm:
                continue
            href = hm.group(1).replace("&amp;", "&")
            url = href if href.startswith("http") else base + href
            if url in urls:
                continue
            urls.add(url)
            key = _pan_key(dm.group(1) if dm else href)
            tname = _txt(tm.group(1)) if tm else "网盘资源"
            links.setdefault(key, []).append((tname, url))

        groups = []
        for k in PAN_ORDER + ["other"]:
            items = links.get(k) or []
            if not items:
                continue
            eps = []
            for i, (tname, url) in enumerate(items):
                label = tname
                if len(label) > 40:
                    label = label[:40]
                label = label.replace("$", " ").replace("#", " ").strip() or ("资源%d" % (i + 1))
                eps.append("%s$%s" % (label, url))
            groups.append((PAN_NAME.get(k, "其他网盘"), eps))

        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": "",
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": remark or vote,
            "vod_actor": actor,
            "vod_director": director,
            "vod_content": desc,
        }
        if groups:
            vod["vod_play_from"] = "$$$".join([g[0] for g in groups])
            vod["vod_play_url"] = "$$$".join(["#".join(g[1]) for g in groups])
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        pid = str(id or "")
        url = pid if pid.startswith("http") else self.site + pid
        header = {"User-Agent": UA, "Referer": self.site + "/"}
        return {"parse": 1, "playUrl": "", "url": url, "header": header}
