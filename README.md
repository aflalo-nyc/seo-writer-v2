# Aflalo SEO Writer

Writes and publishes SEO copy (page title + meta description), image alt text and standard photo
file names for products on the Aflalo Shopify store. Runs as a small Flask app.

## What it does

| Area | Manual (in the app) | Automatic (Shopify webhooks) |
|---|---|---|
| SEO copy | **SEO** tab: Generate missing → tick → Publish approved. Writes straight into the product's *Search engine listing* in Shopify. | When a style is created in Shopify, copy is written using live same-category examples as reference and parked in the **Approval queue**. Merch approves → it goes live. Nothing is published without approval. |
| Photos | **Photos** tab: Generate → review alt text + file name → Apply approved. | When a photo is added to a product, it is classified (Model Front / Ghost Back / Detail …), given alt text `AFLALO <Title> – <Color> - <View>` and renamed `ProductName_Color_View_NN.ext`. |

The naming convention lives in one file: `naming.py`.

## Run on your laptop

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in the four keys (already done on Sanskriti's machine)
python app.py             # http://localhost:4000
```

Tests (no network, no keys needed):

```bash
python -m pytest tests -q
```

## Permissions the Shopify app needs

The app authenticates with the client id/secret of a Shopify custom app (Dev Dashboard → Apps).
Current scopes: `read_products`, `write_products`. That is enough for SEO copy and alt text.

**Photo renames** need one more scope. In the Shopify Dev Dashboard open the app → *Configuration* →
*Admin API access scopes* → tick **write_files** (and `read_files`) → Save → *Release* the new version.
No code change is needed; the **Setup** tab in this app shows a green tick once it is picked up
(the app fetches a fresh token every 24 h; restart it to force a new one).

## Turning on the automation (webhooks)

Shopify has to be able to reach this app over https, so it must be hosted (Render, Railway, Fly.io
all work; the `Procfile` is included). Then:

1. Set these environment variables on the host: the four keys from `.env`, plus
   `PUBLIC_URL=https://<your app address>` and `APP_PASSWORD=<something strong>`.
   Mount a persistent disk at `DATA_DIR` (default `./data`) so the approval queue survives restarts.
2. Register the webhooks, either from the **Setup** tab (button *Register webhooks*) or:

   ```bash
   python register_webhooks.py https://<your app address>
   ```

   This creates two subscriptions on the store: `PRODUCTS_CREATE` and `PRODUCTS_UPDATE`, signed
   with the app's client secret. The Setup tab shows them.
3. Create a test product in Shopify with a title, a description and a photo. Within about a minute the
   **Approval queue** shows its SEO copy and the **Setup → Activity** log shows the photo being tagged.

To test webhooks from your laptop without hosting, run a tunnel (e.g. `ngrok http 4000`) and use the
tunnel's https address as `PUBLIC_URL`. Remove the tunnel's webhooks afterwards with
`python register_webhooks.py https://<tunnel address> --remove`.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `AUTO_APPLY_PHOTOS` | `true` | Webhook tags and renames new photos on its own. `false` = they wait in the Photos tab. |
| `GEN_WORKERS` | `4` | How many products / photos are processed at once. |
| `CLAUDE_MODEL` | `claude-opus-5` | Writes the SEO copy. |
| `CLAUDE_VISION_MODEL` | `claude-sonnet-5` | Classifies photos. |
| `APP_PASSWORD` | empty | When set, the UI asks for it (any username). Webhooks are unaffected. |

## Files

- `app.py` — routes, approval queue, webhook handlers
- `shopify_client.py` — Shopify Admin API (GraphQL for products/SEO/files, REST for image alt)
- `ai_client.py` — Claude: SEO copy and photo view classification
- `naming.py` — file name + alt text convention (edit here to change it)
- `store.py` — JSON persistence for the queue, activity log and processed photos (`data/`)
- `register_webhooks.py` — one-off CLI to create/remove the store webhooks
- `templates/index.html` — the UI
