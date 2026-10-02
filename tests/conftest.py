import os
import tempfile

# Must run before any app module is imported (config reads env at import; .env never overrides existing env).
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="seo-writer-test-")
os.environ["APP_PASSWORD"] = ""
os.environ["SHOPIFY_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
