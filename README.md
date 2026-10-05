# Aflalo SEO Writer

**Current state and what's left: [STATUS.md](STATUS.md)**

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

## Status (2 Oct 2026) and the one remaining step

Live on Railway (workspace *AFLALO Projects*, project `aflalo-seo-writer`), webhooks registered, end-to-end test passed.
The only thing not working is **photo file renames**: the Shopify app the keys belong to (*Product Agent*, developer
*Daughters Group LLC*) lacks the `write_files` permission and cannot be edited by us. A replacement app has been created in
the Dev Dashboard but a **store owner (or staff with "install apps" permission)** must install it:

1. Signed in to the Aflalo admin as the store owner, open
   `https://admin.shopify.com/store/aflalo/oauth/install?client_id=aa086d5b664b8d3f47378026e0e252d6` and click **Install**.
   The consent screen must list read/write products and read/write files; if files are missing, add them under the app's
   *Access scopes* in the Dev Dashboard and release the version first.
2. In Railway, service `seo-writer` > Variables: replace `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` with the new app's
   client id and secret (Sanskriti has them). Railway redeploys.
3. In the app's **Setup & activity** tab click **Register webhooks** (they are per app). Then remove the old app's webhooks
   from a laptop that still has the old keys in `.env`:
   `python register_webhooks.py https://seo-writer-production-4bec.up.railway.app --remove`
4. Setup tab row *Can rename photo files* turns green. Test: Photos tab, any category, Generate on one row, Apply approved.

## Using your own Shopify app (recommended if you cannot edit the current one)

The app works with either kind of Shopify credential. Set **one** of these in `.env` / Railway:

- `SHOPIFY_CLIENT_ID` + `SHOPIFY_CLIENT_SECRET` from an app in the Shopify Dev Dashboard (what it uses today), or
- `SHOPIFY_ACCESS_TOKEN` (starts with `shpat_`) from a custom app created in Shopify admin, plus
  `SHOPIFY_WEBHOOK_SECRET` set to that app's *API secret key* so webhook signatures verify.

To create an admin custom app: Shopify admin > Settings > Apps and sales channels > Develop apps > Create an app >
Configure Admin API scopes: tick `read_products`, `write_products`, `read_files`, `write_files` > Save > Install app >
reveal the Admin API access token once and copy it. Then set the two variables above and restart.

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
| `AUTO_TAG_MAX_AGE_HOURS` | `48` | On a product update, only photos uploaded within this window are auto-tagged. Older ones are for the Photos tab cleanup. |
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
