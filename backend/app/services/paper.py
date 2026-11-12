"""Read an uploaded question paper (PDF, Word, Excel, text, photo) into plain text plus its pictures, for the AI to turn into questions.

The result is: text with a marker where each picture belongs ("[[IMAGE 3]]"), the pictures themselves (shrunk, re-encoded, as data URIs),
page pictures of scanned pages ("PAGE 2") and notes about whatever could not be read. Nothing is stored. The file is untrusted:
sizes and page counts are capped, a Word file's declared sizes are checked before it is opened, and every picture is decoded and
re-encoded by Pillow, so what leaves here is only ever a plain PNG or JPEG."""
from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

MAX_FILE = 20_000_000
MAX_PAGES = 50
MAX_TEXT = 120_000
MAX_IMAGES, MAX_SCANS, MAX_PICTURE_BYTES_TOTAL = 60, 20, 12_000_000
MIN_PX = 48            # smaller pictures are bullets and logos
SIDE, SCAN_SIDE = 1200, 1600
KINDS = {"pdf": "PDF", "docx": "Word", "xlsx": "Excel", "txt": "text", "csv": "text", "md": "text", "jpg": "photo", "jpeg": "photo", "png": "photo", "webp": "photo"}


class PaperError(ValueError):
    """A reason, in plain words, why this file cannot be used."""


# ---- pictures
def _open_picture(raw: bytes):
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("PNG", "JPEG", "GIF", "WEBP", "BMP", "TIFF") or img.width * img.height > 40_000_000:
            return None
        img.load()
        return img
    except Exception:  # a drawing format Pillow cannot read (EMF, WMF, SVG), or a broken picture
        return None


def _encode(img, side: int = SIDE, scan: bool = False) -> Optional[str]:
    """A data URI of at most 1 MB: PNG when it fits, else JPEG, getting smaller until it fits."""
    from PIL import Image
    img = img.convert("RGBA") if img.mode in ("P", "LA", "PA") or "transparency" in img.info else img
    if img.mode == "RGBA":
        flat = Image.new("RGB", img.size, "white")
        flat.paste(img, mask=img.getchannel("A"))
        img = flat
    img = img.convert("RGB")
    for s in (side, side * 3 // 4, side // 2, side // 3):
        small = img.copy()
        small.thumbnail((s, s))
        for fmt, mime, opts in ((("PNG", "png", {"optimize": True}),) if not scan else ()) + (("JPEG", "jpeg", {"quality": 78}),):
            buf = io.BytesIO()
            small.save(buf, fmt, **opts)
            if len(buf.getvalue()) <= 900_000:
                return f"data:image/{mime};base64," + base64.b64encode(buf.getvalue()).decode()
    return None


class _Collector:
    def __init__(self):
        self.images: List[Dict[str, Any]] = []
        self.scans: List[Dict[str, Any]] = []
        self.notes: List[str] = []
        self._seen: Dict[str, str] = {}
        self._bytes = 0

    def note(self, msg: str) -> None:
        if msg not in self.notes:
            self.notes.append(msg)

    def picture(self, raw: bytes, page: Optional[int] = None) -> Optional[str]:
        """Add a picture; returns its id ("IMAGE 3"), or None when it is too small, unreadable or over the limits."""
        img = _open_picture(raw)
        return self._add(img, page) if img is not None else None

    def _add(self, img, page) -> Optional[str]:
        if img.width < MIN_PX or img.height < MIN_PX:
            return None
        src = _encode(img)
        if not src:
            return None
        key = hashlib.sha1(src.encode()).hexdigest()
        if key in self._seen:
            return self._seen[key]
        if len(self.images) >= MAX_IMAGES or self._bytes + len(src) > MAX_PICTURE_BYTES_TOTAL:
            self.note("Some pictures were left out: the paper has more pictures than one upload can hold. Upload it in parts.")
            return None
        iid = f"IMAGE {len(self.images) + 1}"
        self.images.append({"id": iid, "src": src, "page": page})
        self._bytes += len(src)
        self._seen[key] = iid
        return iid

    def scan(self, img, page: int, detail: str = "high") -> Optional[str]:
        if len(self.scans) >= MAX_SCANS:
            self.note(f"Only the first {MAX_SCANS} pages that needed to be looked at as pictures were sent to the AI. Upload the rest separately.")
            return None
        src = _encode(img, SCAN_SIDE, scan=True)
        if not src:
            return None
        sid = f"PAGE {page}"
        self.scans.append({"id": sid, "src": src, "detail": detail})  # "low" is enough to see the layout; a scanned page has to be read, so "high"
        return sid


# ---- Word
_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "a": "http://schemas.openxmlformats.org/drawingml/2006/main", "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
       "v": "urn:schemas-microsoft-com:vml", "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006"}
