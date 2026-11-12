"""The question paper format people can download (Word and text), built from one description so the two never differ.

The Word file holds real sample pictures (drawn here with Pillow), so an examiner sees exactly how a picture sits under a question
and after an option label. Nothing is stored: the file is made when it is asked for."""
from __future__ import annotations

import io
import zipfile
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape

# A block is (kind, text, picture): kind "h" = a section heading, "b" = bold line, "p" = plain line, "n" = a note to the writer; picture is a key of PICTURES or None.
Block = Tuple[str, str, Optional[str]]

BLOCKS: List[Block] = [
    ("b", "Write your exam title here (this line is only a title)", None),
    ("n", "=== NOTES FOR THE WRITER (the upload ignores everything up to the END OF NOTES line; you may delete it or leave it) ===", None),
    ("n", "1. One heading per section, on its own line: Section A: Quantitative Aptitude (9 marks).", None),
    ("n", "2. Number every question with a Q and a number (Q1, Q2, Q3 ...) followed by a full stop, and put the marks at the end of the question line: [1 mark] or [8 marks].", None),
    ("n", "3. A picture (graph, figure, diagram, table drawn as a picture) goes on a line that starts with the word Image:, right under the question text and before the options. Put the picture on that line, or right under it. In Word, insert it inline with the text: Insert > Pictures, with the cursor on the Image: line.", None),
    ("n", "4. Options go one per line, with a letter: (a) (b) (c) (d). If an option is a picture, write (a) Image: and put the picture there. Options can also be text.", None),
    ("n", "5. The answer goes right after the question: Answer: (b). Several right options: Answer: (a), (c). A written question: Answer: followed by the model answer.", None),
    ("n", "6. A coding question: the statement, then Sample answer (Python): and the program (keep the indentation), then Test cases: one per line, open: or hidden: followed by the input. A very large case can be described, for example: hidden: 50000 opening and 50000 closing round brackets. If you leave the sample answer out, the platform writes one and marks it for you to check.", None),
    ("n", "7. An SQL question: the statement, then Tables: (the CREATE TABLE statements), Sample data: (the INSERT statements), Answer: (the correct query) and Hidden data: (write it, or describe it).", None),
    ("n", "8. Instead of writing the answers under each question you can put them all together at the end, under the heading Answer Key and Solutions with the line For the examiner only. Pictures there are never shown to candidates.", None),
    ("n", "=== END OF NOTES ===", None),
    ("h", "Section A: Quantitative Aptitude (2 marks)", None),
    ("p", "Q1. A train 180 m long crosses a pole in 12 seconds. What is its speed? [1 mark]", None),
    ("p", "(a) 10 m/s", None), ("p", "(b) 15 m/s", None), ("p", "(c) 20 m/s", None), ("p", "(d) 25 m/s", None),
    ("p", "Answer: (b)", None),
    ("p", "Q2. Refer to the bar chart. By what percentage did sales rise from March to April? [1 mark]", None),
    ("p", "Image:", "bar"),
    ("p", "(a) 25%", None), ("p", "(b) 45%", None), ("p", "(c) 55.6%", None), ("p", "(d) 62.5%", None),
    ("p", "Answer: (c)", None),
    ("h", "Section B: Logical Reasoning (1 mark)", None),
    ("p", "Q3. Which figure completes the series: circle, square, ...? [1 mark]", None),
    ("p", "(a) Image:", "circle"), ("p", "(b) Image:", "cross"), ("p", "(c) Image:", "triangle"), ("p", "(d) Image:", "square"),
    ("p", "Answer: (c)", None),
    ("h", "Section C: English (1 mark)", None),
    ("p", "Q4. Choose the word closest in meaning to EPHEMERAL. [1 mark]", None),
    ("p", "(a) Eternal", None), ("p", "(b) Short-lived", None), ("p", "(c) Fragile", None), ("p", "(d) Obvious", None),
    ("p", "Answer: (b)", None),
    ("h", "Section D: Coding (8 marks)", None),
    ("p", "Q5. Balanced Brackets [8 marks]", None),
    ("p", "A string made only of ( ) [ ] { } is balanced if every opening bracket is closed by the same type of bracket, in the correct order. Write a program that tells whether the given string is balanced.", None),
    ("p", "Image:", "stack"),
    ("p", "Input format", None), ("p", "One line containing the string s.", None),
    ("p", "Output format", None), ("p", "Print YES if the string is balanced, otherwise print NO.", None),
    ("p", "Constraints", None), ("p", "1 <= |s| <= 100000.", None),
    ("p", "Sample answer (Python):", None),
    ("p", "s = input().strip()", None), ("p", "pairs = {')': '(', ']': '[', '}': '{'}", None), ("p", "stack = []", None), ("p", "for ch in s:", None),
    ("p", "    if ch in '([{':", None), ("p", "        stack.append(ch)", None), ("p", "    elif not stack or stack.pop() != pairs[ch]:", None),
    ("p", "        print('NO')", None), ("p", "        break", None), ("p", "else:", None), ("p", "    print('YES' if not stack else 'NO')", None),
    ("p", "Test cases:", None),
    ("p", "open: {[()]}", None), ("p", "open: ([)]", None), ("p", "hidden: ()[]{}", None), ("p", "hidden: (((", None),
    ("p", "hidden: 50000 opening round brackets followed by 50000 closing round brackets", None),
    ("h", "Section E: SQL (9 marks)", None),
    ("p", "Q6. Employees earning more than 50000 [9 marks]", None),
    ("p", "Write one SQLite query that returns the names of employees who earn more than 50000, in alphabetical order.", None),
    ("p", "Image:", "tables"),
    ("p", "Output format", None), ("p", "One column: name.", None),
    ("p", "Tables:", None),
    ("p", "CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, salary INTEGER);", None),
    ("p", "Sample data:", None),
    ("p", "INSERT INTO employees VALUES (1,'Asha',60000),(2,'Ben',40000),(3,'Chen',55000);", None),
    ("p", "Answer:", None),
    ("p", "SELECT name FROM employees WHERE salary > 50000 ORDER BY name", None),
    ("p", "Hidden data: a salary of exactly 50000 (must not appear); two names that sort differently by capital letters.", None),
]


