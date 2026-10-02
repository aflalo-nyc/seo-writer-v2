import base64
import hashlib
import hmac
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, Response, abort, jsonify, render_template, request

from config import (
    ANTHROPIC_API_KEY, APP_PASSWORD, AUTO_APPLY_PHOTOS, CATEGORIES, CLAUDE_MODEL, CLAUDE_VISION_MODEL,
    GEN_WORKERS, PORT, PUBLIC_URL, SHOPIFY_STORE, SHOPIFY_WEBHOOK_SECRET,
)
import shopify_client as sh
from ai_client import classify_view, generate_seo
from naming import build_alt, build_filename, color_from_handle, extension_from_url, is_standard_alt, is_standard_filename
from store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ----------------------------------------------------------------------------- catalog cache

_products: list[dict] | None = None
_lock = threading.RLock()


def _load_all(force: bool = False) -> list[dict]:
    global _products
    with _lock:
        if _products is None or force:
            logger.info("Fetching all products from Shopify...")
            _products = sh.get_all_products()
            logger.info("Loaded %d products", len(_products))
        return _products


def _find(product_id) -> dict | None:
    return next((p for p in _load_all() if p["id"] == int(product_id)), None)


def _upsert_cached(product: dict) -> None:
    with _lock:
        prods = _load_all()
        for i, p in enumerate(prods):
            if p["id"] == product["id"]:
                if "images" in p and "images" not in product:
                    product["images"] = p["images"]
                prods[i] = product
                return
        prods.append(product)


def _tags(p: dict) -> list[str]:
    return [t.strip().lower() for t in (p.get("tags") or "").split(",") if t.strip()]