W, R, M = ("{%s}" % _NS[k] for k in ("w", "r", "m"))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _on(el, tag: str) -> bool:
    """A formatting switch such as <w:b/>: on unless it says w:val=false/0/none."""
    x = el.find(f"w:{tag}", _NS) if el is not None else None
    return x is not None and x.get(W + "val", "true").lower() not in ("false", "0", "none", "off")


def _wrap(x: str) -> str:
    return x if re.fullmatch(r"[A-Za-z0-9]", x) else f"({x})"


def _omml(el) -> str:
    """Word's equation markup as plain text: (a)/(b), x^2, sqrt(x)."""
    t = _local(el.tag)
    kids = lambda e: "".join(_omml(c) for c in e)  # noqa: E731
    part = lambda name: (lambda x: kids(x) if x is not None else "")(el.find(f"m:{name}", _NS))  # noqa: E731
    if t.endswith("Pr"):
        return ""
    if t == "t":
        return el.text or ""
    if t == "f":
        return f"({part('num')})/({part('den')})"
    if t == "sSup":
        return _wrap(part("e")) + "^" + _wrap(part("sup"))
    if t == "sSub":
        return _wrap(part("e")) + "_" + _wrap(part("sub"))
    if t == "sSubSup":
        return _wrap(part("e")) + "_" + _wrap(part("sub")) + "^" + _wrap(part("sup"))
    if t == "rad":
        deg = part("deg").strip()
        return f"root({deg})({part('e')})" if deg and deg != "2" else f"sqrt({part('e')})"
    if t == "d":
        pr = el.find("m:dPr", _NS)
        beg = pr.find("m:begChr", _NS) if pr is not None else None
        end = pr.find("m:endChr", _NS) if pr is not None else None
        return (beg.get(M + "val", "(") if beg is not None else "(") + ", ".join(kids(e) for e in el.findall("m:e", _NS)) + (end.get(M + "val", ")") if end is not None else ")")
    if t == "nary":
        pr = el.find("m:naryPr/m:chr", _NS)
        sub, sup = part("sub"), part("sup")
        return (pr.get(M + "val", "") if pr is not None else "∫") + (f"_{_wrap(sub)}" if sub else "") + (f"^{_wrap(sup)}" if sup else "") + " " + part("e")
    if t == "func":
        return f"{part('fName')}({part('e')})"
    return kids(el)


