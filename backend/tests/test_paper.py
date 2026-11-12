"""Uploading a question paper: reading Word / PDF / Excel / text / photo files with their pictures, the AI step (replaced here by a fixed answer),
the ordinary check and import after it, and the picture rules every way of saving a question shares."""
import base64
import re
import io
import os
import zipfile

import pytest
from PIL import Image
from test_exam_pack import _bank_count, _creator, _exam, _import  # noqa: F401
from test_exam_rules import DEPT, PW, _login, client  # noqa: F401  (client is a fixture)

from app.api import exam_pack
from app.services.paper import PaperError, read_paper

API = "/api/v1"
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"')


def png(w=300, h=200, colour="red") -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(b, "PNG")
    return b.getvalue()


def data_uri(raw=None) -> str:
    return "data:image/png;base64," + base64.b64encode(raw or png()).decode()


def docx(body: str, media: dict = None) -> bytes:
    rels = "".join(f'<Relationship Id="{k}" Target="media/{v[0]}"/>' for k, v in (media or {}).items())
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {NS}><w:body>{body}</w:body></w:document>')
        z.writestr("word/_rels/document.xml.rels", f'<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for _, (name, raw) in (media or {}).items():
            z.writestr("word/media/" + name, raw)
    return out.getvalue()


def p(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def r(text: str, props: str = "") -> str:
    return f"<w:r>{'<w:rPr>' + props + '</w:rPr>' if props else ''}<w:t>{text}</w:t></w:r>"


def blip(rid: str) -> str:
    return f'<w:r><w:drawing><a:blip r:embed="{rid}"/></w:drawing></w:r>'


# ---------------------------------------------------------------- reading files
def test_a_word_paper_keeps_its_order_marks_pictures_tables_and_maths():
    body = (p(r("1. Which is prime?")) + p(r("4")) + p(r("7", "<w:b/>")) + p(r("9", '<w:highlight w:val="yellow"/>'))
            + p(r("Look at "), blip("rId1"), r(" and "), blip("rId2"))
            + p(r("x"), r("2", '<w:vertAlign w:val="superscript"/>'), r(" and "), "<m:oMath><m:f><m:num><m:r><m:t>a</m:t></m:r></m:num><m:den><m:r><m:t>b</m:t></m:r></m:den></m:f></m:oMath>")
            + '<w:tbl><w:tr><w:tc>' + p(r("x")) + '</w:tc><w:tc>' + p(r("y")) + '</w:tc></w:tr></w:tbl>' + p(r("last")))
    out = read_paper("paper.docx", docx(body, {"rId1": ("a.png", png(3000, 2000)), "rId2": ("b.png", png(20, 20)), }))
    t = out["text"]
    assert t.index("Which is prime") < t.index("**7**") < t.index("==9==") < t.index("[[IMAGE 1]]") < t.index("| x | y |") < t.index("last")
    assert "x^2" in t and "(a)/(b)" in t
    assert [i["id"] for i in out["images"]] == ["IMAGE 1"]          # the 20 px picture is a bullet or a logo: dropped, not numbered
    img = Image.open(io.BytesIO(base64.b64decode(out["images"][0]["src"].split(",", 1)[1])))
    assert max(img.size) == 1200 and img.format in ("PNG", "JPEG")  # shrunk and re-encoded
    assert out["kind"] == "Word" and out["scans"] == []


def test_a_drawing_that_cannot_be_read_is_said_so_not_hidden():
    out = read_paper("p.docx", docx(p(r("Q1 "), blip("rId1")), {"rId1": ("fig.emf", b"\x01\x00\x00\x00 not a picture")}))
    assert "could not be read" in out["text"] and out["notes"] and out["images"] == []


def test_a_pdf_with_text_and_a_picture_and_a_scanned_pdf():
    raw = bytes((x * 5 % 256, y * 5 % 256, (x + y) % 256)[c] for y in range(60) for x in range(60) for c in range(3))
    stream = b"BT /F1 12 Tf 20 250 Td (1. Which is prime? A 4 B 7 C 9 D 12) Tj ET q 100 0 0 100 20 100 cm /Im1 Do Q"
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>/XObject<</Im1 6 0 R>>>>>>",
            b"<</Length %d>>stream\n" % len(stream) + stream + b"\nendstream", b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
            b"<</Type/XObject/Subtype/Image/Width 60/Height 60/ColorSpace/DeviceRGB/BitsPerComponent 8/Length %d>>stream\n" % len(raw) + raw + b"\nendstream"]
    pdf = b"%PDF-1.4\n" + b"".join(b"%d 0 obj\n" % (i + 1) + o + b"\nendobj\n" for i, o in enumerate(objs)) + b"trailer<</Root 1 0 R/Size 7>>\n%%EOF"
    out = read_paper("paper.pdf", pdf)
    assert "Which is prime" in out["text"] and "Page 1" in out["text"] and out["pages"] == 1 and out["kind"] == "PDF"
    assert [i["id"] for i in out["images"]] == ["IMAGE 1"] and "IMAGE 1" in out["text"]
    assert [s["id"] for s in out["scans"]] == ["PAGE 1"]            # a page with a figure is also shown to the AI whole

    b = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(b, "PDF")
    scan = read_paper("scan.pdf", b.getvalue())
    assert "PAGE 1" in scan["text"] and [s["id"] for s in scan["scans"]] == ["PAGE 1"] and scan["images"] == []


def test_excel_text_and_photo_papers():
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XlImage
    wb = Workbook()
    ws = wb.active
    ws.title = "Questions"
    ws.append(["No", "Question", "A", "B", "Answer"])
    ws.append([1, "2+2?", 3, 4, "B"])
    ws.append([2, "Which figure?", "", "", "A"])
    ws.add_image(XlImage(io.BytesIO(png(200, 150))), "B3")
    b = io.BytesIO()
    wb.save(b)
    out = read_paper("q.xlsx", b.getvalue())
    assert "### Sheet: Questions" in out["text"] and "| 1 | 2+2? | 3 | 4 | B |" in out["text"]
    assert out["text"].splitlines()[-1].endswith("[[IMAGE 1]]") and len(out["images"]) == 1  # the picture is on the row it sits on

    assert read_paper("q.txt", "caf\xe9 question".encode("cp1252"))["text"] == "caf\xe9 question"   # Notepad's own encoding
    photo = read_paper("q.jpg", png(400, 600))                                                     # (a PNG under a .jpg name is still read by what it is)
    assert photo["kind"] == "photo" and [s["id"] for s in photo["scans"]] == ["PAGE 1"]


@pytest.mark.parametrize("name,data,words", [
    ("old.doc", b"x", "Save as"), ("old.xls", b"x", "Save as"), ("deck.pptx", b"x", "Save as"), ("a.exe", b"x", "cannot be read"), ("noext", b"x", "cannot be read"),
    ("e.txt", b"", "empty"), ("e.docx", b"not a zip at all", "Word"), ("e.pdf", b"not a pdf", "PDF"), ("e.xlsx", b"nope", "Excel"), ("e.png", b"nope", "picture"),
    ("long.txt", b"word " * 30_000, "too long"), ("blank.txt", b"   \n  ", "No text"),
])
def test_files_that_cannot_be_used_get_a_plain_reason(name, data, words):
    with pytest.raises(PaperError) as e:
        read_paper(name, data)
    assert words in str(e.value)


def test_a_zip_bomb_is_refused_before_it_is_opened():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * 61_000_000)
    assert len(out.getvalue()) < 1_000_000
    with pytest.raises(PaperError, match="too large"):
        read_paper("bomb.docx", out.getvalue())
    with pytest.raises(PaperError, match="larger than 20 MB"):
        read_paper("big.txt", b"x" * 20_000_001)


# ---------------------------------------------------------------- the endpoints
def _paper_pack(images):
    """What the AI would answer for a paper with one figure question and one question whose options are pictures."""
    a, b = images
    return {"sections": [{"title": "Aptitude", "questions": [
        {"type": "mcq_single", "title": "Graph", "statement": "What does the graph show at x = 2?", "images": [a, "IMAGE 99"],
         "options": ["1", "2", "3"], "correct": ["b"], "marks": 2, "answer_from_ai": True},
        {"type": "mcq_single", "title": "Figure", "statement": "Which figure comes next?", "options": [{"text": "A", "image": b}, {"text": "B", "image": b}, {"text": "C", "image": "IMAGE 98"}],
         "correct": ["a"]}]}], "notes": ["The paper has a chart on page 3 that could not be read."]}


def _fake_ai(monkeypatch, make, why="stop"):
    seen = {}

    def fake(system, msg, pictures):
        import json
        seen.update(system=system, msg=msg, pictures=pictures)
        return json.dumps(make(pictures)), why
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", fake)
    return seen


