import base64
import hashlib
import hmac
import json
import threading

import pytest

import app as app_module
from store import store


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(b"test-webhook-secret", body, hashlib.sha256).digest()).decode()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json["ok"] is True


def test_webhook_rejects_bad_signature(client):
    body = json.dumps({"id": 123}).encode()
    r = client.post("/webhooks/products/create", data=body, headers={"X-Shopify-Hmac-Sha256": "nope"})
    assert r.status_code == 401


def test_webhook_accepts_valid_signature_and_dispatches(client, monkeypatch):
    seen = {}
    done = threading.Event()

    def fake_handler(action, pid):
        seen["action"], seen["pid"] = action, pid
        done.set()

    monkeypatch.setattr(app_module, "_handle_product_event", fake_handler)
    body = json.dumps({"id": 42, "title": "Test Dress"}).encode()
    r = client.post("/webhooks/products/create", data=body, headers={"X-Shopify-Hmac-Sha256": _sign(body)})
    assert r.status_code == 200
    assert done.wait(2)
    assert seen == {"action": "create", "pid": 42}


def test_new_product_lands_in_pending_queue_not_live(monkeypatch):
    product = {"id": 7, "gid": "gid://shopify/Product/7", "title": "Alune Dress in Wool Silk", "handle": "alune-dress-citron",
               "tags": "Dresses", "status": "active", "created_at": "2026-09-18T00:00:00Z",
               "body_html": "<p>A bias-cut dress in wool silk, made in Italy with a draped neckline and fluid skirt.</p>",
               "seo": {"title_tag": "", "description_tag": ""}}
    monkeypatch.setattr(app_module.sh, "get_product", lambda pid: dict(product))
    monkeypatch.setattr(app_module.sh, "get_product_images", lambda pid: [])
    monkeypatch.setattr(app_module, "_load_all", lambda force=False: [])
    monkeypatch.setattr(app_module, "_generate_for", lambda p: {"title": "Alune Dress Citron in Wool Silk | AFLALO", "description": "A wool silk dress crafted in Italy. The Alune Dress drapes."})
    published = []
    monkeypatch.setattr(app_module.sh, "set_seo", lambda *a: published.append(a))

    app_module._handle_product_event("create", 7)

    assert store.is_pending(7), "copy should wait for merch approval"
    assert published == [], "nothing should go live without approval"
    assert store.get_pending()[0]["seo_title"].endswith("| AFLALO")


def test_approving_pending_publishes_and_clears(client, monkeypatch):
    store.add_pending(9, {"title": "Gide Sweater in Wool", "handle": "gide-sweater-plum", "seo_title": "T", "seo_desc": "D"})
    published = []
    monkeypatch.setattr(app_module.sh, "set_seo", lambda pid, t, d: published.append((pid, t, d)))
    monkeypatch.setattr(app_module, "_load_all", lambda force=False: [])

    r = client.post("/pending/approve", json=[{"product_id": 9, "title": "Gide Sweater Plum in Wool | AFLALO", "description": "Desc"}])
    assert r.status_code == 200
    assert r.json["published"] == [9]
    assert published == [(9, "Gide Sweater Plum in Wool | AFLALO", "Desc")]
    assert not store.is_pending(9)


def test_webhook_photo_tagging_applies_alt_and_rename(monkeypatch):
    product = {"id": 11, "gid": "gid://shopify/Product/11", "title": "Herve Sweater in Cashmere", "handle": "herve-sweater-black",
               "tags": "Sweaters", "status": "active", "created_at": "2026-09-18T00:00:00Z", "body_html": "",
               "seo": {"title_tag": "x", "description_tag": "y"}}
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    images = [
        {"id": 501, "position": 2, "src": "https://cdn/x/files/20260705_AFLALO_1123copy.png?v=1", "alt": "", "filename": "20260705_AFLALO_1123copy.png",
         "created_at": (now - datetime.timedelta(hours=1)).isoformat()},
        {"id": 502, "position": 3, "src": "https://cdn/x/files/old_shot.png?v=1", "alt": "", "filename": "old_shot.png",
         "created_at": (now - datetime.timedelta(days=90)).isoformat()},
    ]
    monkeypatch.setattr(app_module.sh, "get_product", lambda pid: dict(product))
    monkeypatch.setattr(app_module.sh, "get_product_images", lambda pid: [dict(i) for i in images])
    monkeypatch.setattr(app_module, "_load_all", lambda force=False: [])
    monkeypatch.setattr(app_module, "classify_view", lambda url, title: "Model Back")
    monkeypatch.setattr(app_module.sh, "get_file_owners", lambda: {"20260705_AFLALO_1123copy.png": [11], "old_shot.png": [11]})
    monkeypatch.setitem(app_module._owners, "at", 0.0)
    alts, renames = [], []
    monkeypatch.setattr(app_module.sh, "set_image_alt", lambda pid, iid, alt: alts.append((pid, iid, alt)))
    monkeypatch.setattr(app_module.sh, "rename_product_image", lambda pid, src, fn, max_age: renames.append((pid, fn)) or True)

    app_module._handle_product_event("update", 11)

    assert alts == [(11, 501, "AFLALO Herve Sweater in Cashmere, Black, back view on model")]
    assert renames == [(11, "aflalo-herve-sweater-cashmere-black-model-back-02.png")]
    assert store.is_media_processed(501)

    # A second update for the same product must not re-process the same photo.
    app_module._handle_product_event("update", 11)
    assert len(alts) == 1


def test_late_event_for_deleted_product_is_ignored(monkeypatch):
    store.add_pending(77, {"title": "Gone Dress", "handle": "gone-dress", "seo_title": "T", "seo_desc": "D"})
    monkeypatch.setattr(app_module.sh, "get_product", lambda pid: None)
    called = []
    monkeypatch.setattr(app_module, "_generate_for", lambda p: called.append(p))
    app_module._handle_product_event("update", 77)
    assert called == [] and not store.is_pending(77)


