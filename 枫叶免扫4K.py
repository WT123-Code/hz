# @tvbox-source
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
枫叶免扫4K  - 茶杯狐(cupfox)模板网页爬虫
逆向自 EasyTV 的 AppFENGYE（EasyXC/EasyTVbox 新版 jar），改为自托管 py 源。
站点默认 maihaolian.com，备用 zzztool.com；失效时改下方 SITE 即可，无需动 jar。
支持：首页/分类/筛选、搜索、详情、播放(页面直出或解析站 mplayer.php)。
"""

import re
import json
from urllib.parse import quote

import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    BaseSpider = object


class Spider(BaseSpider):
    # 主站 + 备用站：站挂了换一个即可
    SITE = "https://maihaolian.com"
    SITE_BACKUP = "https://zzztool.com"
    # 解析站表（视频非直链时按线路前缀走这些解析站）
    PARSE = {
        "JD": "https://fgsrg.hzqingshan.com",
        "co": "https://zzrs.mfdyvip.com",
        "knmb": "https://zzrs.mfdyvip.com",
        "YYNB": "https://zzrs.mfdyvip.com",
    }
    UA = ("Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
          "Chrome/150.0.0.0 Mobile")
    TIMEOUT = 20

    # 播放页提取直链的正则
    RE_PLAYER_AAAA = re.compile(r'var\s+player_aaaa[\s\S]*?"url"\s*:\s*"([^"]+)"')
    RE_URL_VAR = re.compile(r'url\s*[:=]\s*["\'](http[^"\']+)["\']')
    RE_TOKEN = re.compile(r'data-te="([^"]+)"')

    def __init__(self):
        super().__init__()
        self.site = self.SITE

    def _headers(self):
        return {"User-Agent": self.UA, "Referer": self.site + "/"}

    def _get(self, url):
        try:
            r = requests.get(url, headers=self._headers(), timeout=self.TIMEOUT)
            return r.text
        except Exception:
            return ""

    # ---------- 首页 ----------
    def homeContent(self, filter=False):
        classes = [
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "/label/qq", "type_name": "腾讯精选"},
            {"type_id": "/label/bli", "type_name": "B站精选"},
            {"type_id": "/label/youku", "type_name": "优酷精选"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "5", "type_name": "热门短剧"},
        ]
        return json.dumps({"class": classes}, ensure_ascii=False)

    def homeVideoContent(self):
        return self.categoryContent("", "1", False, {})

    # ---------- 分类/筛选 ----------
    def categoryContent(self, tid, pg, filter, extend):
        pg = max(int(pg or 1), 1)
        tid = (tid or "").strip()
        is_label = tid.startswith("/label")
        if not extend:
            extend = {}
        type_v = extend.get("type") or tid
        area = extend.get("area", "")
        orderby = extend.get("orderby", "time")
        cls = extend.get("class", "")
        lang = extend.get("lang", "")
        letter = extend.get("letter", "")
        year = extend.get("year", "")
        if is_label:
            url = self.site + tid + "/page/" + str(pg) + ".html"
        else:
            if not type_v:
                url = self.site
            else:
                url = (self.site + "/cupfox-list/" + type_v + "-" + area + "-" + orderby +
                       "-" + cls + "-" + lang + "-" + letter + "---" + str(pg) + "---" + year + ".html")
        html = self._get(url)
        if not html:
            return json.dumps({"list": [], "page": pg, "pagecount": 1}, ensure_ascii=False)
        lst, pagecount = self._parse_list(html, is_label=is_label)
        return json.dumps({"parse": 0, "jx": 0, "list": lst, "page": pg,
                           "pagecount": max(pagecount, 1), "limit": 30,
                           "total": max(pagecount, 1) * 30}, ensure_ascii=False)

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg="1"):
        if int(pg or 1) >= 2:
            return '{"parse":0,"jx":0,"list":[],"pagecount":1}'
        url = self.site + "/cupfox-search/-------------.html?wd=" + quote(key)
        html = self._get(url)
        if not html:
            return '{"parse":0,"jx":0,"list":[],"pagecount":1}'
        lst, pagecount = self._parse_list(html, is_search=True)
        return json.dumps({"parse": 0, "jx": 0, "list": lst, "pagecount": max(pagecount, 1)},
                          ensure_ascii=False)

    # ---------- 列表解析（茶杯狐模板） ----------
    def _parse_list(self, html, is_label=False, is_search=False):
        lst = []
        pagecount = 1
        # 条目容器 .public-list-bj
        for block in re.findall(r'class="[^"]*public-list-bj[^"]*"[^>]*>(.*?)</li>', html, re.S):
            href_m = re.search(r'<a[^>]+class="[^"]*public-list-exp[^"]*"[^>]+href="([^"]+)"', block)
            if not href_m:
                continue
            href = href_m.group(1)
            title = ""
            tm = re.search(r'<a[^>]+class="[^"]*public-list-exp[^"]*"[^>]+title="([^"]+)"', block)
            if tm:
                title = tm.group(1)
            if not title:
                tm2 = re.search(r'class="thumb-content"[^>]*>\s*<a[^>]*>([^<]+)<', block)
                if tm2:
                    title = tm2.group(1)
            pic = ""
            pm = re.search(r'<img[^>]+data-src="([^"]+)"', block)
            if pm:
                pic = pm.group(1)
            else:
                pm2 = re.search(r'<img[^>]+src="([^"]+)"', block)
                if pm2:
                    pic = pm2.group(1)
            remarks = ""
            rm = re.search(r'class="[^"]*ft2[^"]*"[^>]*>([^<]+)<', block)
            if rm:
                remarks = rm.group(1).strip()
            # 年份信息
            year = ""
            ym = re.search(r'class="[^"]*public-prt-g[^"]*"[^>]*>([^<]+)<', block)
            if ym:
                year = ym.group(1).strip()
            prts = re.findall(r'class="[^"]*public-prt[^"]*"[^>]*>([^<]+)<', block)
            if len(prts) > 1:
                year = prts[1].strip()
            year_txt = ("「" + year + "」 ") if year else ""
            if href:
                lst.append({"vod_id": href,
                            "vod_name": title,
                            "vod_pic": pic,
                            "vod_remarks": remarks,
                            "vod_year": year_txt.strip()})
        # 分页 .page-tip  形如 "1/12页"
        pt = re.search(r'class="[^"]*page-tip[^"]*"[^>]*>([^<]+)<', html)
        if pt:
            m = re.search(r'(\d+)/(\d+)页', pt.group(1))
            if m:
                pagecount = int(m.group(2))
        return lst, pagecount

    # ---------- 详情 ----------
    def detailContent(self, ids):
        if not ids or not ids[0]:
            return '{"list":[]}'
        vod_id = ids[0].strip()
        if not vod_id:
            return '{"list":[]}'
        url = vod_id if vod_id.startswith("http") else (self.site + (vod_id if vod_id.startswith("/") else "/" + vod_id))
        html = self._get(url)
        if not html:
            return '{"list":[]}'
        d = {"vod_id": vod_id, "vod_name": "未知标题", "vod_pic": "",
             "vod_actor": "", "vod_remarks": "", "vod_content": "",
             "vod_play_from": "", "vod_play_url": ""}
        # 标题 .slide-info-title
        m = re.search(r'class="[^"]*slide-info-title[^"]*"[^>]*>\s*<h1[^>]*>([^<]+)</h1>', html, re.S)
        if m:
            d["vod_name"] = m.group(1).strip()
        # 封面 .detail-pic img
        m = re.search(r'class="[^"]*detail-pic[^"]*"[^>]*>\s*<img[^>]+(?:data-src|src)="([^"]+)"', html, re.S)
        if m:
            d["vod_pic"] = m.group(1)
        # 简介 #height_limit
        m = re.search(r'id="height_limit"[^>]*>([^<]+)<', html, re.S)
        if m:
            d["vod_content"] = m.group(1).strip()
        # 演员/信息 .detail-info .slide-info
        for info in re.findall(r'class="[^"]*slide-info[^"]*"[^>]*>([^<]+)<', html):
            t = info.strip()
            if "演员" in t:
                d["vod_actor"] = re.sub(r'\s+', '', t).replace("演员：", "").replace("演员:", "")
        # 线路分组 .swiper-slide
        lines = []
        for sw in re.findall(r'class="[^"]*swiper-slide[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S):
            nm = re.search(r'<(?:i|span)[^>]*>([^<]+)<', sw)
            if nm:
                t = nm.group(1).strip()
                if t and t not in lines:
                    lines.append(t)
        # 剧集 .anthology-list-box a
        groups = []
        for box in re.findall(r'class="[^"]*anthology-list-box[^"]*"[^>]*>(.*?)</ul>', html, re.S):
            eps = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>', box)
            if eps:
                groups.append(eps)
        # 兜底：直接找所有 anthology-list-box 里的 a
        if not groups:
            for box in re.findall(r'anthology-list-box', html):
                pass
        if not lines and groups:
            lines = ["线路" + str(i + 1) for i in range(len(groups))]
        if groups:
            froms = "$$$".join(f"{lines[i]}({len(groups[i])})" if i < len(lines) else f"线路{i+1}({len(groups[i])})"
                               for i in range(len(groups)))
            urls = "$$$".join("#".join(f"{n}${h}" for h, n in g) for g in groups)
            d["vod_play_from"] = froms
            d["vod_play_url"] = urls
        return json.dumps({"parse": 0, "jx": 0, "list": [d]}, ensure_ascii=False)

    # ---------- 播放 ----------
    def playerContent(self, ids, flag, url):
        url = (url or "").strip()
        if not url:
            return '{"parse":0,"url":""}'
        if not url.startswith("http"):
            url = self.site + (url if url.startswith("/") else "/" + url)
        html = self._get(url)
        real = ""
        m = self.RE_PLAYER_AAAA.search(html)
        if m:
            real = m.group(1).replace("\\/", "/")
        if not real:
            m = self.RE_URL_VAR.search(html)
            if m:
                real = m.group(1)
        if real:
            url = real
        # 非直链走解析站
        if not (url.startswith("http") and (url.find("m3u") >= 0 or url.find(".mp4") >= 0)):
            parsed = self._parse_play(url)
            if parsed:
                url = parsed
        header = {"User-Agent": self.UA, "Referer": self.site + "/"}
        parse = 0 if (url.find("m3u") >= 0 or url.find(".mp4") >= 0) else 1
        return json.dumps({"parse": parse, "jx": 0, "url": url, "header": header}, ensure_ascii=False)

    def _parse_play(self, url):
        # 线路前缀 -> 解析站
        head = url.split("[-_]")[0]
        ps = self.PARSE.get(head)
        if not ps:
            return ""
        try:
            r = requests.get(ps + "/player/?url=" + quote(url), headers=self._headers(), timeout=self.TIMEOUT)
            text = r.text
            token = ""
            m = re.search(r'id="player-data"[^>]+data-te="([^"]+)"', text)
            if m:
                token = m.group(1)
            if not token:
                m = self.RE_TOKEN.search(text)
                if m:
                    token = m.group(1)
            if not token:
                return ""
            r2 = requests.post(ps + "/player/mplayer.php",
                                data={"url": url, "token": token},
                                headers={"User-Agent": self.UA, "Referer": ps + "/player/?url=" + url,
                                         "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                                timeout=self.TIMEOUT)
            txt = r2.text.strip()
            if not txt:
                return ""
            if txt.startswith("{"):
                try:
                    u = json.loads(txt).get("url")
                    if u:
                        return u if u.startswith("/playproxy.php") else u
                except Exception:
                    pass
        except Exception:
            pass
        return ""
