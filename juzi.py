# -*- coding: utf-8 -*-
# 橘汁诊断版：在 Newbox 里测旧域名/新域名哪个能连，结果显示成分类名
import json, time, urllib.request, ssl

try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass

OLD = "http://202.189.6.51:18004"
NEW = "https://juziapp.hzhcbkj.cn"
UA = "okhttp/3.12.1"
CTX = ssl._create_unverified_context()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    return urllib.request.urlopen(req, timeout=8, context=CTX).read()


class Spider(_Base):
    HOST_NAME = "橘汁诊断"

    def getName(self):
        return "橘汁诊断"

    def init(self, extend=""):
        pass

    def homeContent(self, f):
        res = []
        # 1 旧域名 getCategory (http)
        try:
            d = _get(OLD + "/api/v3/drama/getCategory?orderBy=type_id")
            n = len(json.loads(d).get("data") or [])
            res.append("旧域名: 通(%d分类)" % n)
        except Exception as e:
            res.append("旧域名: 失败 %s" % str(e)[:22])
        # 2 新域名 getCategory (https)
        try:
            d = _get(NEW + "/api/v3/drama/getCategory?orderBy=type_id")
            n = len(json.loads(d).get("data") or [])
            res.append("新域名: 通(%d分类)" % n)
        except Exception as e:
            res.append("新域名: 失败 %s" % str(e)[:22])
        return {"class": [{"type_id": str(i + 1), "type_name": x} for i, x in enumerate(res)]}

    def categoryContent(self, tid, pg, f, ext):
        return {"list": [], "page": 1, "pagecount": 1}