def _understand(client, h, tid, text="1. Q", images=(), scans=()):
    return client.post(f"{API}/tests/{tid}/understand-paper", headers=h, json={"text": text, "images": [{"id": i, "src": s} for i, s in images], "scans": [{"id": i, "src": s} for i, s in scans]})


def test_reading_and_understanding_a_paper_then_the_ordinary_check_and_import(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Paper exam")
    up = client.post(f"{API}/tests/{t['id']}/read-paper", headers=h, files={"file": ("paper.docx", docx(p(r("1. Q "), blip("rId1")), {"rId1": ("a.png", png())}))})
    assert up.status_code == 200 and up.json()["images"][0]["id"] == "IMAGE 1" and "[[IMAGE 1]]" in up.json()["text"]
    assert client.post(f"{API}/tests/{t['id']}/read-paper", headers=h, files={"file": ("x.doc", b"x")}).status_code == 422

    one, two = data_uri(png(100, 80, "blue")), data_uri(png(90, 90, "green"))
    seen = _fake_ai(monkeypatch, lambda pics: _paper_pack(("IMAGE 1", "IMAGE 2")))
    ai = _understand(client, h, t["id"], "1. Q\n2. Q", images=[("IMAGE 1", one), ("IMAGE 2", two)], scans=[("PAGE 1", one)])
    assert ai.status_code == 200, ai.text
    got = ai.json()
    assert [x[0] for x in seen["pictures"]] == ["IMAGE 1", "IMAGE 2", "PAGE 1 (a whole page of the paper)"] and [x[2] for x in seen["pictures"]] == ["low", "low", "high"]
    assert "<<<PAPER" in seen["msg"] and "Technical" in seen["system"] and '"type": "coding"' in seen["system"]
    q1, q2 = got["pack"]["sections"][0]["questions"]
    assert q1["images"] == [one] and q2["options"][0]["image"] == two and q2["options"][2]["image"] == ""   # ids became pictures; an unknown id was dropped
    assert any("chart on page 3" in n for n in got["notes"]) and sum("does not exist" in n for n in got["notes"]) == 2
    assert "notes" not in got["pack"]

    # step 3 is the ordinary check; the review also gets each question's text, options and who chose the answer
    pack = got["pack"]
    q2["options"][2] = {"text": "C", "image": ""}
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": pack, "dry_run": True, "detail": True}).json()
    assert rep["ok"], rep["errors"]
    a, b = rep["sections"][0]["questions"]
    assert a["answer_from_ai"] is True and b["answer_from_ai"] is False and "<img" in a["body"] and a["options"][1]["correct"]
    assert b["options"][0]["image"] == two and b["options"][2]["image"] == ""
    assert _bank_count(client, h, "Figure") == 0                                                # the dry run saved nothing
    done = _import(client, h, t["id"], pack, dry_run=False)
    assert done.status_code == 200 and done.json()["question_count"] == 2
    bank = client.get(f"{API}/questions", headers=h, params={"q": "Figure"}).json()
    full = client.get(f"{API}/questions/{bank[0]['id']}", headers=h).json()
    assert full["config"]["options"][0]["image"] == two and "image" not in full["config"]["options"][2]


def test_a_problem_is_reported_against_its_question(client):
    h = _creator(client)
    t = _exam(client, h, title="Problem exam")
    pack = {"sections": [{"title": "S", "questions": [{"type": "mcq_single", "title": "ok", "statement": "?", "options": ["a", "b"], "correct": ["a"]},
                                                      {"type": "mcq_single", "title": "bad", "statement": "?", "options": ["a", "b"], "correct": ["z"]}]}]}
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": pack, "dry_run": True, "detail": True}).json()
    assert not rep["ok"] and rep["problems"] == [{"section": 1, "question": 2, "message": "correct answer 'z' is not one of the options (a, b)"}]
    assert rep["sections"][0]["count"] == 1 and rep["sections"][0]["questions"][0]["title"] == "ok"


def test_the_ai_step_fails_with_a_reason_and_only_for_authors_of_draft_exams(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Reasons exam")
    assert _understand(client, h, t["id"]).status_code == 503                      # the test server has the AI switched off: a plain reason, not a crash
    assert "not switched on" in _understand(client, h, t["id"]).json()["detail"]

    _fake_ai(monkeypatch, lambda pics: {"sections": []}, why="length")
    assert "too long" in _understand(client, h, t["id"]).json()["detail"] and _understand(client, h, t["id"]).status_code == 422
    _fake_ai(monkeypatch, lambda pics: {"nothing": 1})
    assert _understand(client, h, t["id"]).status_code == 502
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda *a: ("this is not json", "stop"))
    assert _understand(client, h, t["id"]).status_code == 502

    _fake_ai(monkeypatch, lambda pics: _paper_pack(("IMAGE 1", "IMAGE 1")))
    assert _understand(client, h, t["id"], text="   ").status_code == 422
    assert _understand(client, h, t["id"], images=[("IMAGE 1", "https://example.com/a.png")]).status_code == 422   # only pictures we made, never a link
    assert _understand(client, h, t["id"], images=[("IMAGE 1", data_uri())]).status_code == 200

    staff = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    for call in (lambda: _understand(client, staff, t["id"]), lambda: client.post(f"{API}/tests/{t['id']}/read-paper", headers=staff, files={"file": ("a.txt", b"x")})):
        assert call().status_code == 403
    assert client.post(f"{API}/tests/{t['id']}/read-paper", files={"file": ("a.txt", b"x")}).status_code in (401, 403)

    hr = _exam(client, h, "HR", "Published exam")
    pack = {"sections": [{"questions": [{"type": "short", "title": "t", "statement": "s", "model_answer": "m"}]}]}
    assert _import(client, h, hr["id"], pack, dry_run=False).status_code == 200
    assert client.post(f"{API}/tests/{hr['id']}/publish", headers=h).status_code == 200
    assert _understand(client, h, hr["id"]).status_code == 409
    assert client.post(f"{API}/tests/{hr['id']}/read-paper", headers=h, files={"file": ("a.txt", b"x")}).status_code == 409


# ---------------------------------------------------------------- pictures in the editor, the JSON route and anywhere else a question is saved
def _mcq(client, h, body="<p>Q</p>", options=None, status=200):
    options = options or [{"id": "a", "text": "one", "correct": True}, {"id": "b", "text": "two", "correct": False}]
    r = client.post(f"{API}/questions", headers=h, json={"department_id": DEPT["Technical"], "type": "mcq_single", "title": "Pic q", "body": body,
                                                         "marks": 1, "config": {"options": options, "partial": True}})
    assert r.status_code == status, r.text
    return r


def test_picture_rules_hold_for_every_way_of_saving_a_question(client):
    h = _creator(client)
    img = f'<p><img src="{data_uri()}" alt="Picture 1"></p>'
    saved = _mcq(client, h, "<p>Q</p>" + img).json()
    assert "<img" in saved["body"] and "data:image/png" in saved["body"]                      # kept by the sanitiser
    assert "<img" in client.get(f"{API}/questions/{saved['id']}", headers=h).json()["body"]

    bad = lambda *msg: any(m in _mcq(client, h, *msg, status=422).text for m in ("picture",))  # noqa: E731
    assert bad('<p><img src="https://example.com/a.png"></p>')                                 # a link, not a picture
    assert bad('<p><img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="></p>')               # SVG can carry scripts
    assert bad("".join(f'<img src="{data_uri()}">' for _ in range(5)))                         # more than 4
    assert bad(f'<img src="{data_uri(png(1500, 1500) + bytes(1_100_000))}">')                  # over 1 MB
    assert bad('<img src="data:image/png;base64,***">')
    opts = [{"id": "a", "text": "", "correct": True}, {"id": "b", "text": "  ", "correct": False}]
    assert "Option 1 needs a text or a picture" in _mcq(client, h, options=opts, status=422).text
    assert "Option 1" in _mcq(client, h, options=[{"id": "a", "text": "x", "image": "https://x/y.png", "correct": True}, {"id": "b", "text": "y"}], status=422).text
    ok = [{"id": "a", "text": "", "image": data_uri(), "correct": True}, {"id": "b", "text": "B", "correct": False}]
    assert _mcq(client, h, options=ok).json()["config"]["options"][0]["image"].startswith("data:image/png")  # an option that is only a picture is fine


def test_editing_a_question_keeps_its_pictures_and_the_candidate_gets_them_without_the_key(client):
    from app.models import Question
    from app.services.attempts import candidate_question
    h = _creator(client)
    ok = [{"id": "a", "text": "", "image": data_uri(), "correct": True}, {"id": "b", "text": "B", "correct": False}]
    q = _mcq(client, h, "<p>Q</p>" + f'<img src="{data_uri()}">', options=ok).json()
    from types import SimpleNamespace
    row = SimpleNamespace(question=SimpleNamespace(id=q["id"], type="mcq_single", title="t", body=q["body"], difficulty="easy", skills=[], group_id=None,
                                                   config={"options": q["config"]["options"], "partial": True}),
                          marks=1, negative=0, section_id="s", order=0, option_order=["b", "a"])
    out = candidate_question(row, None)
    assert [o["id"] for o in out["options"]] == ["b", "a"] and out["options"][1]["image"].startswith("data:image/png") and out["options"][0]["image"] == ""
    assert all("correct" not in o for o in out["options"]) and "<img" in out["body"]
    assert Question  # imported to make sure the model still loads with these tests


def test_the_ai_is_told_where_each_picture_sits_and_the_examiner_is_told_about_loose_ones(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Loose picture exam")
    one, two = data_uri(png(100, 80, "blue")), data_uri(png(90, 90, "green"))
    pack = {"sections": [{"title": "mcq_single", "questions": [{"type": "mcq_single", "title": "Graph", "statement": "What is shown?", "options": ["a", "b"], "correct": ["a"]}]}]}
    seen = _fake_ai(monkeypatch, lambda pics: pack)   # the AI attaches nothing and names its section after a type code
    text = "1. What is shown?\n[[IMAGE 1]]\nA) a\nB) b\n[[IMAGE 2]]"
    got = _understand(client, h, t["id"], text, images=[("IMAGE 1", one), ("IMAGE 2", two)]).json()
    assert 'IMAGE 1 comes right after: "1. What is shown? /"' in seen["msg"] and "WHERE THE PICTURES ARE" in seen["msg"]
    assert got["pack"]["sections"][0]["title"] == "Multiple choice"                      # never a code as a title
    q = got["pack"]["sections"][0]["questions"][0]                                       # both pictures follow the question in the paper, so both belong to it (not left loose)
    assert len(q["images"]) == 2 and not any("not attached" in n for n in got["notes"])
    assert "WHERE THE PICTURES ARE" not in _fake_and_msg(client, h, t, monkeypatch)       # a paper without pictures has no such block


def _fake_and_msg(client, h, t, monkeypatch):
    seen = _fake_ai(monkeypatch, lambda pics: {"sections": [{"title": "S", "questions": []}]})
    _understand(client, h, t["id"], "1. Q")
    return seen["msg"]


def test_markers_the_ai_copies_into_the_text_become_pictures(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Marker exam")
    one, two = data_uri(png(100, 80, "blue")), data_uri(png(90, 90, "green"))
    pack = {"sections": [{"title": "Reasoning", "questions": [
        {"type": "mcq_single", "title": "Graph", "statement": "What does the graph show? [[IMAGE 1]] Be exact. [[IMAGE 1]]", "options": ["a", "b"], "correct": ["a"]},
        {"type": "mcq_single", "title": "Figures", "statement": "Which figure?", "options": ["A [[IMAGE 2]]", {"text": "[[IMAGE 2]]"}, "no picture"], "correct": ["a"]}]}]}
    _fake_ai(monkeypatch, lambda pics: pack)
    got = _understand(client, h, t["id"], "text", images=[("IMAGE 1", one), ("IMAGE 2", two)]).json()
    q1, q2 = got["pack"]["sections"][0]["questions"]
    assert q1["statement"] == "<p>What does the graph show?</p><p><b>Be exact.</b></p>" and q1["images"] == [one]          # said twice, attached once
    assert q2["options"][0] == {"text": "A", "image": two} and q2["options"][1] == {"text": "", "image": two} and q2["options"][2] == "no picture"
    assert not any("not attached" in n for n in got["notes"])                                         # both pictures were used
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got["pack"], "dry_run": True, "detail": True}).json()
    assert rep["ok"], rep["errors"]


def _pdf(items, size=(300, 400)):
    """A one-page PDF: items are ("text", x, y, words) or ("image", x, y, side, (r, g, b))."""
    content, imgs = b"", []
    for it in items:
        if it[0] == "text":
            content += b"BT /F1 11 Tf %d %d Td (%s) Tj ET\n" % (it[1], it[2], it[3].encode())
        else:
            imgs.append(bytes(it[4][c] if (x + y) % 7 else (c * 40) % 256 for y in range(it[3]) for x in range(it[3]) for c in range(3)))
            content += b"q %d 0 0 %d %d %d cm /Im%d Do Q\n" % (it[3], it[3], it[1], it[2], len(imgs))
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 %d %d]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>/XObject<<%s>>>>>>" % (size[0], size[1], b"".join(b"/Im%d %d 0 R" % (n + 1, 6 + n) for n in range(len(imgs)))),
            b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream", b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    for n, raw in enumerate(imgs):
        w = int(len(raw) ** 0.5 / 3 ** 0.5)
        objs.append(b"<</Type/XObject/Subtype/Image/Width %d/Height %d/ColorSpace/DeviceRGB/BitsPerComponent 8/Length %d>>stream\n" % (w, w, len(raw)) + raw + b"\nendstream")
    return b"%PDF-1.4\n" + b"".join(b"%d 0 obj\n" % (i + 1) + o + b"\nendobj\n" for i, o in enumerate(objs)) + b"trailer<</Root 1 0 R/Size %d>>\n%%%%EOF" % (len(objs) + 1)


