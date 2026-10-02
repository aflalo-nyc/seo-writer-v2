import os
from dotenv import load_dotenv

load_dotenv()

SHOPIFY_STORE = os.environ.get("SHOPIFY_STORE", "aflalo.myshopify.com")
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
# Webhooks created through the Admin API are signed with the app's client secret.
SHOPIFY_WEBHOOK_SECRET = os.environ.get("SHOPIFY_WEBHOOK_SECRET", SHOPIFY_CLIENT_SECRET)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Model that writes the SEO copy (brand voice matters here).
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5")
# Model that looks at each photo and says front / back / side / detail (simple task, high volume).
CLAUDE_VISION_MODEL = os.environ.get("CLAUDE_VISION_MODEL", "claude-sonnet-5")

PORT = int(os.environ.get("PORT", 4000))
# Public https URL of this app once hosted (needed for Shopify webhooks), e.g. https://aflalo-seo.onrender.com
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
# If set, every page except /webhooks/* and /health asks for this password (any username).
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
GEN_WORKERS = int(os.environ.get("GEN_WORKERS", 4))
# When a webhook sees a new photo: true = tag + rename it automatically; false = only log it for the Photos tab.
AUTO_APPLY_PHOTOS = os.environ.get("AUTO_APPLY_PHOTOS", "true").lower() in ("1", "true", "yes")
# On a product *update* event, only photos uploaded within this many hours are tagged automatically.
# Older untagged photos belong to the one-time cleanup in the Photos tab, where merch reviews them.
AUTO_TAG_MAX_AGE_HOURS = int(os.environ.get("AUTO_TAG_MAX_AGE_HOURS", 48))

CATEGORIES = ["denim", "bottoms", "fine jewelry", "dresses", "outerwear", "sweaters", "tops"]
