# -*- coding: utf-8 -*-
# by @嗷呜
import sys

# ===== 内嵌 pyquery 兼容层（纯标准库） =====
# -*- coding: utf-8 -*-
"""极简 pyquery 兼容层：只实现脚本用到的 pq(html) / (sel) / items / text / attr / eq"""

import re as _re
from html.parser import HTMLParser as _HTMLParser

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _Node(object):
    __slots__ = ("tag", "attrs", "parent", "children")

    def __init__(self, tag=None, attrs=None, parent=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.parent = parent
        self.children = []

    @property
    def text(self):
        return "".join(c if isinstance(c, str) else c.text for c in self.children)

    def get(self, key, default=None):
        return self.attrs.get(key, default)

    def __bool__(self):
        return True

    def __repr__(self):
        return "<%s %s>" % (self.tag, self.attrs)

    def select(self, css):
        chain = _parse_chain(css)
        out = []
        for node in self._iter_nodes():
            if node is self:
                continue
            if _match_chain(node, chain, self):
                out.append(node)
        return out

    def select_one(self, css):
        chain = _parse_chain(css)
        for node in self._iter_nodes():
            if node is self:
                continue
            if _match_chain(node, chain, self):
                return node
        return None

    def _iter_nodes(self):
        yield self
        for c in self.children:
            if not isinstance(c, str):
                for n in c._iter_nodes():
                    yield n


def _parse_pred(body):
    body = body.strip()
    m = _re.match(r"([\w:-]+)\s*([*^$]?=)\s*(.*)$", body)
    if not m:
        key = body
        return lambda n: key in n.attrs
    key, op, val = m.group(1), m.group(2), m.group(3)
    val = val.strip()
    if len(val) >= 2 and val[0] in ("'", '"') and val[-1] == val[0]:
        val = val[1:-1]
    if op == "=":
        return lambda n: n.attrs.get(key, "") == val
    if op == "*=":
        return lambda n: val in n.attrs.get(key, "")
    if op == "^=":
        return lambda n: n.attrs.get(key, "").startswith(val)
    if op == "$=":
        return lambda n: n.attrs.get(key, "").endswith(val)
    return lambda n: key in n.attrs


def _parse_simple(sel):
    tag = None
    classes = []
    ids = []
    preds = []
    i = 0
    m = _re.match(r"([a-zA-Z][\w-]*)", sel)
    if m:
        tag = m.group(1).lower()
        i = m.end()
    elif sel.startswith("#"):
        pass
    while i < len(sel):
        c = sel[i]
        if c == ".":
            m = _re.match(r"\.([\w-]+)", sel[i:])
            if not m:
                i += 1
                continue
            classes.append(m.group(1))
            i += len(m.group(0))
        elif c == "#":
            m = _re.match(r"#([\w-]+)", sel[i:])
            if not m:
                i += 1
                continue
            ids.append(m.group(1))
            i += len(m.group(0))
        elif c == "[":
            end = sel.find("]", i)
            if end < 0:
                i += 1
                continue
            preds.append(_parse_pred(sel[i + 1:end]))
            i = end + 1
        else:
            i += 1
    return (tag, classes, ids, preds)


def _parse_chain(css):
    css = css.strip()
    css = _re.sub(r"\s*>\s*", " ", css)
    parts = [p for p in _re.split(r"\s+", css) if p]
    return [_parse_simple(p) for p in parts]


def _match_simple(node, simple):
    tag, classes, ids, preds = simple
    if tag and node.tag != tag:
        return False
    if ids and node.attrs.get("id") not in ids:
        return False
    node_classes = (node.attrs.get("class") or "").split()
    for c in classes:
        if c not in node_classes:
            return False
    for p in preds:
        if not p(node):
            return False
    return True


def _match_chain(node, chain, root):
    if not chain:
        return False
    if not _match_simple(node, chain[-1]):
        return False
    cur = node
    for i in range(len(chain) - 2, -1, -1):
        anc = cur.parent
        while anc is not None:
            if anc is root.parent:
                return False
            if _match_simple(anc, chain[i]):
                break
            anc = anc.parent
        else:
            return False
        if anc is None:
            return False
        cur = anc
    return True


class _Builder(_HTMLParser):
    def __init__(self):
        _HTMLParser.__init__(self, convert_charrefs=True)
        self.root = _Node("#document")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = _Node(tag.lower(), {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag.lower() not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        n = _Node(tag.lower(), {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)

    def handle_endtag(self, tag):
        tag = tag.lower()
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        if data:
            self.cur.children.append(data)


def _parse_html(markup):
    root = _Node("#document")
    if isinstance(markup, bytes):
        markup = markup.decode("utf-8", "replace")
    elif hasattr(markup, "decode"):
        markup = markup.decode("utf-8", "replace")
    b = _Builder()
    try:
        b.feed(markup if isinstance(markup, str) else str(markup))
        b.close()
    except Exception:
        pass
    root.children = b.root.children
    for c in root.children:
        if not isinstance(c, str):
            c.parent = root
    return root


class PyQuery(object):
    def __init__(self, nodes):
        self._nodes = list(nodes)

    def __len__(self):
        return len(self._nodes)

    def __iter__(self):
        return iter(self._nodes)

    def __bool__(self):
        return len(self._nodes) > 0

    def __getitem__(self, i):
        return PyQuery([self._nodes[i]])

    def __repr__(self):
        return "<PyQuery %d nodes>" % len(self._nodes)

    def __call__(self, selector):
        out = []
        for n in self._nodes:
            out.extend(n.select(selector))
        return PyQuery(out)

    def items(self):
        for n in self._nodes:
            yield PyQuery([n])

    def eq(self, i):
        try:
            return PyQuery([self._nodes[i]])
        except IndexError:
            return PyQuery([])

    def text(self):
        return " ".join(n.text for n in self._nodes)

    def attr(self, name):
        if not self._nodes:
            return None
        return self._nodes[0].attrs.get(name)

    def length(self):
        return len(self._nodes)


def pq(markup, *a, **kw):
    if isinstance(markup, PyQuery):
        return markup
    if isinstance(markup, str) and _re.match(r"^<", markup.strip()):
        return PyQuery([_parse_html(markup)])
    if isinstance(markup, (bytes, bytearray)):
        return PyQuery([_parse_html(markup)])
    # 字符串但不是 HTML：当成 HTML 解析（pyquery 也会这样做）
    return PyQuery([_parse_html(markup if isinstance(markup, str) else str(markup))])

# ===== 兼容层结束 =====

sys.path.append('..')
from base.spider import Spider
import base64


class Spider(Spider):

    def init(self, extend=""):
        pass

    def getName(self):
        return '🎬 4KAV'

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="134", "Google Chrome";v="134"',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'document',
        'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.8 Mobile/15E148 Safari/604.1'
    }

    host = "https://4k-av.com"

    def homeContent(self, filter):
        data=self.getpq()
        result = {}
        classes = []
        for k in list(data('#category ul li').items())[:-1]:
            classes.append({
                'type_name': k.text(),
                'type_id': k('a').attr('href')
            })
        result['class'] = classes
        result['list'] = self.getlist(data('#MainContent_scrollul ul li'),'.poster span')
        return result

    def homeVideoContent(self):
        try:
            data = self.getpq()
            return {'list': self.getlist(data('#MainContent_scrollul ul li'), '.poster span')}
        except Exception as e:
            print('homeVideoContent 异常:', e)
            return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        data=self.getpq(f"{tid}page-{pg}.html")
        result = {}
        result['list'] = self.getlist(data('#MainContent_newestlist .virow .NTMitem'))
        result['page'] = pg
        result['pagecount'] = 9999
        result['limit'] = 90
        result['total'] = 999999
        return result

    def detailContent(self, ids):
        data = self.getpq(ids[0])
        v = data('#videoinfo')
        vod = {
            'vod_name': data('#tophead h1').text().split(' ')[0],
            'type_name': v('#MainContent_tags.tags a').text(),
            'vod_year': v('#MainContent_videodetail.videodetail a').text(),
            'vod_remarks': v('#MainContent_titleh12 h2').text(),
            'vod_content': v('p.cnline').text(),
            'vod_play_from': '嗷呜',
            'vod_play_url': ''
        }
        vlist = data('#rtlist li')
        # rtlist 首项：剧集是当前集（span 带 stitle 或 EP 编号）；电影是"相关推荐"截图，不能当选集
        first_span = vlist.eq(0)('span')
        is_ep = ('stitle' in (first_span.attr('class') or '')) or ('EP' in (first_span.text() or ''))
        if vlist and is_ep:
            jn = f"{vod['vod_name']}_"
            c = [f"{jn}{i('span').text()}${i('a').attr('href')}" for i in list(vlist.items())[1:]]
            c.insert(0, f"{jn}{vlist.eq(0)('span').text()}${ids[0]}")
            vod['vod_play_url'] = '#'.join(c)
        else:
            vod['vod_play_url'] = f"{vod['vod_name']}${ids[0]}"
        return {'list': [vod]}

    def searchContent(self, key, quick, pg="1"):
        data=self.getpq(f"/s?k={key}")
        return {'list':self.getlist(data('#MainContent_newestlist .virow.search .NTMitem.Main'))}

    def playerContent(self, flag, id, vipFlags):
        try:
            data=self.getpq(id)
            p,url=0,data('#MainContent_videowindow source').attr('src')
            if not url:raise Exception("未找到播放地址")
        except Exception as e:
            p,url=1,f"{self.host}{id}"
        headers = {
            'origin': self.host,
            'referer': f'{self.host}/',
            'sec-ch-ua-platform': '"macOS"',
            'user-agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.8 Mobile/15E148 Safari/604.1',
        }
        return  {'parse': p, 'url': url, 'header': headers}

    def localProxy(self, param):
        pass

    def liveContent(self, url):
        pass

    def getlist(self,data,y='.resyear label[title="分辨率"]'):
        videos = []
        for i in data.items():
            href = i('.title a').attr('href') or ''
            if '/av/' in href:
                continue
            ns = i('.title h2').text().split(' ')
            videos.append({
                'vod_id': i('.title a').attr('href'),
                'vod_name': ns[0],
                'vod_pic': i('.poster img').attr('src'),
                'vod_remarks': ns[-1] if len(ns) > 1 else '',
                'vod_year': i(y).text()
            })
        return videos

    def getpq(self, path=''):
        url=f"{self.host}{path}"
        data=self.fetch(url,headers=self.headers).text
        try:
            return pq(data)
        except Exception as e:
            print(f"{str(e)}")
            return pq(data.encode('utf-8'))