def test_in_a_pdf_each_figure_is_marked_at_its_own_place_between_the_questions():
    pdf = _pdf([("text", 20, 380, "Q1. Refer to the chart. What is the total?"), ("image", 20, 290, 70, (200, 30, 30)),
                ("text", 20, 270, "(a) 10  (b) 20"), ("text", 20, 250, "Q2. Which figure comes next in the series?"),
                ("image", 20, 160, 70, (30, 30, 200)), ("text", 20, 140, "(a) A  (b) B"), ("text", 20, 120, "Q3. A question with no figure at all?"),
                ("text", 20, 100, "(a) yes  (b) no")])
    out = read_paper("p.pdf", pdf)
    t = out["text"]
    assert [i["id"] for i in out["images"]] == ["IMAGE 1", "IMAGE 2"]
    assert t.index("Q1.") < t.index("[[IMAGE 1]]") < t.index("(a) 10") < t.index("Q2.") < t.index("[[IMAGE 2]]") < t.index("(a) A") < t.index("Q3.")
    assert [s["detail"] for s in out["scans"]] == ["low"]                                   # the layout page is shown small; only a scan is read closely
    b = io.BytesIO()
    Image.new("RGB", (600, 800), "white").save(b, "PDF")
    assert read_paper("scan.pdf", b.getvalue())["scans"][0]["detail"] == "high"


def test_loose_answers_from_the_ai_are_accepted_not_refused(client):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Loose exam")
    coding = {"type": "Coding", "title": "Sum", "statement": "Read two integers, print their sum.", "marks": "8 marks", "difficulty": "Easy",
              "time_limit_ms": None, "memory_mb": "256 MB", "languages": "python", "reference": {"language": "python", "source": "a, b = map(int, input().split())\nprint(a + b)\n"},
              "test_cases": [{"input": "2 3", "visibility": "open"}, {"input": "4 5", "visibility": "hidden"}]}
    mcq = {"type": "Multiple Choice", "title": "Prime", "statement": "Which is prime?", "options": ["4", "7"], "correct": "(B)", "marks": "1"}
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": {"sections": [{"title": "S", "questions": [mcq, coding]}]}, "dry_run": True, "detail": True}).json()
    assert rep["ok"], rep["errors"]
    q = rep["sections"][0]["questions"]
    assert [x["type"] for x in q] == ["mcq_single", "coding"] and q[1]["marks"] == 8 and q[0]["options"][1]["correct"]
    nonsense = dict(coding, time_limit_ms="fast")                                              # a real mistake is still said
    assert "'time_limit_ms' must be a number" in client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": {"sections": [{"questions": [nonsense]}]}}).json()["errors"][0]