def test_empty_copy_is_not_queued(monkeypatch):
    product = {"id": 78, "gid": "gid://shopify/Product/78", "title": "Blank Dress in Silk", "handle": "blank-dress-ivory",
               "tags": "Dresses", "status": "active", "created_at": "2026-10-02T00:00:00Z",
               "body_html": "<p>A long enough description of a silk dress made in Italy for the test to proceed.</p>",
               "seo": {"title_tag": "", "description_tag": ""}}
    monkeypatch.setattr(app_module.sh, "get_product", lambda pid: dict(product))
    monkeypatch.setattr(app_module.sh, "get_product_images", lambda pid: [])
    monkeypatch.setattr(app_module, "_load_all", lambda force=False: [])
    monkeypatch.setattr(app_module, "_generate_for", lambda p: {"title": "", "description": ""})
    app_module._handle_product_event("create", 78)
    assert not store.is_pending(78)
    assert any(e["event"] == "error" and e.get("product_id") == 78 for e in store.get_activity())


def _look(pid, title, handle, status="active"):
    return {"id": pid, "gid": f"gid://shopify/Product/{pid}", "title": title, "handle": handle, "tags": "Sweaters", "status": status,
            "created_at": "2026-08-26T00:00:00Z", "body_html": "", "colors": [], "seo": {"title_tag": "x", "description_tag": "y"}}


def test_a_tagged_look_photo_is_retagged_when_a_second_product_shares_it(monkeypatch):
    artusi, shay = _look(21, "Artusi Sweater in Wool", "artusi-sweater-black"), _look(22, "Shay Trouser in Wool", "shay-trouser-moss")
    photo = {"id": 601, "position": 2, "src": "https://cdn/x/files/look_093.jpg?v=1", "filename": "look_093.jpg",
             "alt": "AFLALO Artusi Sweater in Wool, Black, front view on model", "created_at": "2026-10-08T17:04:08Z"}
    monkeypatch.setattr(app_module.sh, "get_product", lambda pid: dict(artusi))
    monkeypatch.setattr(app_module.sh, "get_product_images", lambda pid: [dict(photo)])
    monkeypatch.setattr(app_module, "_load_all", lambda force=False: [artusi, shay])
    monkeypatch.setattr(app_module.sh, "get_file_owners", lambda: {"look_093.jpg": [21, 22]})
    monkeypatch.setitem(app_module._owners, "at", 0.0)
    monkeypatch.setattr(app_module, "classify_view", lambda url, title: pytest.fail("the view is already in the alt text"))
    alts = []
    monkeypatch.setattr(app_module.sh, "set_image_alt", lambda pid, iid, alt: alts.append(alt))
    monkeypatch.setattr(app_module.sh, "rename_product_image", lambda *a: pytest.fail("a live photo keeps its name"))

    app_module._handle_product_event("update", 21)
    both = "AFLALO Artusi Sweater in Wool, Black, and Shay Trouser in Wool, Moss, front view on model"
    assert alts == [both]

    # The write fires both products' webhooks; each must find the alt already right, or they rewrite it forever.
    photo["alt"] = both
    for pid in (21, 22):
        monkeypatch.setattr(app_module.sh, "get_product", lambda _, p=(artusi if pid == 21 else shay): dict(p))
        app_module._handle_product_event("update", pid)
    assert alts == [both]


def test_a_look_photo_never_names_a_draft(monkeypatch):
    artusi, shay = _look(31, "Artusi Sweater in Wool", "artusi-sweater-black"), _look(32, "Shay Trouser in Wool", "shay-trouser-moss", "draft")
    monkeypatch.setattr(app_module, "_load_all", lambda force=False: [artusi, shay])
    monkeypatch.setattr(app_module.sh, "get_file_owners", lambda: {"look.jpg": [31, 32]})
    monkeypatch.setitem(app_module._owners, "at", 0.0)
    img = {"filename": "look.jpg"}
    assert app_module._photo_products(artusi, img) == [("Artusi Sweater in Wool", "Black")]
    assert app_module._photo_products(shay, img) == [("Artusi Sweater in Wool", "Black")]


def test_a_live_photo_keeps_its_file_name(monkeypatch):
    import shopify_client as sh
    renamed = []
    monkeypatch.setattr(sh, "rename_file", lambda gid, fn: renamed.append(fn))
    monkeypatch.setattr(sh, "get_media_by_filename", lambda pid: {"old.jpg": {"id": "gid://shopify/MediaImage/1", "created_at": "2025-09-09T00:24:25Z"}})
    assert sh.rename_product_image(1, "https://cdn/x/files/old.jpg?v=1", "aflalo-new.jpg", 48) is False
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    monkeypatch.setattr(sh, "get_media_by_filename", lambda pid: {"old.jpg": {"id": "gid://shopify/MediaImage/1", "created_at": now}})
    assert sh.rename_product_image(1, "https://cdn/x/files/old.jpg?v=1", "aflalo-new.jpg", 48) is True
    assert renamed == ["aflalo-new.jpg"]


def test_seo_copy_that_runs_out_of_tokens_comes_back_empty(monkeypatch):
    import types
    import ai_client
    reply = types.SimpleNamespace(stop_reason="max_tokens", content=[types.SimpleNamespace(type="text", text="TITLE: Elestra Top Crimson in Silk Crepe de")])
    fake = types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: reply))
    monkeypatch.setattr(ai_client, "_get_client", lambda: fake)
    assert ai_client.generate_seo("Elestra Top in Silk", "<p>Top</p>", "", "elestra-top-crimson", color="Crimson") == {"title": "", "description": ""}