def _group_by_category(products: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {cat: [] for cat in CATEGORIES}
    grouped["other"] = []
    for p in products:
        if p.get("status") != "active":
            continue
        tags = _tags(p)
        matched = False
        for cat in CATEGORIES:
            if cat in tags:
                grouped[cat].append(p)
                matched = True
        if not matched:
            grouped["other"].append(p)
    return grouped


def _category_products(cat: str) -> list[dict]:
    return _group_by_category(_load_all()).get(cat, [])


def _category_of(p: dict) -> str:
    tags = _tags(p)
    return next((c for c in CATEGORIES if c in tags), "other")


def _has_seo(p: dict) -> bool:
    return bool(p["seo"]["title_tag"] and p["seo"]["description_tag"])


def _ensure_images(products: list[dict]) -> None:
    need = [p for p in products if "images" not in p]
    if need:
        sh.attach_images(need)


def _references_for(product: dict, n: int = 4) -> list[dict]:
    """Live, already-approved SEO copy from the same category, newest first."""
    pool = [p for p in _category_products(_category_of(product)) if p["id"] != product["id"] and _has_seo(p)]
    pool.sort(key=lambda p: p.get("created_at") or "", reverse=True)          # newest first
    pool.sort(key=lambda p: "crafted" not in p["seo"]["description_tag"].lower())  # on-formula copy first
    return [{"title": p["title"], "seo_title": p["seo"]["title_tag"], "seo_desc": p["seo"]["description_tag"]} for p in pool[:n]]


def _generate_for(product: dict) -> dict:
    return generate_seo(product["title"], product.get("body_html", ""), product.get("tags", ""), product.get("handle", ""),
                        references=_references_for(product))


def _photo_needs_work(img: dict) -> bool:
    return not (is_standard_alt(img.get("alt", "")) and is_standard_filename(img.get("filename", "")))


def _photo_proposal(product: dict, img: dict) -> dict:
    view = classify_view(img["src"], product["title"])
    color = color_from_handle(product["handle"], product["title"])
    return {
        "view": view,
        "alt": build_alt(product["title"], color, view),
        "filename": build_filename(product["title"], color, view, img["position"], extension_from_url(img["src"])),
    }


def _product_json(p: dict) -> dict:
    return {
        "id": p["id"], "title": p["title"], "handle": p["handle"],
        "seo_title": p["seo"]["title_tag"], "seo_desc": p["seo"]["description_tag"],
        "created_at": p.get("created_at"), "pending": store.is_pending(p["id"]),
    }


def _image_json(img: dict) -> dict:
    return {**img, "needs_work": _photo_needs_work(img)}


# ----------------------------------------------------------------------------- auth

@app.before_request
def _require_password():
    if not APP_PASSWORD or request.path.startswith("/webhooks/") or request.path == "/health":
        return None
    auth = request.authorization
    if auth and hmac.compare_digest(auth.password or "", APP_PASSWORD):
        return None
    return Response("Password required", 401, {"WWW-Authenticate": 'Basic realm="Aflalo SEO Writer"'})


# ----------------------------------------------------------------------------- pages

@app.route("/")
def index():
    grouped = _group_by_category(_load_all())
    stats = {cat: {"total": len(prods)} for cat, prods in grouped.items()}
    return render_template("index.html", stats=stats, categories=CATEGORIES + ["other"], pending_count=len(store.get_pending()),
                           store_handle=SHOPIFY_STORE.split(".")[0])


@app.route("/health")
def health():
    return jsonify({"ok": True, "products_loaded": _products is not None, "pending": len(store.get_pending())})


# ----------------------------------------------------------------------------- SEO copy

@app.route("/category/<cat>")
def category(cat: str):
    products = _category_products(cat)
    return jsonify({"products": [_product_json(p) for p in products], "missing": sum(1 for p in products if not _has_seo(p))})


@app.route("/generate", methods=["POST"])
def generate():
    product = _find(request.json["product_id"])
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(_generate_for(product))


@app.route("/generate-category", methods=["POST"])
def generate_category():
    targets = [p for p in _category_products(request.json["category"]) if not _has_seo(p)]
    results = {}
    with ThreadPoolExecutor(max_workers=GEN_WORKERS) as ex:
        futures = {ex.submit(_generate_for, p): p for p in targets}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                results[p["id"]] = fut.result()
            except Exception as e:
                logger.error("Failed to generate SEO for %s: %s", p["title"], e)
                results[p["id"]] = {"error": str(e)}
    return jsonify(results)


def _publish_seo(items: list[dict], source: str) -> dict:
    published, errors = [], []
    for item in items:
        pid = int(item["product_id"])
        try:
            sh.set_seo(pid, item["title"], item["description"])
            p = _find(pid)
            if p:
                p["seo"] = {"title_tag": item["title"], "description_tag": item["description"]}
            store.remove_pending([pid])
            store.log("seo_published", product_id=pid, title=(p or {}).get("title", ""), source=source)
            published.append(pid)
        except Exception as e:
            logger.error("Failed to publish SEO for product %s: %s", pid, e)
            errors.append({"product_id": pid, "error": str(e)})
    return {"published": published, "errors": errors}


@app.route("/publish", methods=["POST"])
def publish():
    return jsonify(_publish_seo(request.json, source="seo tab"))


# ----------------------------------------------------------------------------- pending queue (merch approval)

@app.route("/pending")
def pending():
    return jsonify({"pending": store.get_pending()})


@app.route("/pending/approve", methods=["POST"])
def pending_approve():
    return jsonify(_publish_seo(request.json, source="approval queue"))


@app.route("/pending/dismiss", methods=["POST"])
def pending_dismiss():
    ids = [int(i) for i in request.json.get("product_ids", [])]
    store.remove_pending(ids)
    for pid in ids:
        store.log("seo_dismissed", product_id=pid)
    return jsonify({"dismissed": ids})


# ----------------------------------------------------------------------------- photos (alt text + file names)

@app.route("/photos/<cat>")
def photos(cat: str):
    products = _category_products(cat)
    _ensure_images(products)
    out = []
    for p in products:
        out.append({
            "id": p["id"], "title": p["title"], "handle": p["handle"],
            "color": color_from_handle(p["handle"], p["title"]),
            "images": [_image_json(img) for img in p.get("images", [])],
        })
    missing = sum(1 for p in products for img in p.get("images", []) if _photo_needs_work(img))
    return jsonify({"products": out, "missing": missing})


def _find_image(product_id, image_id):
    product = _find(product_id)
    if not product:
        return None, None
    _ensure_images([product])
    img = next((i for i in product["images"] if i["id"] == int(image_id)), None)
    return product, img


@app.route("/photos/propose", methods=["POST"])
def photos_propose():
    product, img = _find_image(request.json["product_id"], request.json["image_id"])
    if not img:
        return jsonify({"error": "Image not found"}), 404
    return jsonify(_photo_proposal(product, img))


@app.route("/photos/propose-category", methods=["POST"])
def photos_propose_category():
    products = _category_products(request.json["category"])
    _ensure_images(products)
    overwrite = request.json.get("overwrite", False)
    targets = [(p, img) for p in products for img in p.get("images", []) if overwrite or _photo_needs_work(img)]
    results = {}
    with ThreadPoolExecutor(max_workers=GEN_WORKERS) as ex:
        futures = {ex.submit(_photo_proposal, p, img): (p, img) for p, img in targets}
        for fut in as_completed(futures):
            p, img = futures[fut]
            key = f"{p['id']}-{img['id']}"
            try:
                results[key] = fut.result()
            except Exception as e:
                logger.error("Failed to classify %s image %s: %s", p["title"], img["id"], e)
                results[key] = {"error": str(e)}
    return jsonify(results)


def _apply_photo(product: dict, img: dict, alt: str, filename: str | None, rename: bool) -> dict:
    """Write alt text and (optionally) rename the file. Returns what happened."""
    result = {"product_id": product["id"], "image_id": img["id"], "renamed": False, "rename_error": None}
    sh.set_image_alt(product["id"], img["id"], alt)
    img["alt"] = alt
    if rename and filename and filename != img.get("filename"):
        try:
            sh.rename_product_image(product["id"], img["src"], filename)
            img["filename"] = filename
            result["renamed"] = True
        except Exception as e:
            result["rename_error"] = str(e)
    return result


@app.route("/photos/apply", methods=["POST"])
def photos_apply():
    published, errors = [], []
    for item in request.json:
        try:
            product, img = _find_image(item["product_id"], item["image_id"])
            if not img:
                raise ValueError("Image not found")
            res = _apply_photo(product, img, item["alt"].strip(), item.get("filename", "").strip(), item.get("rename", True))
            store.mark_media_processed(img["id"])
            store.log("photo_tagged", product_id=product["id"], title=product["title"], image_id=img["id"], alt=item["alt"],
                      filename=img["filename"], renamed=res["renamed"], error=res["rename_error"], source="photos tab")
            published.append(res)
        except Exception as e:
            errors.append({"product_id": item.get("product_id"), "image_id": item.get("image_id"), "error": str(e)})
    return jsonify({"published": published, "errors": errors})


# ----------------------------------------------------------------------------- activity + setup

@app.route("/activity")
def activity():
    return jsonify({"activity": store.get_activity(200)})


@app.route("/status")
def status():
    out = {
        "store": SHOPIFY_STORE, "public_url": PUBLIC_URL, "password_protected": bool(APP_PASSWORD),
        "auto_apply_photos": AUTO_APPLY_PHOTOS, "model": CLAUDE_MODEL, "vision_model": CLAUDE_VISION_MODEL,
        "anthropic_key_set": bool(ANTHROPIC_API_KEY), "pending": len(store.get_pending()),
        "webhooks": [], "scopes": [],
    }
    try:
        out["scopes"] = sh.get_access_scopes()
        out["shopify_connected"] = True
    except Exception as e:
        out["shopify_connected"] = False
        out["error"] = str(e)
    out["can_rename_files"] = "write_files" in out["scopes"]
    try:
        out["webhooks"] = sh.list_webhooks()
    except Exception as e:
        out["webhooks_error"] = str(e)
    expected = {PUBLIC_URL + path for path in sh.WEBHOOK_TOPICS.values()} if PUBLIC_URL else set()
    have = {w["url"] for w in out["webhooks"]}
    out["webhooks_ok"] = bool(expected) and expected.issubset(have)
    return jsonify(out)


@app.route("/setup/register-webhooks", methods=["POST"])
def setup_register_webhooks():
    url = ((request.json or {}).get("public_url") or PUBLIC_URL).strip().rstrip("/")
    if not url.startswith("https://"):
        return jsonify({"error": "Set PUBLIC_URL to the https address where this app is hosted first."}), 400
    try:
        return jsonify(sh.ensure_webhooks(url))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/reload", methods=["POST"])
def reload_products():
    _load_all(force=True)
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------- Shopify webhooks

def _verify_webhook(raw: bytes, header: str) -> bool:
    if not SHOPIFY_WEBHOOK_SECRET:
        return False
    digest = base64.b64encode(hmac.new(SHOPIFY_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(digest, header or "")


@app.route("/webhooks/products/<action>", methods=["POST"])
def webhook_products(action: str):
    if action not in ("create", "update"):
        abort(404)
    raw = request.get_data()
    if not _verify_webhook(raw, request.headers.get("X-Shopify-Hmac-Sha256", "")):
        return jsonify({"error": "invalid hmac"}), 401
    payload = json.loads(raw or b"{}")
    pid = payload.get("id")
    if pid:
        threading.Thread(target=_handle_product_event, args=(action, int(pid)), daemon=True).start()
    return jsonify({"ok": True})


def _handle_product_event(action: str, product_id: int) -> None:
    try:
        product = sh.get_product(product_id)
        if not product:
            return
        _upsert_cached(product)
        _maybe_queue_seo(product, action)
        _process_photos(product)
    except Exception as e:
        logger.exception("Webhook handling failed for product %s", product_id)
        store.log("error", product_id=product_id, where=f"webhook products/{action}", error=str(e))


def _maybe_queue_seo(product: dict, action: str) -> None:
    """Generate SEO copy for a product that has none and park it in the approval queue."""
    if _has_seo(product) or store.is_pending(product["id"]):
        return
    body = re.sub(r"<[^>]+>", " ", product.get("body_html") or "").strip()
    if not product["title"] or product["title"].lower().startswith("untitled") or len(body) < 40:
        if action == "create":
            store.log("seo_waiting", product_id=product["id"], title=product["title"],
                      reason="Will generate once the product has a title and a description")
        return
    seo = _generate_for(product)
    store.add_pending(product["id"], {
        "title": product["title"], "handle": product["handle"], "status": product["status"],
        "seo_title": seo["title"], "seo_desc": seo["description"], "source": f"webhook products/{action}",
    })
    store.log("seo_generated", product_id=product["id"], title=product["title"], source=f"webhook products/{action}")


def _process_photos(product: dict) -> None:
    """Tag (alt text) and rename any photo on the product that doesn't follow the convention yet."""
    images = sh.get_product_images(product["id"])
    product["images"] = images
    targets = [img for img in images if _photo_needs_work(img) and not store.is_media_processed(img["id"])]
    if not targets:
        return
    if not AUTO_APPLY_PHOTOS:
        store.log("photos_waiting", product_id=product["id"], title=product["title"], count=len(targets),
                  reason="AUTO_APPLY_PHOTOS is off; use the Photos tab")
        return
    for img in targets:
        # Mark first: our own alt/rename writes trigger another products/update webhook.
        store.mark_media_processed(img["id"])
        try:
            prop = _photo_proposal(product, img)
            res = _apply_photo(product, img, prop["alt"], prop["filename"], rename=not is_standard_filename(img["filename"]))
            store.log("photo_tagged", product_id=product["id"], title=product["title"], image_id=img["id"], view=prop["view"],
                      alt=prop["alt"], filename=img["filename"], renamed=res["renamed"], error=res["rename_error"], source="webhook")
        except Exception as e:
            logger.exception("Photo tagging failed for %s image %s", product["title"], img["id"])
            store.log("error", product_id=product["id"], title=product["title"], image_id=img["id"], where="photo tagging", error=str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True, threaded=True)