def test_headings_and_the_answer_key_are_read_off_the_paper_before_the_ai_sees_it(client, monkeypatch):
    from app.api.exam_pack import _paper_facts
    pad = "Instructions. " * 20
    body = (pad + "\n**Section A: Quantitative Aptitude (9 marks)**\nQ1. What is shown? [[IMAGE 1]]\nSection Content Questions Marks\nSection B: English (7 marks)\nQ2. Solutions must be short.\n"
            "Answer Key and Solutions\nFor the examiner only.\n[[IMAGE 2]] the green bars\nDetailed solutions: Sections A and B\n")
    text, key, heads = _paper_facts(body)
    assert heads == ["Section A: Quantitative Aptitude", "Section B: English"]              # the table header and the key's own headings are not sections
    assert text.rstrip().endswith("Solutions must be short.") and key.startswith("Answer Key and Solutions")

    h = _creator(client)
    t = _exam(client, h, "Technical", "Key exam")
    seen = _fake_ai(monkeypatch, lambda pics: {"sections": [{"title": "S", "questions": [{"type": "mcq_single", "title": "Q", "statement": "What is shown?", "options": ["a", "b"], "correct": ["a"]}]}]})
    one, two = data_uri(png(100, 80, "blue")), data_uri(png(90, 90, "green"))
    got = _understand(client, h, t["id"], body, images=[("IMAGE 1", one), ("IMAGE 2", two)]).json()
    assert [x[0] for x in seen["pictures"]] == ["IMAGE 1"]                                    # the key's picture (it shows the answer) never goes to the AI as a question picture
    assert "SECTION HEADINGS FOUND IN THE PAPER" in seen["msg"] and "- Section B: English" in seen["msg"]
    assert 'THE ANSWER KEY STARTS AT THE HEADING "Answer Key and Solutions"' in seen["msg"] and "[[IMAGE 2]]" not in seen["msg"]
    assert not any("IMAGE 2" in n for n in got["notes"])                                      # and it is not reported as a forgotten picture
    assert not any("IMAGE 1" in n for n in got["notes"]) and got["pack"]["sections"][0]["questions"][0]["images"] == [one]   # IMAGE 1 follows its question


def test_a_question_the_ai_forgot_to_word_is_asked_for_once_more(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Retry exam")
    q = {"type": "mcq_single", "title": "Prime", "statement": "Which is prime?", "options": ["4", "7"], "correct": ["b"]}
    calls = []

    def fake(system, msg, pictures):
        import json
        calls.append(msg)
        return json.dumps({"sections": [{"title": "S", "questions": [q if len(calls) > 1 else {k: v for k, v in q.items() if k != "statement"}]}]}), "stop"
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", fake)
    got = _understand(client, h, t["id"]).json()
    assert len(calls) == 2 and 'HAD NO "statement"' in calls[1] and "Prime" in calls[1]
    assert got["pack"]["sections"][0]["questions"][0]["statement"] == "<p><b>Which is prime?</b></p>"
    calls.clear()
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: (calls.append(m) or '{"sections": [{"questions": [{"type": "mcq_single", "title": "Still none"}]}]}', "stop"))
    assert _understand(client, h, t["id"]).status_code == 200 and len(calls) == 2           # asks once, not forever; the review then shows the problem


BRACKETS = ("s = input().strip()\npairs = {')': '(', ']': '[', '}': '{'}\nst = []\nfor ch in s:\n    if ch in '([{':\n        st.append(ch)\n"
            "    elif not st or st.pop() != pairs[ch]:\n        print('NO')\n        break\nelse:\n    print('YES' if not st else 'NO')\n")


def _coding(cases, **extra):
    return {"type": "coding", "title": "Balanced Brackets", "statement": "Tell whether the brackets in s are balanced. Print YES or NO.", "marks": 8,
            "reference": {"language": "python", "source": BRACKETS}, "test_cases": cases, **extra}


def test_a_big_case_is_made_by_a_program_and_a_described_case_is_left_out_with_a_note(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Generator exam")
    cases = [{"input": "{[()]}", "visibility": "open", "purpose": "sample"}, {"input": "([)]", "visibility": "open"},
             {"generator": {"language": "python", "source": "print('(' * 3000 + ')' * 3000)"}, "visibility": "hidden", "purpose": "maximum size, deeply nested"},
             {"input": "(generated) maximum size, deeply nested", "visibility": "hidden", "purpose": "a description, not an input"}]
    _fake_ai(monkeypatch, lambda pics: {"sections": [{"title": "Coding", "questions": [_coding(cases)]}]})
    got = _understand(client, h, t["id"]).json()
    kept = got["pack"]["sections"][0]["questions"][0]["test_cases"]
    assert [c["visibility"] for c in kept] == ["open", "open", "hidden"] and len(kept[2]["input"]) >= 6000 and kept[2]["input"].startswith("(((")
    assert any("test case 4 was left out" in n and "could not run on it" in n for n in got["notes"])           # (no AI in this test: nothing can make it)

    from app.services import ai                                                              # with an AI, the described case gets one try at a generator program
    monkeypatch.setattr(ai, "ai_generator_program", lambda *a, **k: "print('[' * 2000 + ']' * 2000)")
    again = _understand(client, h, t["id"]).json()
    kept = again["pack"]["sections"][0]["questions"][0]["test_cases"]
    assert [c["visibility"] for c in kept] == ["open", "open", "hidden", "hidden"] and kept[3]["input"].startswith("[[[")
    assert any("test case 4 was only a description" in n for n in again["notes"])
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got["pack"], "dry_run": True, "detail": True}).json()
    assert rep["ok"], rep["errors"]                                                          # what is left passes the ordinary check, expected outputs from the reference

    # a generator that prints nothing, and a reference that cannot run at all, are not hidden: the first is left out, the second is the ordinary check's to explain
    broken = [{"input": "()", "visibility": "open"}, {"generator": {"language": "python", "source": "raise SystemExit(3)"}, "visibility": "hidden"}]
    _fake_ai(monkeypatch, lambda pics: {"sections": [{"questions": [_coding(broken)]}]})
    assert any("generator program did not produce an input" in n for n in _understand(client, h, t["id"]).json()["notes"])


def test_hidden_data_the_paper_only_describes_is_written_and_checked_against_the_reference(client, monkeypatch):
    from app.services import ai
    h = _creator(client)
    t = _exam(client, h, "Technical", "Missing hidden exam")
    sql = {"type": "sql", "title": "Well paid", "statement": "Names of employees earning over 50000, alphabetically.", "marks": 9, "schema": "CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, salary INTEGER);",
           "reference_sql": "SELECT name FROM employees WHERE salary > 50000 ORDER BY name",
           "datasets": [{"data": "INSERT INTO employees VALUES (1,'Asha',60000),(2,'Ben',40000);", "visibility": "open"}]}
    coding = _coding([{"input": "{[()]}", "visibility": "open"}, {"input": "([)]", "visibility": "open"}])
    _fake_ai(monkeypatch, lambda pics: {"sections": [{"title": "Both", "questions": [coding, sql]}]})
    monkeypatch.setattr(ai, "ai_generate_inputs", lambda *a, **k: [{"input": "((()))", "purpose": "nested"}, {"input": "(x", "purpose": "crashes the reference"}])
    monkeypatch.setattr(ai, "ai_generate_sql_datasets", lambda *a, **k: [{"data": "INSERT INTO employees VALUES (1,'Zed',50000),(2,'Amy',50001);", "purpose": "a tie at the limit"},
                                                                          {"data": "INSERT INTO nothing VALUES (1);", "purpose": "broken"}])
    got = _understand(client, h, t["id"]).json()
    c, s = got["pack"]["sections"][0]["questions"]
    assert [x["visibility"] for x in c["test_cases"]] == ["open", "open", "hidden"] and c["test_cases"][2]["input"] == "((()))"   # the input the reference cannot run on is not kept
    assert [d["visibility"] for d in s["datasets"]] == ["open", "hidden"] and "Zed" in s["datasets"][1]["data"]                    # the dataset that does not fit the schema is not kept
    assert any("no hidden test cases, so 1 were written" in n for n in got["notes"]) and any("no hidden data, so 1 dataset(s)" in n for n in got["notes"])
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got["pack"], "dry_run": True, "detail": True}).json()
    assert rep["ok"], rep["errors"]

    # no AI available for the repair: nothing is invented, the ordinary check says what is missing
    monkeypatch.setattr(ai, "ai_generate_sql_datasets", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no AI")))
    monkeypatch.setattr(ai, "ai_generate_inputs", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no AI")))
    got = _understand(client, h, t["id"]).json()
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got["pack"], "dry_run": True}).json()
    assert not rep["ok"] and sum("at least 1 sample" in e for e in rep["errors"]) == 2