class _Docx:
    def __init__(self, z: zipfile.ZipFile, pics: _Collector):
        self.z, self.pics = z, pics
        self.rels: Dict[str, str] = {}
        try:
            for rel in ET.fromstring(z.read("word/_rels/document.xml.rels")):
                self.rels[rel.get("Id", "")] = rel.get("Target", "")
        except (KeyError, ET.ParseError):
            pass

    def _blob(self, rid: str, page=None) -> str:
        target = self.rels.get(rid, "")
        name = target.lstrip("/") if target.startswith("/") else "word/" + target
        name = re.sub(r"[^/]+/\.\./", "", name)
        try:
            raw = self.z.read(name)
        except KeyError:
            return ""
        iid = self.pics.picture(raw)
        if iid:
            return f" [[{iid}]] "
        if name.lower().endswith((".emf", ".wmf", ".svg")) or not _open_picture(raw):
            self.pics.note("A drawing in the paper could not be read (it is a drawing, not a picture). Add it to the question with a screenshot after importing.")
            return " [[a drawing here could not be read]] "
        return ""  # a bullet or a logo

    def _pictures(self, el) -> str:
        out = ""
        for blip in el.iter("{%s}blip" % _NS["a"]):
            out += self._blob(blip.get(R + "embed", ""))
        for im in el.iter("{%s}imagedata" % _NS["v"]):
            out += self._blob(im.get(R + "id", ""))
        if any(_local(c.tag) == "chart" for c in el.iter()):
            self.pics.note("A chart made inside Word could not be read. Add it to the question with a screenshot after importing.")
            out += " [[a chart here could not be read]] "
        return out

    def _drawing(self, el) -> str:
        """The pictures in a drawing, and the words of its text boxes."""
        out = self._pictures(el)
        for box in el.iter(W + "txbxContent"):
            out += " [" + " ".join(x for x in (self._par(p) for p in box.iter(W + "p")) if x) + "] "
        return out

    def _run(self, r) -> str:
        text = ""
        for c in r:
            t = _local(c.tag)
            if t == "t":
                text += c.text or ""
            elif t == "tab":
                text += " "
            elif t in ("br", "cr"):
                text += "\n"
            elif t in ("drawing", "pict", "object"):
                text += self._drawing(c)
            elif t == "AlternateContent":  # the same drawing twice (new and old markup): read the new one
                ch = c.find("mc:Choice", _NS)
                text += self._drawing(ch) if ch is not None else ""
        pr = r.find("w:rPr", _NS)
        if not text.strip() or pr is None:
            return text
        if _on(pr, "b"):
            text = f"**{text}**"
        shd = pr.find("w:shd", _NS)
        hl = pr.find("w:highlight", _NS)
        if (hl is not None and hl.get(W + "val", "none") != "none") or (shd is not None and shd.get(W + "fill", "auto").lower() not in ("auto", "ffffff", "")):
            text = f"=={text}=="  # a marked option often is the right one
        va = pr.find("w:vertAlign", _NS)
        if va is not None and va.get(W + "val") == "superscript":
            text = "^" + _wrap(text.strip())
        elif va is not None and va.get(W + "val") == "subscript":
            text = "_" + _wrap(text.strip())
        return text

    def _walk(self, el) -> str:
        out = ""
        for c in el:
            t = _local(c.tag)
            if t == "r":
                out += self._run(c)
            elif t in ("oMath", "oMathPara"):
                out += " " + _omml(c) + " "
            elif t in ("hyperlink", "ins", "smartTag", "sdt", "sdtContent", "fldSimple"):
                out += self._walk(c)
        return out

    def _par(self, p) -> str:
        s = self._walk(p)
        return re.sub(r"(\*\*|==)(\s*)\1", r"\2", s).strip()  # runs that were split in the middle of a bold or marked piece are joined

    def _blocks(self, el):
        for c in el:
            if _local(c.tag) in ("sdt", "sdtContent"):  # a content control wraps paragraphs
                yield from self._blocks(c)
            else:
                yield c

    def body(self) -> str:
        root = ET.fromstring(self.z.read("word/document.xml"))
        body = root.find("w:body", _NS)
        if body is None:
            raise PaperError("This Word file has no text in it.")
        lines: List[str] = []
        for c in self._blocks(body):
            t = _local(c.tag)
            if t == "p":
                s = self._par(c)
                if s:
                    lines.append(("- " if c.find("w:pPr/w:numPr", _NS) is not None else "") + s)
            elif t == "tbl":
                for tr in c.iter(W + "tr"):
                    cells = [" ".join(x for x in (self._par(p) for p in tc.iter(W + "p")) if x) for tc in tr.findall("w:tc", _NS)]
                    if any(cells):
                        lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)


