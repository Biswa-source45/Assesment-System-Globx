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