def test_a_long_paper_is_converted_part_by_part_and_joined_again(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Long paper exam")
    sec = lambda c: f"Section {c}: Part {c}\n" + "".join(f"Q{c}{i}. Question number {i} " + "word " * 140 + "\n(a) one\n(b) two\n" for i in range(1, 8))  # noqa: E731
    paper = "Instructions for everyone. " * 5 + "\n" + sec("A") + sec("B") + sec("C") + "Answer Key and Solutions\nFor the examiner only.\nQA1 (a)\n"
    msgs = []

    def fake(system, msg, pictures):
        import json
        msgs.append(msg)
        part = int(msg.split("PART ")[1].split(" ")[0])
        title = msg.split('SECTION "')[1].split('"')[0]
        qs = [{"type": "mcq_single", "title": f"{title} q{i}", "statement": f"Question {i}", "options": ["a", "b"], "correct": ["a"]} for i in range(2)]
        return json.dumps({"sections": [{"title": "whatever", "questions": qs}], "paper_question_count": 7, "notes": [f"part {part} done"]}), "stop"
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", fake)
    got = _understand(client, h, t["id"], paper).json()
    assert len(msgs) == 3 and all("OF 3 OF THE PAPER" in m and "QA1 (a)" in m and "Instructions for everyone" in m for m in msgs)   # each part gets the key and the introduction
    assert [s["title"] for s in got["pack"]["sections"]] == ["Section A: Part A", "Section B: Part B", "Section C: Part C"]            # the paper's headings, whatever the AI called them
    assert [len(s["questions"]) for s in got["pack"]["sections"]] == [2, 2, 2]
    assert sorted(n for n in got["notes"] if n.startswith("part")) == ["part 1 done", "part 2 done", "part 3 done"]
    assert any("counted 21 questions in the paper but returned 6" in n for n in got["notes"])


GARBLED = ('{"format": "x", "sections": [{"title": "Coding", "questions": [{"type": "mcq_single", "title": "Q", "statement": "What \\"is\\" {this}?", "options": ["a", "b"], "correct": ["a"]}]}],'
           ' "notes�: []}  ```  ```  ```  ```  ```  ```')


def test_a_reply_that_garbles_its_end_and_loops_is_salvaged_not_thrown_away(client, monkeypatch):
    from app.services.ai import OpenAIProvider, salvage_json
    assert salvage_json(GARBLED)["sections"][0]["questions"][0]["statement"] == 'What "is" {this}?'           # braces and quotes inside strings do not fool it
    assert salvage_json("no json here") is None and salvage_json('{"sections": [{"title": "S", "questions": [{"type": "sho') is None   # nothing complete yet
    assert salvage_json('{"a": [1, 2, {"b": 3}') == {"a": [1, 2, {"b": 3}]}

    h = _creator(client)
    t = _exam(client, h, "Technical", "Garbled exam")
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: (GARBLED, "stop"))
    got = _understand(client, h, t["id"]).json()
    assert len(got["pack"]["sections"][0]["questions"]) == 1 and any("garbled near its end" in n for n in got["notes"])
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: (GARBLED, "length"))                  # cut off by the limit: what is complete is kept, and the examiner is told
    got = _understand(client, h, t["id"]).json()
    assert len(got["pack"]["sections"][0]["questions"]) == 1 and any("cut off" in n for n in got["notes"])
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda s, m, p: ("```  ```  ```", "length"))           # nothing usable at all: the old plain refusal
    assert _understand(client, h, t["id"]).status_code == 422

    sent = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.update(kw["json"]) or R())
    OpenAIProvider("k", "m").look_and_complete("s", "u", [("IMAGE 1", "data:image/png;base64,AA==", "low")])
    assert sent["stop"] == ["```"] and sent["response_format"] == {"type": "json_object"}                     # the loop is cut at the first code fence


def test_pictures_go_to_the_question_they_follow_even_when_the_ai_attaches_them_wrongly(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Placement exam")
    pics = {f"IMAGE {n}": data_uri(png(60 + n, 60, c)) for n, c in enumerate(["red", "green", "blue", "orange", "purple", "gray"], 1)}
    paper = ("Instructions. " * 20 + "\nSection A: Reasoning\n"
             "Q1. Refer to the bar chart. What is the total sales in March?\n[[IMAGE 1]]\n(a) 10\n(b) 20\n"
             "Q2. Which figure completes the series of shapes?\nA) [[IMAGE 2]]\nB) [[IMAGE 3]]\nC) [[IMAGE 4]]\n"
             "Q3. Choose the word closest in meaning to EPHEMERAL.\n(a) short\n(b) long\n"
             "Q4. Refer to the family tree. How is Arun related to Gita?\n[[IMAGE 5]]\n(a) father\n(b) uncle\n"
             "Answer Key and Solutions\nFor the examiner only.\n[[IMAGE 6]] the green bars\n")
    q = lambda title, st, **kw: {"type": "mcq_single", "title": title, "statement": st, "options": kw.pop("options", ["a", "b"]), "correct": ["a"], **kw}  # noqa: E731
    wrong = [q("Q1", "Refer to the bar chart. What is the total sales in March?", images=["IMAGE 5"]),                                  # a picture that belongs to Q4
             q("Q2", "Which figure completes the series of shapes?", images=["IMAGE 1"], options=["A", "B", "C"]),                   # option pictures forgotten, question picture invented
             q("Q3", "Choose the word closest in meaning to EPHEMERAL.", images=["IMAGE 2", "IMAGE 3"]),                            # pictures on a question without any
             q("Q4", "Refer to the family tree. How is Arun related to Gita?")]                                                      # picture forgotten
    _fake_ai(monkeypatch, lambda p: {"sections": [{"title": "Section A: Reasoning", "questions": wrong}]})
    got = _understand(client, h, t["id"], paper, images=[(i, s) for i, s in pics.items()]).json()
    q1, q2, q3, q4 = got["pack"]["sections"][0]["questions"]
    assert q1["images"] == [pics["IMAGE 1"]] and "images" not in q3 and q4["images"] == [pics["IMAGE 5"]] and "images" not in q2
    assert [o.get("image") for o in q2["options"]] == [pics["IMAGE 2"], pics["IMAGE 3"], pics["IMAGE 4"]]                       # A) B) C) are the options' pictures, in order
    assert all("image" not in o for o in q3["options"])
    assert not any("IMAGE 6" in n for n in got["notes"])                                                                         # the key's picture is never offered
    assert [x["title"] for x in got["pack"]["sections"][0]["questions"]][:2] == ["Refer to the bar chart. What is the total...", "Which figure completes the series of shapes?"]  # "Q1" is not a title
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got["pack"], "dry_run": True, "detail": True}).json()
    assert rep["ok"], rep["errors"]


def test_a_question_that_cannot_be_found_in_the_paper_keeps_what_the_ai_said_and_the_text_gets_a_shape(client, monkeypatch):
    from app.api.exam_pack import _structure
    h = _creator(client)
    t = _exam(client, h, "Technical", "Shape exam")
    one = data_uri(png(100, 80, "blue"))
    pack = {"sections": [{"title": "S", "questions": [{"type": "mcq_single", "title": "Reworded", "statement": "Something the paper never said.<br>Second line", "images": ["IMAGE 1"], "options": ["a", "b"], "correct": ["a"]}]}]}
    _fake_ai(monkeypatch, lambda p: pack)
    got = _understand(client, h, t["id"], "1. A completely different text\n[[IMAGE 1]]", images=[("IMAGE 1", one)]).json()
    q = got["pack"]["sections"][0]["questions"][0]
    assert q["images"] == [one] and q["statement"] == "<p>Something the paper never said.</p><p><b>Second line</b></p>"

    coding = ("A string made only of brackets is balanced if each is closed.\nInput format\nOne line containing the string s.\nOutput format: Print YES or NO.\n"
              "Constraints\n1 <= |s| <= 100000.\nSample\n  {[()]}  \n")
    assert _structure(coding, "coding") == ("<p>A string made only of brackets is balanced if each is closed.</p><p><b>Input format</b></p><p>One line containing the string s.</p>"
                                           "<p><b>Output format:</b> Print YES or NO.</p><p><b>Constraints</b></p><p>1 &lt;= |s| &lt;= 100000.</p><p><b>Sample</b></p><p>{[()]}</p>")
    sql = ("Write one query for every department.\nOutput format\nTwo columns.\nSample data (schema and data are provided on the platform)\nCREATE TABLE d (\n id INTEGER\n);\n"
           "INSERT INTO d VALUES (1);\nNote: departments with no employees must not appear.")
    out = _structure(sql, "sql")
    assert "CREATE" not in out and "INSERT" not in out and "Sample data" not in out and "<b>Output format</b>" in out and out.endswith("<p><b>Note:</b> departments with no employees must not appear.</p>")
    assert _structure("<p>Already <b>html</b></p>", "mcq_single") == "<p>Already <b>html</b></p>"
    assert "<pre>SELECT 1;</pre>" in _structure("Try this:\nSELECT 1;", "sql")


