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
        self.hosts = ["https://www.baipiaozhe.com", "https://baipiaozhe.com", "https://ai.baipiaozhe.com"]
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
        """resolve first episode token to discover multi-line providers"""
        data = self._api_get("/v1/playback/resolve/" + ep_token)
        line_options = data.get("line_options", [])
        direct_lines = []
        for lo in line_options:
            if lo.get("resolve_mode") == "direct" and lo.get("url_kind") == "m3u8":
                url = lo.get("url", "")
                if url and url.startswith("http"):
                    direct_lines.append({
                        "provider_id": lo.get("provider_id") or "",
                        "provider_name": lo.get("provider_name") or lo.get("display_label") or lo.get("label") or "",
                    })
        direct_lines.sort(key=lambda x: x.get("provider_name", ""))
        return direct_lines

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
                for ep in episodes:
                    token = ep.get("token") or ""
                    if not token:
                        continue
                    label = ep.get("title") or ep.get("key") or str(ep.get("number") or len(plays) + 1)
                    pid = line_pids[idx] if idx < len(line_pids) else ""
                    plays.append(label + "$" + token + "|" + pid)
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

    def playerContent(self, flag, id, vipFlags):
        # id format: token|provider_id  (multi-line) or token (fallback)
        raw = str(id)
        parts = raw.split("|", 1)
        token = parts[0]
        target_pid = parts[1] if len(parts) > 1 else ""

        data = self._api_get("/v1/playback/resolve/" + token)
        line_options = data.get("line_options", [])

        # try to match the specific provider line
        m3u8_url = ""
        if target_pid:
            for lo in line_options:
                if lo.get("resolve_mode") == "direct" and lo.get("url_kind") == "m3u8":
                    if lo.get("provider_id") == target_pid:
                        url = lo.get("url", "")
                        if url and url.startswith("http"):
                            m3u8_url = url
                            break

        # fallback: first available direct m3u8
        if not m3u8_url:
            for lo in line_options:
                if lo.get("resolve_mode") == "direct" and lo.get("url_kind") == "m3u8":
                    url = lo.get("url", "")
                    if url and url.startswith("http"):
                        m3u8_url = url
                        break

        # last fallback: any direct url
        if not m3u8_url:
            for lo in line_options:
                if lo.get("resolve_mode") == "direct":
                    url = lo.get("url", "")
                    if url and url.startswith("http"):
                        m3u8_url = url
                        break

        if m3u8_url:
            return {
                "parse": 0,
                "url": m3u8_url,
                "header": {"User-Agent": self.ua},
            }

        return {
            "parse": 1,
            "url": self.host + "/player/" + token,
            "header": dict(self.headers),
        }
