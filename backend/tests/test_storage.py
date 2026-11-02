"""Where camera pictures go: under the storage folder, recorded by relative path, served only to staff, never from outside the folder."""
import os

from test_exam_rules import PW, _login, _new_candidate, _start, client  # noqa: F401  (client is a fixture)

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import ProctorSnapshot

API = "/api/v1"


def test_camera_pictures_are_stored_under_the_storage_folder_by_relative_path(client):
    staff, cand, aid = _new_candidate(client, "Storage Check")
    at = _start(client, cand, aid)
    picture = b"\xff\xd8\xff\xe0 not a real picture, the server stores any bytes it is sent"
    r = client.post(f"{API}/attempts/{at}/proctor/snapshot", headers=cand, data={"kind": "webcam", "faces": "1"}, files={"image": ("a.jpg", picture, "image/jpeg")})
    assert r.status_code == 200, r.text
    sid = r.json()["snapshot_id"]

    with SessionLocal() as db:
        row = db.get(ProctorSnapshot, sid)
        assert row.path.startswith(f"proctor/{at}/") and row.path.endswith(".jpg") and not os.path.isabs(row.path)  # portable: the folder can move
        on_disk = os.path.join(get_settings().storage_dir, *row.path.split("/"))
    assert os.path.isfile(on_disk) and open(on_disk, "rb").read() == picture

    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    assert client.get(f"{API}/snapshots/{sid}", headers=recruiter).content == picture
    assert client.get(f"{API}/snapshots/{sid}", headers=cand).status_code == 403      # a candidate cannot open pictures
    assert client.get(f"{API}/snapshots/{sid}").status_code == 401

    with SessionLocal() as db:  # a row pointing outside the storage folder is never served, however it got there
        db.get(ProctorSnapshot, sid).path = "../../../etc/passwd"
        db.commit()
    assert client.get(f"{API}/snapshots/{sid}", headers=recruiter).status_code == 404
    with SessionLocal() as db:  # rows written before paths became relative still work
        db.get(ProctorSnapshot, sid).path = on_disk
        db.commit()
    assert client.get(f"{API}/snapshots/{sid}", headers=recruiter).content == picture