def test_the_downloadable_paper_format_is_a_real_word_file_with_pictures_that_the_upload_reads_correctly(client, monkeypatch):
    from app.services import paper_format
    h = _creator(client)
    docx_r = client.get(f"{API}/help/paper-format.docx", headers=h)
    txt_r = client.get(f"{API}/help/paper-format.txt", headers=h)
    assert docx_r.status_code == 200 and docx_r.content[:2] == b"PK" and "wordprocessingml" in docx_r.headers["content-type"] and "attachment" in docx_r.headers["content-disposition"]
    assert txt_r.status_code == 200 and "Image: [the picture goes here]" in txt_r.text and txt_r.text.count("[the picture goes here]") == paper_format.format_text().count("[the picture goes here]") == 7
    assert client.get(f"{API}/help/paper-format.docx").status_code in (401, 403)                      # staff only, like the rest of Help
    with zipfile.ZipFile(io.BytesIO(docx_r.content)) as z:
        assert {n for n in z.namelist() if n.startswith("word/media/")} and "word/document.xml" in z.namelist()

    out = read_paper("format.docx", docx_r.content)
    t = out["text"]
    assert len(out["images"]) == 7 and not out["notes"]
    assert re.search(r"Q2\..*\nImage:\s*\[\[IMAGE 1\]\]", t) and "(a) Image:" in t and t.index("(a) Image:") < t.index("[[IMAGE 2]]") < t.index("(b) Image:")   # the pictures sit where the format puts them

    # through the upload: the MCQs of the format are read by rules (the stand-in AI is only asked about the coding and SQL questions)
    t_ = _exam(client, h, "Technical", "Format exam")
    asked = []
    _fake_ai(monkeypatch, lambda p: asked.append(1) or {"sections": []})
    pics = [(i["id"], i["src"]) for i in out["images"]]
    got = _understand(client, h, t_["id"], t, images=pics).json()
    secs = {s["title"]: s["questions"] for s in got["pack"]["sections"]}
    a, b, c = secs["Section A: Quantitative Aptitude"], secs["Section B: Logical Reasoning"], secs["Section C: English"]
    assert [q["correct"] for q in a + b + c] == [["b"], ["c"], ["c"], ["b"]] and all(q["read_from_paper"] for q in a + b + c)   # the answers are the key's
    assert "images" not in a[0] and a[1]["images"] == [pics[0][1]] and "Image" not in a[1]["statement"]                              # the label word is not question text
    assert [o.get("image") for o in b[0]["options"]] == [pics[1][1], pics[2][1], pics[3][1], pics[4][1]]                            # (a)-(d) Image: are the options' pictures, in order
    assert a[0]["marks"] == 1 and any("6 question(s) were read exactly" in n for n in got["notes"]) and asked == []                  # all six: the AI was never asked
    code, sql = secs["Section D: Coding"][0], secs["Section E: SQL"][0]
    assert code["type"] == "coding" and code["marks"] == 8 and code["reference"]["language"] == "python" and "        print('NO')" in code["reference"]["source"]   # the sample answer, indentation kept
    assert [(c["visibility"], c["input"]) for c in code["test_cases"]][:3] == [("open", "{[()]}"), ("open", "([)]"), ("hidden", "()[]{}")] and len(code["test_cases"]) == 5
    assert code["images"] == [pics[5][1]] and sql["images"] == [pics[6][1]]                                                             # the diagrams under the coding and SQL questions
    assert sql["type"] == "sql" and sql["marks"] == 9 and "CREATE TABLE employees" in sql["schema"] and sql["reference_sql"].startswith("SELECT name FROM employees")
    assert "INSERT INTO employees" in sql["datasets"][0]["data"] and "CREATE" not in sql["statement"] and "Sample data" not in sql["statement"]