# ---- the sample pictures
def _pictures():
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=14)

    def canvas(w, h):
        im = Image.new("RGB", (w, h), "white")
        return im, ImageDraw.Draw(im)

    out = {}
    im, d = canvas(360, 220)
    d.line([(40, 15), (40, 185), (340, 185)], fill="black", width=2)
    for k, (v, name) in enumerate(((40, "Jan"), (55, "Feb"), (45, "Mar"), (70, "Apr"), (60, "May"), (80, "Jun"))):
        x = 55 + k * 45
        d.rectangle([x, 185 - v * 2, x + 30, 185], fill="#2f6fb5")
        d.text((x + 2, 190), name, fill="black", font=font)
        d.text((x + 6, 185 - v * 2 - 18), str(v), fill="black", font=font)
    d.text((100, 4), "Monthly sales (thousands)", fill="black", font=font)
    out["bar"] = im
    for key in ("circle", "square", "triangle", "cross"):
        im, d = canvas(120, 120)
        if key == "circle":
            d.ellipse([15, 15, 105, 105], outline="#d9381e", width=6)
        elif key == "square":
            d.rectangle([15, 15, 105, 105], outline="#1e8449", width=6)
        elif key == "triangle":
            d.polygon([(60, 12), (108, 105), (12, 105)], outline="#2f6fb5", width=6)
        else:
            d.line([(15, 15), (105, 105)], fill="black", width=6)
            d.line([(105, 15), (15, 105)], fill="black", width=6)
        out[key] = im
    im, d = canvas(300, 150)
    for k, ch in enumerate("{[("):
        d.rectangle([20 + k * 60, 100 - k * 30, 70 + k * 60, 130 - k * 30 + 0], outline="#2f6fb5", width=2)
        d.text((40 + k * 60, 105 - k * 30), ch, fill="black", font=font)
    d.text((20, 8), "Stack after reading { [ (   (bottom to top)", fill="black", font=font)
    out["stack"] = im
    im, d = canvas(320, 140)
    for x, name, cols in ((20, "departments", ["dept_id (PK)", "dept_name"]), (190, "employees", ["id (PK)", "name", "salary"])):
        d.rectangle([x, 15, x + 110, 125], outline="#2f6fb5", width=2)
        d.rectangle([x, 15, x + 110, 38], fill="#2f6fb5")
        d.text((x + 6, 19), name, fill="white", font=font)
        for k, c in enumerate(cols):
            d.text((x + 8, 46 + k * 22), c, fill="black", font=font)
    d.line([(130, 60), (190, 60)], fill="#d9381e", width=2)
    out["tables"] = im
    return out


def format_text() -> str:
    """The same paper as plain text: a picture is written as "Image: [picture]" so the shape is clear even without a Word file."""
    lines: List[str] = []
    for kind, text, pic in BLOCKS:
        if kind in ("h", "b"):
            lines += ["", text, "-" * min(len(text), 60)] if kind == "h" else ["", text]
        else:
            lines.append(text + (" [the picture goes here]" if pic else ""))
    return "\n".join(lines).strip() + "\n"


# ---- the Word file (stdlib zip + XML; pictures inline)
_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
       'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
       'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


def _run(text: str, bold: bool = False, italic: bool = False, size: Optional[int] = None) -> str:
    props = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "") + (f'<w:sz w:val="{size}"/>' if size else "")
    return f'<w:r>{"<w:rPr>" + props + "</w:rPr>" if props else ""}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _inline(n: int, rid: str, w: int, h: int) -> str:
    cx, cy = w * 9525, h * 9525
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{n}" name="Picture {n}" descr="Example picture {n}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{n}" name="picture{n}.png"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')


def format_docx() -> bytes:
    pics = _pictures()
    media, rels, body = {}, [], []
    for kind, text, key in BLOCKS:
        runs = _run(text, bold=kind in ("h", "b"), italic=kind == "n", size=28 if kind == "h" else None)
        if key:
            if key not in media:
                buf = io.BytesIO()
                pics[key].save(buf, "PNG")
                media[key] = (f"rId{100 + len(media)}", f"picture_{key}.png", buf.getvalue(), pics[key].size)
            rid, _, _, (w, h) = media[key]
            runs += _run(" ") + _inline(len(media) * 10 + len(body), rid, w, h)
        body.append(f"<w:p>{runs}</w:p>")
    rels = "".join(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{name}"/>' for rid, name, _, _ in media.values())
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_NS}><w:body>{"".join(body)}'
                   '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for _, name, data, _ in media.values():
            z.writestr("word/media/" + name, data)
    return out.getvalue()
