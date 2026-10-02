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
    alts, renames = [], []
    monkeypatch.setattr(app_module.sh, "set_image_alt", lambda pid, iid, alt: alts.append((pid, iid, alt)))
    monkeypatch.setattr(app_module.sh, "rename_product_image", lambda pid, src, fn: renames.append((pid, fn)))

    app_module._handle_product_event("update", 11)

    assert alts == [(11, 501, "AFLALO Herve Sweater in Cashmere – Black - Model Back")]
    assert renames == [(11, "HerveSweater_Black_ModelBack_02.png")]
    assert store.is_media_processed(501)

    # A second update for the same product must not re-process the same photo.
    app_module._handle_product_event("update", 11)
    assert len(alts) == 1
