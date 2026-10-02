"""Shopify Admin API client.

Reads and SEO writes go through GraphQL (one call returns every product with its SEO fields).
Image alt text uses the REST product-images endpoint, which works with the app's current
`write_products` permission. Renaming a photo's file uses GraphQL `fileUpdate`, which needs
the `write_files` permission (see README).
"""
import logging
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from config import SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET
from naming import basename_from_url

logger = logging.getLogger(__name__)

API_VERSION = "2026-04"
BASE_URL = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}"

_token: str | None = None
_token_expiry: float = 0


class ShopifyError(Exception):
    pass


def _get_access_token() -> str:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry - 60:
        return _token
    resp = requests.post(
        f"https://{SHOPIFY_STORE}/admin/oauth/access_token",
        data={"grant_type": "client_credentials", "client_id": SHOPIFY_CLIENT_ID, "client_secret": SHOPIFY_CLIENT_SECRET},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expiry = time.time() + data.get("expires_in", 86400)
    return _token


def _headers() -> dict:
    return {"X-Shopify-Access-Token": _get_access_token(), "Content-Type": "application/json"}


def gql(query: str, variables: dict | None = None, _retries: int = 3) -> dict:
    resp = requests.post(f"{BASE_URL}/graphql.json", headers=_headers(), json={"query": query, "variables": variables or {}}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        msg = "; ".join(e.get("message", "") for e in data["errors"])
        if "hrottled" in msg and _retries > 0:
            time.sleep(2)
            return gql(query, variables, _retries - 1)
        raise ShopifyError(msg)
    return data["data"]


def _check_user_errors(payload: dict, what: str) -> None:
    errs = payload.get("userErrors") or []
    if errs:
        raise ShopifyError(f"{what}: " + "; ".join(f"{e.get('code', '')} {e.get('message', '')}".strip() for e in errs))


def gid_to_id(gid: str) -> int:
    return int(str(gid).rsplit("/", 1)[-1])


def product_gid(product_id: int) -> str:
    return f"gid://shopify/Product/{int(product_id)}"


# ---------------------------------------------------------------- products + SEO

_PRODUCT_FIELDS = """
  id legacyResourceId title handle tags status descriptionHtml createdAt
  seo { title description }
"""


def _normalize_product(node: dict) -> dict:
    seo = node.get("seo") or {}
    return {
        "id": int(node["legacyResourceId"]),
        "gid": node["id"],
        "title": node["title"],
        "handle": node["handle"],
        "tags": ", ".join(node.get("tags") or []),
        "status": (node.get("status") or "").lower(),
        "body_html": node.get("descriptionHtml") or "",
        "created_at": node.get("createdAt"),
        "seo": {"title_tag": seo.get("title") or "", "description_tag": seo.get("description") or ""},
    }


def get_all_products() -> list[dict]:
    """Every product in the store with its SEO title/description, in a handful of calls."""
    query = f"""
    query($cursor: String) {{
      products(first: 100, after: $cursor) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {_PRODUCT_FIELDS} }}
      }}
    }}"""
    products, cursor = [], None
    while True:
        page = gql(query, {"cursor": cursor})["products"]
        products.extend(_normalize_product(n) for n in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return products
        cursor = page["pageInfo"]["endCursor"]


def get_product(product_id: int) -> dict | None:
    data = gql(f"query($id: ID!) {{ product(id: $id) {{ {_PRODUCT_FIELDS} }} }}", {"id": product_gid(product_id)})
    return _normalize_product(data["product"]) if data.get("product") else None


def set_seo(product_id: int, seo_title: str, seo_description: str) -> None:
    """Write the product's Search engine listing (page title + meta description)."""
    mutation = """
    mutation($product: ProductUpdateInput!) {
      productUpdate(product: $product) { product { id } userErrors { field message } }
    }"""
    data = gql(mutation, {"product": {"id": product_gid(product_id), "seo": {"title": seo_title, "description": seo_description}}})
    _check_user_errors(data["productUpdate"], "productUpdate")
    logger.info("Updated SEO for product %s", product_id)


# ---------------------------------------------------------------- images (REST)

def get_product_images(product_id: int) -> list[dict]:
    resp = requests.get(f"{BASE_URL}/products/{product_id}/images.json", headers=_headers(), params={"fields": "id,position,src,alt"}, timeout=15)
    resp.raise_for_status()
    return [
        {"id": img["id"], "position": img.get("position", 0), "src": img["src"], "alt": img.get("alt") or "", "filename": basename_from_url(img["src"])}
        for img in resp.json().get("images", [])
    ]


def attach_images(products: list[dict]) -> None:
    def _fetch(p):
        p["images"] = get_product_images(p["id"])
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in [ex.submit(_fetch, p) for p in products]:
            f.result()


def set_image_alt(product_id: int, image_id: int, alt_text: str) -> None:
    requests.put(
        f"{BASE_URL}/products/{product_id}/images/{image_id}.json",
        headers=_headers(), json={"image": {"id": image_id, "alt": alt_text}}, timeout=15,
    ).raise_for_status()
    logger.info("Updated alt text for product %s image %s", product_id, image_id)


# ---------------------------------------------------------------- file renames (GraphQL, needs write_files)

def get_media_by_filename(product_id: int) -> dict[str, str]:
    """{current file name -> MediaImage gid} for a product's photos."""
    data = gql(
        """query($id: ID!) { product(id: $id) { media(first: 100) { nodes { id ... on MediaImage { image { url } } } } } }""",
        {"id": product_gid(product_id)},
    )
    out = {}
    for m in (data.get("product") or {}).get("media", {}).get("nodes", []):
        url = (m.get("image") or {}).get("url")
        if url:
            out[basename_from_url(url)] = m["id"]
    return out


def rename_file(media_gid: str, filename: str) -> None:
    mutation = """
    mutation($files: [FileUpdateInput!]!) {
      fileUpdate(files: $files) { files { id } userErrors { field message code } }
    }"""
    try:
        data = gql(mutation, {"files": [{"id": media_gid, "filename": filename}]})
    except ShopifyError as e:
        if "write_files" in str(e) or "Access denied" in str(e):
            raise ShopifyError("Renaming files needs the `write_files` permission on the Shopify app (see README, step 'Photo renames').") from e
        raise
    _check_user_errors(data["fileUpdate"], "fileUpdate")
    logger.info("Renamed %s -> %s", media_gid, filename)


def rename_product_image(product_id: int, current_src: str, new_filename: str) -> None:
    media = get_media_by_filename(product_id)
    gid = media.get(basename_from_url(current_src))
    if not gid:
        raise ShopifyError(f"Could not find media for {basename_from_url(current_src)} on product {product_id}")
    rename_file(gid, new_filename)


# ---------------------------------------------------------------- setup helpers

def get_access_scopes() -> list[str]:
    resp = requests.get(f"https://{SHOPIFY_STORE}/admin/oauth/access_scopes.json", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return sorted(s["handle"] for s in resp.json().get("access_scopes", []))


def list_webhooks() -> list[dict]:
    data = gql("""{ webhookSubscriptions(first: 50) { nodes { id topic endpoint { __typename ... on WebhookHttpEndpoint { callbackUrl } } } } }""")
    return [
        {"id": n["id"], "topic": n["topic"], "url": (n.get("endpoint") or {}).get("callbackUrl", "")}
        for n in data["webhookSubscriptions"]["nodes"]
    ]


def create_webhook(topic: str, url: str) -> str:
    mutation = """
    mutation($topic: WebhookSubscriptionTopic!, $sub: WebhookSubscriptionInput!) {
      webhookSubscriptionCreate(topic: $topic, webhookSubscription: $sub) {
        webhookSubscription { id } userErrors { field message }
      }
    }"""
    data = gql(mutation, {"topic": topic, "sub": {"uri": url, "format": "JSON"}})
    _check_user_errors(data["webhookSubscriptionCreate"], "webhookSubscriptionCreate")
    return data["webhookSubscriptionCreate"]["webhookSubscription"]["id"]


def delete_webhook(webhook_gid: str) -> None:
    data = gql("""mutation($id: ID!) { webhookSubscriptionDelete(id: $id) { deletedWebhookSubscriptionId userErrors { field message } } }""", {"id": webhook_gid})
    _check_user_errors(data["webhookSubscriptionDelete"], "webhookSubscriptionDelete")


WEBHOOK_TOPICS = {
    "PRODUCTS_CREATE": "/webhooks/products/create",
    "PRODUCTS_UPDATE": "/webhooks/products/update",
}


def ensure_webhooks(base_url: str) -> dict:
    """Create the two product webhooks pointing at this app if they don't exist yet."""
    base_url = base_url.rstrip("/")
    existing = list_webhooks()
    created = []
    for topic, path in WEBHOOK_TOPICS.items():
        url = base_url + path
        if not any(w["topic"] == topic and w["url"] == url for w in existing):
            create_webhook(topic, url)
            created.append({"topic": topic, "url": url})
    return {"created": created, "webhooks": list_webhooks()}


def remove_webhooks(base_url: str) -> int:
    base_url = base_url.rstrip("/")
    n = 0
    for w in list_webhooks():
        if w["url"].startswith(base_url + "/webhooks/"):
            delete_webhook(w["id"])
            n += 1
    return n
