# -*- coding: utf-8 -*-
# 橘汁中文名诊断：零网络，验证 Newbox 能否加载中文名 py 并执行 homeContent
try:
    from base.spider import Spider as _Base
except Exception:
    class _Base:
        pass


class Spider(_Base):
    HOST_NAME = "橘汁诊断"

    def getName(self):
        return "橘汁中文名诊断"

    def init(self, extend=""):
        pass

    def homeContent(self, f):
        return {"class": [
            {"type_id": "1", "type_name": "PY_OK 中文名加载成功"},
            {"type_id": "2", "type_name": "homeContent 已执行"},
        ]}

    def categoryContent(self, tid, pg, f, ext):
        return {"list": [], "page": 1, "pagecount": 1}
