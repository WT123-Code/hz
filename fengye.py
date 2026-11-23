# -*- coding: utf-8 -*-
"""
枫叶影视 / 枫叶免扫4K · CatVod / TVBox / NewBox Python Spider
------------------------------------------------------------------
站点模板：sm（/label/qq 列表 + /chabeihu/<id>.html 详情 + /play/<id>-<sid>-<nid>.html 播放）
站点池：www.tjtcdl.com（当前主用）、www.vip1949.com、maihaolian.com、zzztool.com
依赖：仅标准库
说明：站点已改版为 sm 模板，旧 jar（csp_FengYe / csp_AppFENGYE）走 /detail、/cupfox-list
      全部 404 或空页，故改用本源。搜索页需人机验证码，本源搜索走「列表接口不可用→返回空」，
      不影响首页/分类/详情/播放。
"""
import re
import json
import urllib.request
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


SITES = [
    "https://www.tjtcdl.com",
    "https://www.vip1949.com",
    "https://maihaolian.com",
]

UA = ("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Mobile Safari/537.36")

# 首页/分类：path -> 名称
CATS = [
    ("/label/qq", "腾讯vip热播"),
    ("/label/yk", "优酷vip热播"),
    ("/label/bli", "B站vip热播"),
    ("/label/duanju", "红果短剧"),
    ("/type1.html", "电影"),
    ("/type2.html", "电视剧"),
    ("/type3.html", "综艺"),
    ("/type4.html", "动漫"),
    ("/type5.html", "短剧"),
]


def _txt(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&quot;", '"')
    s = s.replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
    return s.strip()


class Spider(BaseSpider):
    def __init__(self):
        self.site = SITES[0]
        self.extend = ""

    def init(self, extend=""):
        self.extend = extend or ""
        raw = self.extend
        if isinstance(raw, dict):
            site = raw.get("site") or raw.get("url")
            if isinstance(site, list) and site:
                site = site[0]
        else:
            site = ""
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
            SITES.insert(0, site)
        self.site = SITES[0]

    # ---------------- 网络 ----------------
    def _get(self, url, referer=None):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", UA)
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        if referer:
            req.add_header("Referer", referer)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        return data.decode("utf-8", "replace")

    def _fetch(self, path):
        """按站点池顺序尝试，返回 (html, base)"""
        last = None
        for base in SITES:
            try:
                html = self._get(base + path, referer=base + "/")
                if html and "系统安全验证" not in html:
                    self.site = base
                    return html, base
            except Exception as e:
                last = e
        if last:
            raise last
        return "", self.site

    # ---------------- 解析 ----------------
    @staticmethod
    def _parse_list(html, base):
        out = []
        blocks = re.split(r'<div class="public-list-box', html)
        for b in blocks[1:]:
            m = re.search(r'href="/(?:chabeihu|detail)/(\d+)\.html"', b)
            if not m:
                continue
            vid = m.group(1)
            t = re.search(r'title="([^"]*)"', b)
            name = _txt(t.group(1)) if t else ""
            if not name:
                t2 = re.search(r'<a[^>]+class="time-title[^"]*"[^>]*>([^<]*)<', b)
                name = _txt(t2.group(1)) if t2 else vid
            pic = ""
            p = re.search(r'data-src="([^"]+)"', b) or re.search(r'src="(https?://[^"]+)"', b)
            if p:
                pic = p.group(1).replace("&amp;", "&")
            note = ""
            n = re.search(r'class="public-list-prb[^"]*"[^>]*>([^<]*)<', b)
            if n:
                note = _txt(n.group(1))
            out.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": note,
            })
        return out

    # ---------------- 接口 ----------------
    def getName(self):
        return "枫叶"

    def homeContent(self, filter=False):
        cls = [{"type_id": p, "type_name": n} for p, n in CATS]
        videos = []
        try:
            html, base = self._fetch("/")
            videos = self._parse_list(html, base)
        except Exception:
            pass
        return {"class": cls, "list": videos, "filters": {}}

    def homeVideoContent(self):
        try:
            html, base = self._fetch("/")
            return {"list": self._parse_list(html, base)}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or "/label/qq")
        page = int(pg or 1)
        path = tid
        if not path.startswith("/"):
            path = "/label/" + path
        if page > 1:
            if path.endswith(".html"):
                path = path[:-5] + "/page/%d.html" % page
            else:
                path = path + "/page/%d.html" % page
        html, base = self._fetch(path)
        vlist = self._parse_list(html, base)
        pagecount = page + 1 if len(vlist) >= 10 else page
        return {
            "list": vlist,
            "page": page,
            "pagecount": pagecount,
            "limit": len(vlist),
            "total": 999999,
        }

    def searchContent(self, key, quick=False, pg="1"):
        # 站点搜索需图形验证码，程序侧不可用；返回空列表由聚合搜索跳过
        return {"list": [], "page": 1, "pagecount": 1, "total": 0}

    def detailContent(self, array):
        vid = str(array[0]).split("$")[0]
        html, base = self._fetch("/chabeihu/%s.html" % vid)
        name = ""
        m = re.search(r"<title>《([^》]+)》", html)
        if m:
            name = _txt(m.group(1))
        if not name:
            m = re.search(r'<title>([^<_]+)', html)
            name = _txt(m.group(1)) if m else vid
        pic = ""
        p = re.search(r'<img[^>]+class="[^"]*lazy[^"]*"[^>]+data-src="([^"]+)"', html)
        if p:
            pic = p.group(1).replace("&amp;", "&")
        desc = ""
        d = re.search(r'<strong class="r6">简介:</strong>(.*?)</div>', html, re.S)
        if d:
            desc = _txt(d.group(1))
        # 线路名
        lines = []
        tab = re.search(r'<div class="anthology-tab[^>]*>(.*?)</div>', html, re.S)
        if tab:
            for a in re.findall(r"<a[^>]*>(.*?)</a>", tab.group(1), re.S):
                nm = _txt(re.sub(r'<span[^>]*>.*?</span>', "", a, flags=re.S))
                if nm:
                    lines.append(nm)
        # 分集（按线路分组）
        plays = []
        panels = re.findall(r'<div class="anthology-list-box[^"]*"[^>]*>(.*?)</ul>', html, re.S)
        for i, pnl in enumerate(panels):
            eps = []
            for href, txt in re.findall(r'<a[^>]*href="(/play/[^"]+)"[^>]*>([^<]*)</a>', pnl):
                eps.append("%s$%s" % (_txt(txt) or "正片", href))
            if eps:
                plays.append((lines[i] if i < len(lines) else "线路%d" % (i + 1), eps))
        froms = [x[0] for x in plays]
        urls = [("#".join(x[1])) for x in plays]
        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": "",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": desc,
        }
        if plays:
            vod["vod_play_from"] = "$$$".join(froms)
            vod["vod_play_url"] = "$$$".join(urls)
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        # id 形如 /play/20245-8-190.html
        pid = str(id or "")
        if pid.startswith("http"):
            url = pid
        elif pid.startswith("/"):
            url = self.site + pid
        else:
            url = self.site + "/play/" + pid
        header = {
            "User-Agent": UA,
            "Referer": self.site + "/",
        }
        # 站点播放页为签名播放器，交给客户端嗅探
        return {"parse": 1, "playUrl": "", "url": url, "header": header}
