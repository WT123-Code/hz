# -*- coding: utf-8 -*-
import json
import os
import time
import hmac
import hashlib
import requests
from base.spider import Spider


class Spider(Spider):
    def getName(self):
        return "搜剧AI"

    def init(self, extend=""):
        self.hosts = ["https://bpz6.com", "https://souju.ai", "https://www.baipiaozhe.com", "https://baipiaozhe.com", "https://ai.baipiaozhe.com"]
        self.host = self.hosts[0]
        self.secret = "f39d73aa7a6426203cdee1ef17b31d3b7ea8c23f4c59c62a3a8aa0f39ee5e79d"
        self.ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        self.headers = {
            "User-Agent": self.ua,
            "Referer": self.host + "/",
            "Accept": "application/json",
            "x-ai-movie-client-name": "web",
            "x-ai-movie-client-version": "1",
            "x-ai-movie-protocol-version": "1",
        }
        self.session = requests.Session()
        self.session.verify = False
        self._anon_id = None
        self._authed = False
        self._cards = {}
        self._ep_cache = {}
        # 懂片帝后端：同一批片源，但它签发的官方/4K 线路链接是可播的
        # （主站签发的「专享4K-Y」常返回 403 链接无效）
        self.dp_hosts = ["https://dongpian1.com", "https://dongpian17.com"]
        self.dp_key = "8b9a908a05eac640e1ee06f52acaa741bfe4ba9e004eeffdbeb635e532e06666"
        self.dp_ua = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36")

        self.classes = [
            {"type_id": "latest", "type_name": "最新上架"},
            {"type_id": "trending", "type_name": "大家都在看"},
            {"type_id": "tv_domestic", "type_name": "国产新剧"},
            {"type_id": "tv_korean", "type_name": "韩剧在追"},
            {"type_id": "tv_japanese", "type_name": "日剧上新"},
            {"type_id": "tv_american", "type_name": "美剧续看"},
            {"type_id": "movie_high_score", "type_name": "高分电影"},
            {"type_id": "movie_hot", "type_name": "电影热播"},
            {"type_id": "movie_nowplaying", "type_name": "院线热映"},
        ]
        self.filters = {c["type_id"]: [] for c in self.classes}

    # ---- auth & api helpers ----

    def _gen_nonce(self):
        return os.urandom(16).hex()

    def _sign(self, method, full_path):
        ts = str(int(time.time() * 1000))
        nonce = self._gen_nonce()
        msg = method + "\n" + full_path + "\n" + ts + "\n" + nonce
        sig = hmac.new(
            self.secret.encode("utf-8"),
            msg.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return ts, nonce, sig

    def _rotate_host(self):
        """当前域名不通时，自动换下一个可用域名"""
        try:
            i = self.hosts.index(self.host)
        except ValueError:
            i = -1
        for k in range(1, len(self.hosts) + 1):
            cand = self.hosts[(i + k) % len(self.hosts)]
            if cand == self.host:
                continue
            try:
                r = self.session.get(cand + "/", headers={"User-Agent": self.ua}, timeout=8, verify=False)
                if r.status_code == 200:
                    self.host = cand
                    self.headers["Referer"] = cand + "/"
                    self._authed = False
                    return True
            except Exception:
                continue
        return False

    def _ensure_auth(self):
        if self._authed:
            return
        if not self._anon_id:
            self._anon_id = os.urandom(16).hex()
        path = "/v1/users/anonymous"
        ts, nonce, sig = self._sign("POST", path)
        h = dict(self.headers)
        h["Content-Type"] = "application/json"
        h["x-ai-movie-timestamp"] = ts
        h["x-ai-movie-nonce"] = nonce
        h["x-ai-movie-signature"] = sig
        try:
            r = self.session.post(
                self.host + path,
                headers=h,
                json={"anonymous_id": self._anon_id},
                timeout=15,
            )
            if r.status_code == 200 or r.status_code == 201:
                self._authed = True
                return
        except Exception:
            pass
        if self._rotate_host():
            try:
                h2 = dict(self.headers)
                h2["Content-Type"] = "application/json"
                h2["x-ai-movie-timestamp"] = ts
                h2["x-ai-movie-nonce"] = nonce
                h2["x-ai-movie-signature"] = sig
                r = self.session.post(self.host + path, headers=h2,
                                      json={"anonymous_id": self._anon_id},
                                      timeout=15, verify=False)
                if r.status_code in (200, 201):
                    self._authed = True
            except Exception:
                pass

    def _api_get(self, path, params=None):
        self._ensure_auth()
        from urllib.parse import urlencode
        search = ""
        if params:
            search = "?" + urlencode(params)
        full = path + search
        ts, nonce, sig = self._sign("GET", full)
        h = dict(self.headers)
        h["x-ai-movie-timestamp"] = ts
        h["x-ai-movie-nonce"] = nonce
        h["x-ai-movie-signature"] = sig
        for attempt in (0, 1):
            try:
                r = self.session.get(self.host + full, headers=h, timeout=15, verify=False)
                r.encoding = r.apparent_encoding or "utf-8"
                if r.status_code == 200:
                    try:
                        return r.json()
                    except Exception:
                        return {}
            except Exception:
                pass
            if attempt == 0 and self._rotate_host():
                self._ensure_auth()
                continue
            break
        return {}

    def _api_post(self, path, body=None, params=None):
        """带签名的 POST（用于 resolve-line 等）"""
        self._ensure_auth()
        from urllib.parse import urlencode
        search = ""
        if params:
            search = "?" + urlencode(params)
        full = path + search
        ts, nonce, sig = self._sign("POST", full)
        h = dict(self.headers)
        h["Content-Type"] = "application/json"
        h["x-ai-movie-timestamp"] = ts
        h["x-ai-movie-nonce"] = nonce
        h["x-ai-movie-signature"] = sig
        for attempt in (0, 1):
            try:
                r = self.session.post(self.host + full, headers=h,
                                      json=body or {}, timeout=15, verify=False)
                if r.status_code in (200, 201):
                    try:
                        return r.json()
                    except Exception:
                        return {}
            except Exception:
                pass
            if attempt == 0 and self._rotate_host():
                self._ensure_auth()
                continue
            break
        return {}

    def _resolve_line_ticket(self, ticket):
        """把 resolve:// 票据换成真实 m3u8（官方/4K 线路都走这里）"""
        data = self._api_post("/v1/playback/resolve-line", {"ticket": ticket}, {"view": "compact"})
        line = data.get("line") or {}
        url = str(line.get("url") or "")
        if url.startswith("http"):
            return url
        return ""

    def _api2(self, host, key, hdr, method, path, params=None, body=None):
        """通用签名请求（可指定域名/密钥），用于主站与懂片后端"""
        from urllib.parse import urlencode
        qs = ("?" + urlencode(params)) if params else ""
        full = path + qs
        ts = str(int(time.time() * 1000))
        n = self._gen_nonce()
        msg = method + "\n" + full + "\n" + ts + "\n" + n
        sig = hmac.new(key.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
        h = dict(hdr)
        h["x-ai-movie-timestamp"] = ts
        h["x-ai-movie-nonce"] = n
        h["x-ai-movie-signature"] = sig
        try:
            if method == "GET":
                r = self.session.get(host + full, headers=h, timeout=15, verify=False)
            else:
                h["Content-Type"] = "application/json"
                r = self.session.post(host + full, headers=h, json=body or {},
                                      timeout=15, verify=False)
            if r.status_code in (200, 201):
                return r.json()
        except Exception:
            pass
        return {}

    def _dp_headers(self, host):
        return {"User-Agent": self.dp_ua, "Origin": host, "Referer": host + "/",
                "Accept": "application/json"}

    def _ep_token(self, host, key, hdr, vod_id, ep_num):
        """按集号取 token（带缓存）"""
        ck = (host, str(vod_id), str(ep_num))
        if ck in self._ep_cache:
            return self._ep_cache[ck]
        offset = 0
        while offset < 3000:
            d = self._api2(host, key, hdr, "GET",
                           "/v1/catalog/%s/episodes" % vod_id,
                           {"offset": offset, "limit": 100})
            eps = (d or {}).get("episodes") or []
            if not eps:
                break
            for e in eps:
                if str(e.get("number")) == str(ep_num):
                    tok = e.get("token") or ""
                    self._ep_cache[ck] = tok
                    return tok
            pag = (d or {}).get("episode_pagination") or {}
            if not pag.get("has_more"):
                break
            offset += len(eps)
        return ""

    def _line_url(self, host, key, hdr, vod_id, ep_num, pid):
        """在指定后端取某线路的真实播放地址（官方/4K 自动二次解析）"""
        tok = self._ep_token(host, key, hdr, vod_id, ep_num)
        if not tok:
            return ""
        d = self._api2(host, key, hdr, "GET", "/v1/playback/resolve/" + tok)
        lo = (d or {}).get("line_options") or []
        target = None
        for x in lo:
            if (x.get("provider_id") or "") == pid:
                target = x
                break
        if not target:
            return ""
        url = str(target.get("url") or "")
        kind = target.get("url_kind") or ""
        if target.get("resolve_mode") == "direct" and url.startswith("http"):
            return url
        if kind == "resolve_ticket" or url.startswith("resolve://"):
            d2 = self._api2(host, key, hdr, "POST", "/v1/playback/resolve-line",
                            {"view": "compact"},
                            {"ticket": url.replace("resolve://", "")})
            u = ((d2 or {}).get("line") or {}).get("url") or ""
            if u.startswith("http"):
                return u
        return ""

    # ---- card -> vod helper ----

    def _card_to_vod(self, card):
        vod_id = str(card.get("export_id") or card.get("id") or "")
        name = card.get("title") or card.get("normalized_title") or ""
        pic = card.get("poster_url") or card.get("backdrop_url") or ""
        remark = card.get("remarks") or ""
        if not remark and card.get("year"):
            remark = str(card.get("year"))
        try:
            self._cards[vod_id] = card
        except Exception:
            pass
        return {
            "vod_id": vod_id,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remark,
        }

    # ---- six interfaces ----

    def homeContent(self, filter):
        data = self._api_get("/v1/feed/home")
        classes = list(self.classes)
        movies = []
        for sec in data.get("sections", []):
            for card in sec.get("cards", []):
                movies.append(self._card_to_vod(card))
            break
        return {
            "class": classes,
            "list": movies[:20],
            "filters": self.filters,
        }

    def homeVideoContent(self):
        data = self._api_get("/v1/feed/home")
        movies = []
        for sec in data.get("sections", []):
            for card in sec.get("cards", []):
                movies.append(self._card_to_vod(card))
            break
        return movies[:20]

    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg or 1))
        limit = 20
        params = {"page": str(page), "limit": str(limit)}
        if tid == "latest":
            params["sort"] = "latest"
        elif tid == "trending":
            params["sort"] = "trending"
        else:
            params["hot_list_key"] = tid

        ext = extend if isinstance(extend, dict) else {}
        if ext.get("sort"):
            params["sort"] = ext["sort"]
            if "hot_list_key" in params:
                del params["hot_list_key"]

        data = self._api_get("/v1/browse/catalog", params)
        cards = data.get("cards", [])
        movies = [self._card_to_vod(c) for c in cards]
        pag = data.get("pagination", {})
        total = pag.get("total") or 0
        if not total:
            total = pag.get("returned_count", 0) * (page + 1) if pag.get("has_more") else pag.get("returned_count", 0) * page
        pagecount = max(total // limit if total else page, page + 1 if pag.get("has_more") else page)
        return {
            "page": page,
            "pagecount": pagecount,
            "limit": len(movies),
            "total": total or (pagecount * limit),
            "list": movies,
        }

    def _resolve_lines(self, ep_token):
        """解析第一集，列出全部线路：官方(parse/ticket) 在前，第三方直链在后"""
        data = self._api_get("/v1/playback/resolve/" + ep_token)
        line_options = data.get("line_options", [])
        out = []
        for lo in line_options:
            mode = lo.get("resolve_mode") or ""
            kind = lo.get("url_kind") or ""
            url = str(lo.get("url") or "")
            if kind == "resolve_ticket" or url.startswith("resolve://"):
                out.append({
                    "provider_id": lo.get("provider_id") or "",
                    "provider_name": (lo.get("display_label") or lo.get("provider_name")
                                      or lo.get("label") or ""),
                    "resolve_mode": "parse",
                    "url": url,
                    "url_kind": kind,
                })
            elif mode == "direct" and kind == "m3u8" and url.startswith("http"):
                out.append({
                    "provider_id": lo.get("provider_id") or "",
                    "provider_name": (lo.get("provider_name") or lo.get("display_label")
                                      or lo.get("label") or ""),
                    "resolve_mode": "direct",
                    "url": url,
                    "url_kind": kind,
                })
        def _rank(x):
            nm = (x.get("provider_name") or "").upper()
            if "4K" in nm or "2160" in nm:
                return 0
            if x.get("resolve_mode") == "parse":
                return 1
            return 2

        out.sort(key=lambda x: (_rank(x), x.get("provider_name", "")))
        return out

    def detailContent(self, ids):
        # 注意：/v1/catalog/{id} 服务端固定返回 500 internal_error，
        # 详情完全改由 /v1/catalog/{id}/episodes 提供（它自带 title / episode_count）。
        result = []
        for vid in ids:
            export_id = str(vid)
            meta = {}
            episodes = []
            offset = 0
            while True:
                ep_data = self._api_get(
                    "/v1/catalog/" + export_id + "/episodes",
                    {"offset": offset, "limit": 100},
                )
                if not ep_data:
                    break
                if not meta:
                    meta = ep_data
                eps = ep_data.get("episodes", [])
                if not eps:
                    break
                episodes.extend(eps)
                ep_pag = ep_data.get("episode_pagination", {})
                if not ep_pag.get("has_more"):
                    break
                offset += len(eps)
                if offset >= (ep_pag.get("total_count") or 9999):
                    break

            if not episodes:
                continue

            card = self._cards.get(export_id, {})
            name = meta.get("title") or card.get("title") or card.get("normalized_title") or ""
            pic = card.get("poster_url") or card.get("backdrop_url") or ""
            content = card.get("description") or ""
            remark = card.get("remarks") or ""
            if not remark:
                cnt = meta.get("episode_count") or len(episodes)
                if (meta.get("content_kind") or "") == "series":
                    remark = str(cnt) + "集"
                elif card.get("year"):
                    remark = str(card.get("year"))

            # 用第 1 集解析出所有可用线路（provider 去重）
            line_names = []
            line_pids = []
            for ep in episodes:
                tok = ep.get("token") or ""
                if not tok:
                    continue
                lines = self._resolve_lines(tok)
                seen = set()
                for ln in lines:
                    nm = ln.get("provider_name") or "线路"
                    pid = ln.get("provider_id") or ""
                    if pid in seen:
                        continue
                    seen.add(pid)
                    line_names.append(nm)
                    line_pids.append(pid)
                break

            if not line_names:
                line_names = ["默认线路"]
                line_pids = [""]

            line_urls = []
            for idx in range(len(line_names)):
                plays = []
                for ei, ep in enumerate(episodes):
                    token = ep.get("token") or ""
                    if not token:
                        continue
                    ep_num = ep.get("number")
                    if ep_num is None:
                        ep_num = ei + 1
                    label = ep.get("title") or ep.get("key") or ("第%s集" % ep_num)
                    pid = line_pids[idx] if idx < len(line_pids) else ""
                    # 带上 vod_id 与集号：播放时主站不行就换懂片后端取同一集
                    plays.append("%s$%s|%s|%s" % (label, export_id, ep_num, pid))
                line_urls.append("#".join(plays) if plays else "")

            result.append({
                "vod_id": export_id,
                "vod_name": name,
                "vod_pic": pic,
                "vod_content": content,
                "vod_year": str(card.get("year") or ""),
                "vod_area": card.get("area") or "",
                "vod_director": "",
                "vod_actor": "",
                "vod_remarks": remark,
                "type_name": "",
                "vod_play_from": "$$$".join(line_names),
                "vod_play_url": "$$$".join(line_urls),
            })
        return {"list": result}

    def searchContent(self, key, quick, pg="1"):
        page = max(1, int(pg or 1))
        params = {"q": key, "page": str(page), "limit": "20"}
        data = self._api_get("/v1/browse/catalog", params)
        cards = data.get("cards", [])
        movies = [self._card_to_vod(c) for c in cards]
        pag = data.get("pagination", {})
        total = pag.get("total") or 0
        pagecount = max(total // 20 + (1 if total % 20 else 0), 1) if total else page
        return {
            "page": page,
            "pagecount": pagecount,
            "list": movies,
        }

    def _url_ok(self, url):
        """轻量校验 m3u8 是否真的能拉（避免把 403/失效链接交给播放器）"""
        try:
            r = self.session.get(url, headers={"User-Agent": self.ua,
                                               "Referer": self.host + "/"},
                                 timeout=8, stream=True, verify=False)
            code = r.status_code
            r.close()
            return code in (200, 206)
        except Exception:
            return False

    def playerContent(self, flag, id, vipFlags):
        raw = str(id)
        parts = raw.split("|")
        hdr = {"User-Agent": self.ua, "Referer": self.host + "/"}

        # 新格式: vod_id|集号|provider_id
        if len(parts) >= 3:
            vod_id, ep_num, pid = parts[0], parts[1], parts[2]
            url = self._line_url(self.host, self.secret, self.headers,
                                 vod_id, ep_num, pid)
            if url and self._url_ok(url):
                return {"parse": 0, "url": url, "header": hdr}
            # 主站链接不可播（多见于「专享4K-Y」）→ 换懂片后端重解析
            for dh in self.dp_hosts:
                u2 = self._line_url(dh, self.dp_key, self._dp_headers(dh),
                                    vod_id, ep_num, pid)
                if u2 and self._url_ok(u2):
                    return {"parse": 0, "url": u2, "header": hdr}
            return {"parse": 1, "url": self.host + "/player/" + vod_id,
                    "header": dict(self.headers)}

        # 兼容旧格式: token|provider_id
        token = parts[0]
        target_pid = parts[1] if len(parts) > 1 else ""
        data = self._api_get("/v1/playback/resolve/" + token)
        line_options = data.get("line_options", [])
        candidates = []
        if target_pid:
            for lo in line_options:
                if (lo.get("provider_id") or "") == target_pid:
                    candidates.append(lo)
                    break
        for lo in line_options:
            if lo in candidates:
                continue
            candidates.append(lo)
        for lo in candidates:
            url = str(lo.get("url") or "")
            mode = lo.get("resolve_mode") or ""
            kind = lo.get("url_kind") or ""
            direct = ""
            if mode == "direct" and url.startswith("http"):
                direct = url
            elif kind == "resolve_ticket" or url.startswith("resolve://"):
                direct = self._resolve_line_ticket(url.replace("resolve://", ""))
            if direct and self._url_ok(direct):
                return {"parse": 0, "url": direct, "header": hdr}
        return {"parse": 1, "url": self.host + "/player/" + token,
                "header": dict(self.headers)}
