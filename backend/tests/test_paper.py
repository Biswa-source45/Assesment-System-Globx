"""Uploading a question paper: reading Word / PDF / Excel / text / photo files with their pictures, the AI step (replaced here by a fixed answer),
the ordinary check and import after it, and the picture rules every way of saving a question shares."""
import base64
import io
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
    assert any("2 pictures of the paper (IMAGE 1, IMAGE 2) were not attached to any question" in n for n in got["notes"])
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
    assert q1["statement"] == "What does the graph show? Be exact." and q1["images"] == [one]          # said twice, attached once
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
    assert any("IMAGE 1" in n for n in got["notes"])


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
    assert got["pack"]["sections"][0]["questions"][0]["statement"] == "Which is prime?"
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