# ---------------------------------------------------------------- PDFs written the way real ones are: the footer first in the stream, code in a monospaced font
def _doc(pages):
    """A multi-page PDF. A page is a list of operations in STREAM order: ("text", x, y, words, mono) or ("image", x, y, side)."""
    objs, kids = [], []
    imgs = []
    for pn, ops in enumerate(pages):
        content, names = b"", b""
        for op in ops:
            if op[0] == "text":
                words = op[3].replace("(", "\\(").replace(")", "\\)").encode()
                content += b"BT /%s 10 Tf %d %d Td (%s) Tj ET\n" % (b"F2" if op[4] else b"F1", op[1], op[2], words)
            else:
                imgs.append(bytes(((x * 7 + y * 3 + len(imgs) * 40) % 256, (x + len(imgs) * 60) % 256, (y * 5) % 256)[c] for y in range(op[3]) for x in range(op[3]) for c in range(3)))
                names += b"/Im%d %d 0 R " % (len(imgs), 100 + len(imgs))
                content += b"q %d 0 0 %d %d %d cm /Im%d Do Q\n" % (op[3], op[3], op[1], op[2], len(imgs))
        pid, cid = 5 + pn * 2, 6 + pn * 2
        kids.append(b"%d 0 R" % pid)
        objs += [(pid, b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 420 595]/Contents %d 0 R/Resources<</Font<</F1 3 0 R/F2 4 0 R>>/XObject<<%s>>>>>>" % (cid, names)),
                 (cid, b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream")]
    objs += [(1, b"<</Type/Catalog/Pages 2 0 R>>"), (2, b"<</Type/Pages/Kids[%s]/Count %d>>" % (b" ".join(kids), len(pages))),
             (3, b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>"), (4, b"<</Type/Font/Subtype/Type1/BaseFont/Courier/Encoding/WinAnsiEncoding>>")]
    for n, raw in enumerate(imgs, 1):
        w = int((len(raw) // 3) ** 0.5)
        objs.append((100 + n, b"<</Type/XObject/Subtype/Image/Width %d/Height %d/ColorSpace/DeviceRGB/BitsPerComponent 8/Length %d>>stream\n" % (w, w, len(raw)) + raw + b"\nendstream"))
    return b"%PDF-1.4\n" + b"".join(b"%d 0 obj\n" % i + o + b"\nendobj\n" for i, o in sorted(objs)) + b"trailer<</Root 1 0 R/Size 200>>\n%%EOF"


def test_a_pdf_whose_footer_comes_first_is_read_in_reading_order_with_pictures_between_question_and_options_and_code_indented():
    foot = lambda n: ("text", 30, 20, f"Sample Paper - 50 marks - Page {n}", False)  # noqa: E731  (written FIRST, like a footer drawn by a page template)
    head = ("text", 30, 575, "Sample Paper - confidential", False)
    p1 = [foot(1), head, ("text", 30, 540, "Section A: Reasoning (2 marks)", False),
          ("text", 30, 510, "Q1. Refer to the bar chart. What is the total? [1 mark]", False), ("image", 40, 370, 120),
          ("text", 30, 350, "(a) 10", False), ("text", 30, 337, "(b) 20", False),
          ("text", 30, 300, "Q2. Which figure comes next? [1 mark]", False), ("image", 40, 170, 110),
          ("text", 30, 150, "(a) A", False), ("text", 30, 137, "(b) B", False)]
    p2 = [foot(2), head, ("text", 30, 540, "Q3. Write the reference solution [8 marks]", False)]
    for k, line in enumerate(["def f(s):", "    out = []", "    for ch in s:", "        if ch == 'a':", "            out.append(ch)", "    return out"]):
        p2.append(("text", 30, 500 - k * 12, line, True))
    p3 = [foot(3), head, ("text", 30, 540, "Answer Key and Solutions", False), ("text", 30, 525, "Q1 (b)   Q2 (a)", False)]
    out = read_paper("real.pdf", _doc([p1, p2, p3]))
    t = out["text"]
    assert "Sample Paper - 50 marks" not in t and "confidential" not in t                          # the running header and footer are gone
    assert t.index("Q1.") < t.index("[[IMAGE 1]]") < t.index("(a) 10") < t.index("Q2.") < t.index("[[IMAGE 2]]") < t.index("(a) A")     # pictures between question and options
    assert "def f(s):\n    out = []\n    for ch in s:\n        if ch == 'a':\n            out.append(ch)\n    return out" in t   # indentation recovered from the positions
    assert t.index("Section A") < t.index("Q1.")


# ---------------------------------------------------------------- the rules that read a paper without the AI
def _parse(text, key=""):
    from app.api.exam_pack import _spans
    from app.services.paper_parse import parse_paper
    return parse_paper(text, key, _spans(text))


def _qs(res):
    return [it for s in res["sections"] for it in s["items"]]


def test_a_clean_paper_is_read_exactly_answers_from_the_line_under_the_question_or_from_the_key():
    paper = ("Intro line.\nSection A: Aptitude (3 marks)\n"
             "Q1. What is 2 + 2? [1 mark]\n(a) 3\n(b) 4\n(c) 5\nAnswer: (b)\n"
             "Q2. Tick the primes. [2 marks]\n(a) 2\n(b) 4\n(c) 7\nAnswer: (a), (c)\n"
             "Q3. Capital of France?\nA) Paris\nB) Rome\nAnswer: Paris\n"
             "Section B: More\nQ4. Pick one\n(a) x\n(b) y\n")
    key = "Answer Key and Solutions\nQ4 (b)\nQ4. Answer: (b) y\n"
    res = _parse(paper, key)
    items = _qs(res)
    assert res["exact"] == 4 and [s["title"] for s in res["sections"]] == ["Section A: Aptitude", "Section B: More"]
    q1, q2, q3, q4 = (i["question"] for i in items)
    assert q1["correct"] == ["b"] and q1["marks"] == 1 and q1["type"] == "mcq_single" and [o["text"] for o in q1["options"]] == ["3", "4", "5"] and "[1 mark]" not in q1["statement"]
    assert q2["correct"] == ["a", "c"] and q2["type"] == "mcq_multi" and q2["marks"] == 2
    assert q3["correct"] == ["a"]                                                              # "Answer: Paris" names the option by its words
    assert q4["correct"] == ["b"]                                                              # no line under it: the key's Q4 answers
    assert all(q["read_from_paper"] for q in (q1, q2, q3, q4))


def test_what_the_rules_cannot_read_cleanly_goes_to_the_ai_untouched():
    paper = ("Section A\nQ1. Fine question\n(a) one\n(b) two\nAnswer: (a)\n"
             "Q2. No answer anywhere\n(a) one\n(b) two\n"
             "Q3. Odd layout\n(a) one\nsome words between\n(b) two\nAnswer: (a)\n"
             "Q4. Write a program that adds two numbers [8 marks]\nInput format\nTwo integers.\n"
             "Q5. Explain TCP in two lines.\nAnswer: A reliable transport protocol.\n")
    res = _parse(paper, "")
    kinds = [(i["number"], i["kind"], i.get("why")) for i in _qs(res)]
    assert res["exact"] == 1 and kinds == [(1, "mcq", None), (2, "block", "no answer in the paper"), (3, "block", "text between options"),
                                          (4, "block", "no clean options"), (5, "block", "no clean options")]
    assert "Answer: A reliable transport protocol." in _qs(res)[-1]["text"]                    # written answers stay in the block for the AI
    assert _parse("just some text\nwithout numbers\n")["sections"] == [] and _parse("Q1. only one\n(a) x\n(b) y\nAnswer: a\n")["exact"] == 0   # not a structured paper: nothing claimed


def test_pictures_passages_and_same_chart_follow_the_text():
    from app.services.paper_parse import share_pictures
    paper = ("Section A\nQ1. Refer to the bar chart. Total?\n[[IMAGE 1]]\n(a) 1\n(b) 2\nAnswer: (a)\n"
             "Q2. Refer to the same bar chart. Average?\n(a) 1\n(b) 2\nAnswer: (b)\n"
             "Q3. Which figure next?\nImage: [[IMAGE 2]]\n(a) Image: [[IMAGE 3]]\n(b) Image: [[IMAGE 4]]\nAnswer: (b)\n"
             "Q4. Pick the right word.\n(a) x\n(b) y\nAnswer: (a)\n"
             "Read the passage and answer the next two questions.\nThe quick brown fox jumps over the lazy dog many times in a row.\n"
             "Q5. What did the fox do?\n(a) jump\n(b) sleep\nAnswer: (a)\nQ6. Where?\n(a) here\n(b) there\nAnswer: (b)\nQ7. Unrelated\n(a) p\n(b) q\nAnswer: (a)\n")
    qs = [i["question"] for i in _qs(_parse(paper))]
    share_pictures(qs)
    assert qs[0]["images"] == ["IMAGE 1"] and qs[1]["images"] == ["IMAGE 1"]                    # "the same bar chart" shares the picture
    assert qs[2]["images"] == ["IMAGE 2"] and [o.get("image") for o in qs[2]["options"]] == ["IMAGE 3", "IMAGE 4"] and "images" not in qs[3]
    assert "<blockquote>" in qs[4]["statement"] and "quick brown fox" in qs[4]["statement"] and "quick brown fox" in qs[5]["statement"]   # the passage goes with the next two questions
    assert "quick brown fox" not in qs[6]["statement"] and "quick brown fox" not in qs[3]["statement"]


def test_the_writer_notes_block_is_ignored_wherever_it_sits(client, monkeypatch):
    h = _creator(client)
    t = _exam(client, h, "Technical", "Notes exam")
    paper = ("My exam title\n=== NOTES FOR THE WRITER (ignored) ===\n1. Number questions Q1.\nFor the examiner only. Answer Key and Solutions.\n=== END OF NOTES ===\n"
             "Section A: Test (2 marks)\nQ1. What is 1 + 1? [1 mark]\n(a) 1\n(b) 2\nAnswer: (b)\nQ2. What is 2 + 2? [1 mark]\n(a) 4\n(b) 5\nAnswer: (a)\n")
    calls = []
    monkeypatch.setattr(exam_pack, "ask_ai_for_pack", lambda *a: calls.append(1) or ("{}", "stop"))
    got = _understand(client, h, t["id"], paper).json()
    assert calls == [] and len(got["pack"]["sections"][0]["questions"]) == 2                    # nothing left for the AI: no AI call at all
    assert [q["correct"] for q in got["pack"]["sections"][0]["questions"]] == [["b"], ["a"]]


def test_a_paper_that_is_all_rule_readable_needs_no_ai_even_when_the_ai_is_off(client):
    h = _creator(client)
    t = _exam(client, h, "Technical", "No AI exam")
    paper = "Section A: T\nQ1. First question here?\n(a) 1\n(b) 2\nAnswer: (a)\nQ2. Second question here?\n(a) 1\n(b) 2\nAnswer: (b)\n"
    got = _understand(client, h, t["id"], paper)
    assert got.status_code == 200 and any("2 question(s) were read exactly" in n for n in got.json()["notes"])        # the test server has the AI switched off
    rep = client.post(f"{API}/tests/{t['id']}/import-questions", headers=h, json={"pack": got.json()["pack"], "dry_run": True, "detail": True}).json()
    assert rep["ok"] and all(q["from_paper"] and not q["answer_from_ai"] for q in rep["sections"][0]["questions"])
    # a paper with a coding question and the AI off: the rule-read questions stay, the coding one is reported, nothing fails
    mixed = paper + "Section B: Code\nQ3. Write a program [8 marks]\nInput format\nOne integer.\n"
    out = _understand(client, h, t["id"], mixed)
    assert out.status_code == 200 and len(out.json()["pack"]["sections"]) == 1 and any("could not be read by the AI" in n for n in out.json()["notes"])


REAL_PDF = os.environ.get("OAP_REAL_PDF", r"C:\Users\ASUS\Downloads\GLOBX_Aptitude_Coding_SQL_Paper_50_Marks.pdf")


@pytest.mark.skipif(not os.path.exists(REAL_PDF), reason="the user's real paper is not on this machine")
def test_the_users_real_pdf_every_picture_on_its_question_every_answer_from_the_key_code_indented():
    from app.api.exam_pack import _drop_writer_notes, _paper_facts, _spans
    from app.services.paper_parse import parse_paper, share_pictures
    out = read_paper(os.path.basename(REAL_PDF), open(REAL_PDF, "rb").read())
    body, key, _ = _paper_facts(_drop_writer_notes(out["text"]))
    key_ids = set(re.findall(r"\[\[(IMAGE \d+)\]\]", key))
    assert key_ids == {f"IMAGE {n}" for n in range(10, 17)}                                       # the key's pictures (they show the answers) are never question pictures
    res = parse_paper(body, key, _spans(body))
    mcq = {i["number"]: i["question"] for s in res["sections"] for i in s["items"] if i["kind"] == "mcq"}
    assert res["exact"] == 28 and sorted(mcq) == list(range(1, 26))
    assert [mcq[n]["correct"][0] for n in range(1, 26)] == "c a a d b b c b d b a b a c b a c d b c d b b d a".split()   # the key's own table
    share_pictures([mcq[n] for n in sorted(mcq)])
    assert {n: q["images"] for n, q in mcq.items() if q.get("images")} == {7: ["IMAGE 1"], 8: ["IMAGE 1"], 12: ["IMAGE 2"], 13: ["IMAGE 3"], 14: ["IMAGE 4"], 17: ["IMAGE 5"], 18: ["IMAGE 6"]}
    assert all("passage" in mcq[n]["statement"].lower() and "Copenhagen" in mcq[n]["statement"] for n in (23, 24, 25)) and "Copenhagen" not in mcq[22]["statement"]
    code = {i["number"]: i["question"] for s in res["sections"] for i in s["items"] if i["kind"] == "code"}
    assert sorted(code) == [26, 27, 28] and [code[n]["type"] for n in (26, 27, 28)] == ["coding", "coding", "sql"] and [code[n]["marks"] for n in (26, 27, 28)] == [8, 8, 9]
    assert [code[n]["images"] for n in (26, 27, 28)] == [["IMAGE 7"], ["IMAGE 8"], ["IMAGE 9"]]                                    # the coding and SQL figures stay with their question
    assert code[26]["reference"]["source"].startswith("def is_balanced(s):\n    pairs = ") and "\nprint(\"YES\" if is_balanced(s) else \"NO\")" in code[26]["reference"]["source"]
    assert "            continue" in code[27]["reference"]["source"] and code[26]["_cases_key"] and "(generated) maximum size" in code[27]["_cases_key"]
    sql = code[28]
    assert "CREATE TABLE departments" in sql["schema"] and "CREATE TABLE employees" in sql["schema"] and sql["reference_sql"].startswith("SELECT d.dept_name") and "INSERT INTO employees" in sql["datasets"][0]["data"]
    assert "def is_balanced(s):\n    pairs = " in out["text"] and "            continue" in out["text"]                                    # the key's code has its indentation


def test_the_question_is_bold_the_description_normal_and_explanations_stay_out_of_the_question():
    paper = ("Section A: Mixed (4 marks)\n"
             "Q1. Ravi ranks 12th from the top in a class of 40 students. What is his rank from the bottom? [1 mark]\n(a) 27\n(b) 28\n(c) 29\nAnswer: (c)\nExplanation: 40 - 12 + 1 = 29.\n"
             "Q2. Choose the word closest in meaning to EPHEMERAL. [1 mark]\n(a) Eternal\n(b) Short-lived\nAnswer: (b)\n"
             "Explanation: Ephemeral means lasting a very short time, so a\nlong explanation that wraps over two lines.\n"
             "Read the passage and answer the next two questions.\nSleep is often treated as a luxury, but research shows it is a necessity.\n"
             "Q3. What is the main idea of the passage? [1 mark]\n(a) Sleep matters\n(b) Sleep is a luxury\nAnswer: (a) Sleep matters\nExplanation: The passage argues sleep is a necessity.\n"
             "Q4. In the passage, the word luxury is closest in meaning to: [1 mark]\n(a) Comfort\n(b) Need\nAnswer: (a)\nExplanation: Luxury means comfort.\n"
             "Q5. Statements: All pens are books. Some books are bags.\nConclusions: I. Some pens are bags. II. Some bags are books. [1 mark]\n(a) Only I\n(b) Only II\nAnswer: (b)\n")
    qs = {i["number"]: i["question"] for i in _qs(_parse(paper))}
    assert qs[1]["statement"] == "<p>Ravi ranks 12th from the top in a class of 40 students.</p><p><b>What is his rank from the bottom?</b></p>"      # the description normal, the asking part bold
    assert qs[1]["title"] == "What is his rank from the bottom?" and qs[1]["explanation"] == "40 - 12 + 1 = 29."                                   # the title is the question; the explanation is kept apart
    assert qs[2]["statement"] == "<p><b>Choose the word closest in meaning to EPHEMERAL.</b></p>"
    assert qs[2]["explanation"] == "Ephemeral means lasting a very short time, so a long explanation that wraps over two lines."                 # a wrapped explanation ends where its sentence ends
    for n in (3, 4):
        st = qs[n]["statement"]
        assert st.startswith("<blockquote><p>Read the passage and answer the next two questions.</p><p>Sleep is often treated") and "Explanation" not in st and "Ephemeral" not in st
    assert qs[3]["statement"].endswith("<p><b>What is the main idea of the passage?</b></p>") and qs[3]["correct"] == ["a"]
    assert "blockquote" not in qs[1]["statement"] and "blockquote" not in qs[5]["statement"]                                                       # the passage is only for the two questions after it
    assert qs[5]["statement"] == "<p>Statements: All pens are books. Some books are bags.</p><p>Conclusions: I. Some pens are bags. II. Some bags are books.</p>"   # label lines stay as they are


def test_a_question_that_refers_to_the_same_pie_chart_gets_its_picture():
    from app.services.paper_parse import share_pictures
    paper = ("Section A\nQ1. Refer to the pie chart. How much is spent on food? [1 mark]\n[[IMAGE 1]]\n(a) 1\n(b) 2\nAnswer: (a)\n"
             "Q2. Refer to the same pie chart. By how much does saving exceed transport? [1 mark]\n(a) 1\n(b) 2\nAnswer: (b)\n"
             "Q3. An unrelated question about rates?\n(a) 1\n(b) 2\nAnswer: (a)\n"
             "Q4. Using the table above, find the total.\n(a) 1\n(b) 2\nAnswer: (a)\n")
    qs = [i["question"] for i in _qs(_parse(paper))]
    share_pictures(qs)
    assert qs[0]["images"] == ["IMAGE 1"] and qs[1]["images"] == ["IMAGE 1"] and "images" not in qs[2]
    assert qs[3]["images"] == ["IMAGE 1"]                                                       # "the table above" also looks back for the nearest picture


def test_explanations_are_kept_for_staff_and_never_sent_to_the_candidate(client):
    from types import SimpleNamespace
    from app.services.attempts import candidate_question
    h = _creator(client)
    t = _exam(client, h, "Technical", "Explain exam")
    paper = "Section A: T\nQ1. What is 2 + 2?\n(a) 3\n(b) 4\nAnswer: (b)\nExplanation: Two plus two is four.\nQ2. What is 3 + 3?\n(a) 6\n(b) 7\nAnswer: (a)\n"
    pack = _understand(client, h, t["id"], paper).json()["pack"]
    assert _import(client, h, t["id"], pack, dry_run=False).status_code == 200
    qid = client.get(f"{API}/questions", headers=h, params={"q": "What is 2 + 2?"}).json()[0]["id"]
    full = client.get(f"{API}/questions/{qid}", headers=h).json()
    assert full["config"]["explanation"] == "Two plus two is four."
    row = SimpleNamespace(question=SimpleNamespace(id=qid, type="mcq_single", title="t", body=full["body"], difficulty="easy", skills=[], group_id=None, config=full["config"]),
                          marks=1, negative=0, section_id="s", order=0, option_order=["a", "b"])
    assert "explanation" not in str(candidate_question(row, None)) and "Two plus two" not in str(candidate_question(row, None))


REAL_PDF_2 = os.environ.get("OAP_REAL_PDF_2", r"C:\Users\ASUS\Downloads\GLOBX_Set2_Questions_with_Answers_50_Marks.pdf")


@pytest.mark.skipif(not os.path.exists(REAL_PDF_2), reason="the user's second real paper is not on this machine")
def test_the_users_second_real_pdf_answers_inline_explanations_apart_passage_clean_same_chart_shared():
    from app.api.exam_pack import _drop_writer_notes, _paper_facts, _spans
    from app.services.paper_parse import clean_pages, parse_paper, share_pictures
    out = read_paper(os.path.basename(REAL_PDF_2), open(REAL_PDF_2, "rb").read())
    body, key, _ = _paper_facts(_drop_writer_notes(out["text"]))
    res = parse_paper(clean_pages(body), clean_pages(key), _spans(clean_pages(body)))
    mcq = {i["number"]: i["question"] for s in res["sections"] for i in s["items"] if i["kind"] == "mcq"}
    assert sorted(mcq) == list(range(1, 26)) and res["exact"] == 28 and res["solution_images"] == ["IMAGE 2", "IMAGE 4", "IMAGE 6", "IMAGE 8", "IMAGE 10"]   # all read by rules; the pictures under the answers are solutions, kept out
    share_pictures([mcq[n] for n in sorted(mcq)])
    plain = lambda n: re.sub(r"<[^>]+>", " ", mcq[n]["statement"])  # noqa: E731
    assert not any("Explanation" in plain(n) for n in mcq) and all(q.get("explanation") for q in mcq.values())                     # explanations never end up in a question, each is kept apart
    assert mcq[8]["images"] == mcq[7]["images"] and "pie chart" in plain(8)                                                         # "Refer to the same pie chart" has the chart
    for n in (23, 24, 25):
        assert mcq[n]["statement"].startswith("<blockquote><p>Read the passage and answer the next three questions.</p>") and "Sleep is often treated" in mcq[n]["statement"]
        assert "collocation" not in plain(n) and mcq[n]["statement"].count("<b>") == 1                                              # one bold part: the question
    assert mcq[25]["title"].startswith("In the passage, the word steady") and mcq[23]["title"] == "What is the main idea of the passage?"
    assert "<blockquote>" not in mcq[22]["statement"]
