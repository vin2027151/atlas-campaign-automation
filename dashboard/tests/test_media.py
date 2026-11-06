"""Media library API tests. Run from dashboard/:

    .venv/bin/python -m unittest tests.test_media -v     (or pytest tests/test_media.py)

Every test works on temp copies of data/state.json and data/media.json and a temp
upload folder; the real files are never written.
"""

import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
import io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import store  # noqa: E402
import media  # noqa: E402
from media import seed  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import app as app_module  # noqa: E402


def tiny_png(w=3, h=2):
    raw = b"".join(b"\x00" + b"\x93\x6b\xda" * w for _ in range(h))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class MediaApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="media-test-")
        self.orig = (store.STATE_PATH, media.MEDIA_PATH, media.UPLOAD_DIR)
        state = os.path.join(self.tmp, "state.json")
        shutil.copy(self.orig[0], state)
        store.STATE_PATH = state
        store.reload_state()
        media.MEDIA_PATH = os.path.join(self.tmp, "media.json")
        media.UPLOAD_DIR = os.path.join(self.tmp, "uploads")
        real_media = self.orig[1]
        if os.path.exists(real_media):
            shutil.copy(real_media, media.MEDIA_PATH)
        else:
            media.save(seed.build())
        self.client = TestClient(app_module.app)
        self.real_mtimes = {p: os.path.getmtime(p) for p in self.orig[:2] if os.path.exists(p)}

    def tearDown(self):
        for p, m in self.real_mtimes.items():
            self.assertEqual(os.path.getmtime(p), m, "%s was written by a test" % p)
        store.STATE_PATH, media.MEDIA_PATH, media.UPLOAD_DIR = self.orig
        store.reload_state()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers
    def new_request(self, kind="image", **kw):
        body = {"title": "Test %s request" % kind, "kind": kind, "brief": "brief", "due": "2026-11-20",
                "platforms": ["meta"], "placements": ["Feed"]}
        body.update(kw)
        r = self.client.post("/api/media/requests", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["asset"]

    def upload(self, asset_id, data, name="x.png", mime="image/png"):
        return self.client.post("/api/media/%s/upload" % asset_id, files={"file": (name, data, mime)})

    # tests
    def test_list_and_filters(self):
        r = self.client.get("/api/media/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["counts"]["total"], len(body["assets"]))
        by = body["counts"]["by_status"]
        self.assertGreaterEqual(by["requested"], 2)
        self.assertGreaterEqual(by["approved"], 2)
        self.assertTrue(any(a["id"] == "H5-0001" and a["status"] == "approved" for a in body["assets"]))
        r = self.client.get("/api/media/?status=approved&kind=html5")
        self.assertTrue(r.json()["assets"])
        self.assertTrue(all(a["kind"] == "html5" and a["status"] == "approved" for a in r.json()["assets"]))
        self.assertEqual(self.client.get("/api/media/?status=bogus").status_code, 400)
        # module API used by planning
        self.assertEqual(media.get_asset("H5-0001")["kind"], "html5")
        self.assertTrue(all(a["status"] == "approved" for a in media.list_assets(status="approved")))

    def test_create_request(self):
        a = self.new_request("video")
        self.assertRegex(a["id"], r"^VID-\d{4}$")
        self.assertEqual(a["status"], "requested")
        self.assertIsNone(a["file_url"])
        self.assertEqual(a["due"], "2026-11-20")
        self.assertEqual(self.client.get("/api/media/%s" % a["id"]).json()["asset"]["title"], "Test video request")
        self.assertEqual(self.client.post("/api/media/requests", json={"title": "", "kind": "image"}).status_code, 400)
        self.assertEqual(self.client.post("/api/media/requests", json={"title": "x", "kind": "gif"}).status_code, 400)
        acts = store.recent_activity(5)
        self.assertTrue(any(x["action"] == "media.request" and x["target"] == a["id"] for x in acts))

    def test_upload_png_then_approve(self):
        a = self.new_request("image")
        r = self.upload(a["id"], tiny_png(3, 2))
        self.assertEqual(r.status_code, 200, r.text)
        up = r.json()["asset"]
        self.assertEqual(up["status"], "in_review")
        self.assertEqual((up["width"], up["height"]), (3, 2))
        self.assertEqual(up["format"], "image/png")
        self.assertEqual(up["file_url"], "/static/media/library/uploads/%s.png" % a["id"])
        self.assertTrue(os.path.exists(os.path.join(media.UPLOAD_DIR, "%s.png" % a["id"])))
        r = self.client.post("/api/media/%s/approve" % a["id"], json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["asset"]["status"], "approved")
        # approving again is a 400; uploading over an approved asset is a 400
        self.assertEqual(self.client.post("/api/media/%s/approve" % a["id"], json={}).status_code, 400)
        self.assertEqual(self.upload(a["id"], tiny_png()).status_code, 400)

    def test_active_lifecycle(self):
        a = self.new_request("image")
        # only approved assets can be marked active
        self.assertEqual(self.client.post("/api/media/%s/activate" % a["id"], json={}).status_code, 400)
        self.upload(a["id"], tiny_png())
        self.assertEqual(self.client.post("/api/media/%s/activate" % a["id"], json={}).status_code, 400)
        self.client.post("/api/media/%s/approve" % a["id"], json={})
        self.assertEqual(self.client.post("/api/media/%s/deactivate" % a["id"], json={}).status_code, 400)
        r = self.client.post("/api/media/%s/activate" % a["id"], json={"note": "running in Prospecting_Core"})
        self.assertEqual(r.status_code, 200, r.text)
        act = r.json()["asset"]
        self.assertEqual(act["status"], "active")
        self.assertEqual(act["history"][-1]["action"], "marked active")
        self.assertTrue(any(x["action"] == "media.activate" and x["target"] == a["id"] for x in store.recent_activity(5)))
        # activating twice is a 400; uploading over an active asset is a 400
        self.assertEqual(self.client.post("/api/media/%s/activate" % a["id"], json={}).status_code, 400)
        self.assertEqual(self.upload(a["id"], tiny_png()).status_code, 400)
        # active stays usable: listed with approved, publishable, and taggable in Plan & Adapt briefs
        usable = self.client.get("/api/media/?status=approved,active").json()["assets"]
        self.assertIn(a["id"], [x["id"] for x in usable])
        self.assertTrue(all(x["status"] in media.USABLE_STATUSES for x in usable))
        self.assertEqual([x["id"] for x in self.client.get("/api/media/?status=active").json()["assets"]], [a["id"]])
        self.assertEqual(self.client.get("/api/media/").json()["counts"]["by_status"]["active"], 1)
        self.assertEqual(self.client.get("/api/media/?status=approved,bogus").status_code, 400)
        out = media.mark_published(a["id"], "meta", {"image_hash": "abc"})
        self.assertEqual(out["status"], "active")
        from planning import jobs
        self.assertIn(a["id"], [x["id"] for x in jobs.approved_media()])
        # and back to approved
        r = self.client.post("/api/media/%s/deactivate" % a["id"], json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["asset"]["status"], "approved")
        self.assertEqual(r.json()["asset"]["history"][-1]["action"], "taken out of use")
        self.assertEqual(self.client.post("/api/media/IMG-9999/activate", json={}).status_code, 404)

    def test_reject_requires_note(self):
        a = self.new_request("image")
        self.upload(a["id"], tiny_png())
        self.assertEqual(self.client.post("/api/media/%s/reject" % a["id"], json={}).status_code, 400)
        self.assertEqual(self.client.post("/api/media/%s/reject" % a["id"], json={"note": "  "}).status_code, 400)
        r = self.client.post("/api/media/%s/reject" % a["id"], json={"note": "Logo too small"})
        self.assertEqual(r.status_code, 200, r.text)
        back = r.json()["asset"]
        self.assertEqual(back["status"], "requested")
        self.assertEqual(back["review_note"], "Logo too small")
        self.assertEqual(back["history"][-1]["action"], "sent back")

    def test_edit(self):
        r = self.client.post("/api/media/H5-0001", json={"title": "New title", "description": "d",
                                                         "tags": ["g_pmax_us"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["asset"]["tags"], ["g_pmax_us"])
        self.assertEqual(self.client.post("/api/media/H5-0001", json={"tags": ["nope"]}).status_code, 400)
        self.assertEqual(self.client.post("/api/media/H5-0001", json={"status": "requested"}).status_code, 400)

    def test_mark_published(self):
        out = media.mark_published("H5-0001", "google", {"asset_resource": "customers/4445556666/assets/9"})
        self.assertEqual(out["platform_refs"]["google"]["asset_resource"], "customers/4445556666/assets/9")
        self.assertEqual(media.get_asset("H5-0001")["platform_refs"]["google"]["asset_resource"],
                         "customers/4445556666/assets/9")
        with self.assertRaises(store.BadInput):
            media.mark_published("H5-0001", "tiktok", {"x": 1})
        req = self.new_request("image")
        with self.assertRaises(store.BadInput):
            media.mark_published(req["id"], "meta", {"image_hash": "abc"})
        with self.assertRaises(store.NotFound):
            media.mark_published("IMG-9999", "meta", {"image_hash": "abc"})

    def test_404s(self):
        self.assertEqual(self.client.get("/api/media/IMG-9999").status_code, 404)
        self.assertEqual(self.client.post("/api/media/IMG-9999/approve", json={}).status_code, 404)
        self.assertEqual(self.client.post("/api/media/IMG-9999/reject", json={"note": "x"}).status_code, 404)
        self.assertEqual(self.client.post("/api/media/IMG-9999", json={"title": "x"}).status_code, 404)
        self.assertEqual(self.upload("IMG-9999", tiny_png()).status_code, 404)
        with self.assertRaises(store.NotFound):
            media.get_asset("VID-9999")

    def test_bad_uploads(self):
        a = self.new_request("image")
        r = self.upload(a["id"], b"%PDF-1.4 nope", name="x.pdf", mime="application/pdf")
        self.assertEqual(r.status_code, 400)
        self.assertIn("unsupported", r.json()["error"])
        # whitelisted mime but not a real PNG
        self.assertEqual(self.upload(a["id"], b"not a png at all, just text bytes", mime="image/png").status_code, 400)
        # kind mismatch: mp4 against an image request
        self.assertEqual(self.upload(a["id"], b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16, name="v.mp4",
                                     mime="video/mp4").status_code, 400)
        self.assertEqual(media.get_asset(a["id"])["status"], "requested")

    def test_html5_zip_upload(self):
        a = self.new_request("html5")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("index.html", '<html><head><meta name="ad.size" content="width=728,height=90"></head></html>')
        r = self.upload(a["id"], buf.getvalue(), name="ad.zip", mime="application/zip")
        self.assertEqual(r.status_code, 200, r.text)
        up = r.json()["asset"]
        self.assertEqual((up["width"], up["height"], up["aspect"]), (728, 90, "728x90"))
        self.assertTrue(up["file_url"].endswith("/%s/index.html" % a["id"]))

    def test_image_size_parsers(self):
        self.assertEqual(media.image_size(tiny_png(7, 5)), (7, 5))
        gif = b"GIF89a" + struct.pack("<HH", 12, 9) + b"\x00" * 20
        self.assertEqual(media.image_size(gif), (12, 9))
        jpeg = (b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
                + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 250, 300) + b"\x00" * 12)
        self.assertEqual(media.image_size(jpeg), (300, 250))
        webp = b"RIFF" + b"\x00" * 4 + b"WEBPVP8X" + b"\x00" * 8 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
        self.assertEqual(media.image_size(webp), (100, 50))
        self.assertIsNone(media.image_size(b"x" * 40))


if __name__ == "__main__":
    unittest.main()
