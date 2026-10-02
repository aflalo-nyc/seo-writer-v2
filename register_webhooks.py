"""Register (or remove) the Shopify webhooks that point at this app.

    python register_webhooks.py                       # uses PUBLIC_URL from .env
    python register_webhooks.py https://your-app.com  # explicit address
    python register_webhooks.py --remove              # delete this app's webhooks
"""
import sys
from config import PUBLIC_URL
import shopify_client as sh


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = (args[0] if args else PUBLIC_URL).rstrip("/")
    if not url.startswith("https://"):
        sys.exit("Give the public https address of the app (argument or PUBLIC_URL in .env).")
    if "--remove" in sys.argv:
        print(f"Removed {sh.remove_webhooks(url)} webhook(s) pointing at {url}")
        return
    result = sh.ensure_webhooks(url)
    for c in result["created"]:
        print("created", c["topic"], "->", c["url"])
    print("Webhooks now registered on the store:")
    for w in result["webhooks"]:
        print(f"  {w['topic']:<18} {w['url']}")


if __name__ == "__main__":
    main()