def _read_docx(data: bytes, pics: _Collector) -> Tuple[str, Optional[int]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if sum(i.file_size for i in z.infolist()) > 150_000_000 or any(i.file_size > 60_000_000 for i in z.infolist()):  # a zip bomb says so in its own index
            raise PaperError("This Word file is too large to read.")
        if "word/document.xml" not in z.namelist():
            raise PaperError("This does not look like a Word (.docx) file. Save it as .docx or PDF and try again.")
        return _Docx(z, pics).body(), None
    except zipfile.BadZipFile:
        raise PaperError("This does not look like a Word (.docx) file. Save it as .docx or PDF and try again.")
    except ET.ParseError:
        raise PaperError("This Word file is damaged and could not be read.")


# ---- PDF
def _char_below(tp, top: float) -> int:
    """Index of the first character that lies below `top` (a figure's top edge), or -1 when all the text is above it: the figure belongs just before it."""
    for i in range(tp.count_chars()):
        left, bottom, right, top_ = tp.get_charbox(i)
        if right > left and top_ > bottom and (bottom + top_) / 2 < top:
            return i
    return -1


def _read_pdf(data: bytes, pics: _Collector) -> Tuple[str, Optional[int]]:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:
        raise PaperError("This PDF could not be opened" + (" (it is password protected)." if "assword" in str(e) else ". It may be damaged."))
    n = len(pdf)
    if n > MAX_PAGES:
        raise PaperError(f"This PDF has {n} pages. Upload at most {MAX_PAGES} pages at a time.")
    # per page: the text exactly as pdfium gives it, and each figure with where it sits (just before the first line below the figure's top edge)
    info: List[Tuple[str, List[Tuple[int, Tuple[float, float], str]]]] = []
    seen_on: Dict[str, set] = {}
    for i in range(n):
        page = pdf[i]
        tp = page.get_textpage()
        full = tp.get_text_range() or ""
        found: List[Tuple[int, Tuple[float, float], str]] = []
        for obj in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=3):
            try:
                left, bottom, right, top = obj.get_bounds()
                if (right - left) * (top - bottom) >= 0.85 * page.get_width() * page.get_height():
                    continue  # a picture that fills the page is the page itself (a scan, a background), not a figure
                img = obj.get_bitmap(render=True).to_pil()
            except Exception:
                continue
            iid = pics._add(img, i + 1) if img.width >= MIN_PX and img.height >= MIN_PX else None
            if iid and all(f[2] != iid for f in found):
                at = _char_below(tp, top)
                found.append((len(full) if at < 0 else len(tp.get_text_range(0, at)), (-top, left), iid))
                seen_on.setdefault(iid, set()).add(i + 1)
        info.append((full, found))
    # the same picture on three or more pages is a letterhead or a watermark, not a figure
    decoration = {iid for iid, pg in seen_on.items() if len(pg) >= 3}
    pics.images = [im for im in pics.images if im["id"] not in decoration]
    texts: List[str] = []
    for i, (full, found) in enumerate(info):
        found = sorted(f for f in found if f[2] not in decoration)
        out, prev = [], 0
        for at, _, iid in found:  # the marker goes exactly where the figure sits in the page's text
            out += [full[prev:at], f"\n[[{iid}]]\n"]
            prev = at
        txt = re.sub(r"\n{3,}", "\n\n", ("".join(out) + full[prev:]).replace("\r\n", "\n")).strip()
        readable = len(re.sub(r"\[\[IMAGE \d+\]\]", "", txt).strip())
        head = f"--- Page {i + 1} ---\n"
        sid = None
        if readable < 25 or found:  # a page without text is a scan and has to be read; a page with figures is also shown (small) so the AI can see the layout
            sid = pics.scan(pdf[i].render(scale=1.6).to_pil(), i + 1, "high" if readable < 25 else "low")
        if readable < 25:
            texts.append(head + (f"[this page has no text; look at the picture {sid}]" if sid else "[this page has no readable text]"))
            continue
        texts.append(head + txt + (f"\n[the whole page is also shown as the picture {sid}]" if sid and found else ""))
    return "\n\n".join(texts), n


# ---- Excel, text, photo
def _read_xlsx(data: bytes, pics: _Collector) -> Tuple[str, Optional[int]]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception:
        raise PaperError("This Excel file could not be read. Save it as .xlsx and try again.")
    lines: List[str] = []
    for ws in wb.worksheets:
        lines.append(f"### Sheet: {ws.title}")
        by_row: Dict[int, List[str]] = {}
        for im in getattr(ws, "_images", []):
            try:
                row = im.anchor._from.row + 1
                iid = pics.picture(im._data())
            except Exception:
                continue
            if iid:
                by_row.setdefault(row, []).append(f"[[{iid}]]")
        for r, row in enumerate(ws.iter_rows(max_row=5000), 1):
            cells = ["" if c.value is None else str(c.value).strip() for c in row]
            if any(cells) or r in by_row:
                lines.append("| " + " | ".join(cells) + " |" + (" " + " ".join(by_row.get(r, [])) if r in by_row else ""))
    return "\n".join(lines), None


