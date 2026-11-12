"""Allow-list HTML sanitiser for rich-text answers and question bodies (stdlib only)."""
from __future__ import annotations

import base64
import binascii
import html
import re
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


# ---- pictures: they live inside the question as data URIs (nothing to store, nothing to fetch in an exam)
MAX_PICTURE_BYTES, MAX_PICTURES = 1_000_000, 4
_DATA_IMG = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=\s]+)$")


def image_problem(src) -> str:
    """Empty when `src` is a picture we accept (a PNG, JPEG, GIF or WEBP data URI up to 1 MB that really decodes); otherwise why not."""
    m = _DATA_IMG.match(src or "") if isinstance(src, str) else None
    if not m:
        return "a picture must be a PNG, JPEG, GIF or WEBP image added to the question (not a link)"
    try:
        n = len(base64.b64decode(m.group(2), validate=False))
    except (binascii.Error, ValueError):
        return "a picture could not be read"
    return f"a picture is larger than {MAX_PICTURE_BYTES // 1_000_000} MB" if n > MAX_PICTURE_BYTES else ""


def picture_problems(body_html: str) -> list:
    """Every problem with the pictures in a question text: how many, and each one."""
    srcs = re.findall(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']*)[\"']", body_html or "", re.I)
    out = [f"at most {MAX_PICTURES} pictures per question text"] if len(srcs) > MAX_PICTURES else []
    out += sorted({m for m in map(image_problem, srcs) if m})
    return out
