"""Allow-list HTML sanitiser for rich-text answers and question bodies (stdlib only)."""
from __future__ import annotations

import html
from html.parser import HTMLParser

ALLOWED = {"p", "br", "b", "strong", "i", "em", "u", "s", "ul", "ol", "li", "h1", "h2", "h3", "h4", "pre", "code",
           "blockquote", "table", "thead", "tbody", "tr", "th", "td", "a", "span", "div", "sub", "sup", "hr", "img"}
VOID = {"br", "hr", "img"}
ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "width", "height"}, "td": {"colspan", "rowspan"},
         "th": {"colspan", "rowspan"}, "code": {"class"}, "pre": {"class"}, "span": {"class"}}


class _S(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "iframe", "object", "embed"):
            self.skip += 1
            return
        if tag not in ALLOWED or self.skip:
            return
        keep = []
        for k, v in attrs:
            if k in ATTRS.get(tag, set()) and v is not None:
                if k in ("href", "src") and not (v.startswith(("http://", "https://", "/", "#")) or
                                                 (tag == "img" and v.startswith("data:image/"))):
                    continue
                keep.append(f'{k}="{html.escape(v, quote=True)}"')
        self.out.append(f"<{tag}{' ' + ' '.join(keep) if keep else ''}>")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "iframe", "object", "embed"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in ALLOWED and tag not in VOID and not self.skip:
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def sanitize_html(s: str) -> str:
    p = _S()
    p.feed(s or "")
    p.close()
    return "".join(p.out)