def _read_text(data: bytes, pics: _Collector) -> Tuple[str, Optional[int]]:
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), None


def _read_photo(data: bytes, pics: _Collector) -> Tuple[str, Optional[int]]:
    img = _open_picture(data)
    if img is None:
        raise PaperError("This picture could not be read. Use a JPG, PNG or WEBP photo.")
    sid = pics.scan(img, 1)
    return f"[a photo of the question paper: look at the picture {sid}]", 1


_READERS = {"pdf": _read_pdf, "docx": _read_docx, "xlsx": _read_xlsx, "txt": _read_text, "csv": _read_text, "md": _read_text,
            "jpg": _read_photo, "jpeg": _read_photo, "png": _read_photo, "webp": _read_photo}


def read_paper(filename: str, data: bytes) -> Dict[str, Any]:
    """Raises PaperError (a message for the examiner) when the file cannot be used."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if ext in ("doc", "xls", "ppt", "pptx"):
        raise PaperError(f"Old and presentation files cannot be read. Open it and use Save as .docx, .xlsx or PDF, then upload that.")
    if ext not in _READERS:
        raise PaperError("This kind of file cannot be read. Upload a PDF, Word (.docx), Excel (.xlsx), text (.txt) or a photo (.jpg, .png).")
    if not data:
        raise PaperError("The file is empty.")
    if len(data) > MAX_FILE:
        raise PaperError(f"The file is larger than {MAX_FILE // 1_000_000} MB. Upload it in parts.")
    pics = _Collector()
    text, pages = _READERS[ext](data, pics)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise PaperError("No text was found in this file.")
    if len(text) > MAX_TEXT:
        raise PaperError("This paper is too long to read in one go (about " + f"{len(text) // 1000}" + " thousand characters). Upload it in parts of about 40 questions.")
    return {"kind": KINDS[ext], "pages": pages, "text": text, "images": pics.images, "scans": pics.scans, "notes": pics.notes}


# ---- long papers are converted a few questions at a time: one call for a whole paper is slow and the model loses the structure
_STRONG = re.compile(r"(?m)^[\s*#]*(?:Q|Question)\.?\s*\d{1,3}\b")
_WEAK = re.compile(r"(?m)^[\s*#]*\d{1,3}\s*[.)]\s+\S")


def _pieces(text: str) -> List[str]:
    """A section's text cut into whole questions (at "Q12" or "12." starts), or into paragraphs when it has no numbering."""
    for rx in (_STRONG, _WEAK):
        cuts = [m.start() for m in rx.finditer(text)]
        if len(cuts) >= 2:
            cuts = [0] + [c for c in cuts if c > 0]
            return [text[a:b] for a, b in zip(cuts, cuts[1:] + [len(text)])]
    return [p + "\n\n" for p in re.split(r"\n{2,}", text) if p.strip()]


def split_paper(body: str, spans: List[Tuple[int, str]], limit: int = 6000, max_q: int = 8) -> Tuple[str, List[Dict[str, str]]]:
    """(the introduction before the first section heading, the parts to convert). A part is a few whole questions of one section
    ({title, text}); `spans` are (offset, title) of the section headings. A paper that fits `limit` is one part."""
    if len(body) <= limit:
        return "", [{"title": "", "text": body}]
    spans = sorted(spans)
    intro = body[:spans[0][0]] if spans else ""
    sections = [(t, body[s:(spans[i + 1][0] if i + 1 < len(spans) else len(body))]) for i, (s, t) in enumerate(spans)] if spans else [("", body)]
    parts: List[Dict[str, str]] = []
    for title, text in sections:
        cur, n = "", 0
        for piece in _pieces(text):
            if cur and (len(cur) + len(piece) > limit or n >= max_q):
                parts.append({"title": title, "text": cur})
                cur, n = "", 0
            cur += piece
            n += 1 if (_STRONG.match(piece) or _WEAK.match(piece)) else 0
        if cur.strip():
            parts.append({"title": title, "text": cur})
    return intro, parts
