# SEO Writer: status and next steps

Owner: Gloria Melidoni (handed over by Sanskriti Akhoury, 2026-10-02)
Last checked: 2026-10-05

## State: live, except photo file renames

| | |
|---|---|
| App | https://seo-writer-production-4bec.up.railway.app (password protected) |
| Service | Railway `aflalo-seo-writer` → `seo-writer` |
| SEO title + meta description | Working. New Shopify products get copy written and parked in the **Approval queue**. Nothing goes live until someone approves it. |
| Photo alt text | Working. Applied automatically to new photos (last seen on 2026-10-05). |
| Photo file renames | **Not working.** |
| Tests | 14 pass |

Renames fail because the Shopify app whose keys the service uses (*Product Agent*, made by
*Daughters Group LLC*) has no `write_files` permission, and we can't edit that app. Sanskriti made a
replacement app in the Shopify Dev Dashboard, but it only works once a store owner installs it.

## To finish

1. **Store owner installs the new app** (Sarena, or anyone with "install apps" permission). Signed in to
   the Aflalo admin, open
   `https://admin.shopify.com/store/aflalo/oauth/install?client_id=aa086d5b664b8d3f47378026e0e252d6`
   and click Install. The consent screen must list read/write **products** and read/write **files**.
   If files is missing, add it under the app's Access scopes in the Dev Dashboard, release the version,
   then install.
2. **Swap the keys on Railway.** `seo-writer` → Variables: replace `SHOPIFY_CLIENT_ID` and
   `SHOPIFY_CLIENT_SECRET` with the new app's. The secret is in the Dev Dashboard under the app's
   settings, and Sanskriti also has it.
3. **Move the webhooks to the new app.** In the app, open Setup & activity → Register webhooks. Then
   remove the old app's webhooks from a laptop with the *old* keys in `.env`:
   `python register_webhooks.py https://seo-writer-production-4bec.up.railway.app --remove`
4. **Check it.** In the Setup tab, *Can rename photo files* turns green. Then go to the Photos tab →
   pick one category → Generate on one row → Apply approved, and confirm the file name changed in
   Shopify.

## Open, not blocking

- **Who approves the queue?** SEO copy only goes live after a person approves it, so the Approval
  queue needs an owner from merch.
- **Older products.** Automatic tagging only touches photos uploaded in the last 48 h. To fix alt text
  and file names on the existing ~590 products, use the Photos tab one category at a time.
- **Repo is public.** No secrets in it. Make it private with the other three, then confirm a Railway
  redeploy still builds.

## Where things are

How to run it, settings and the naming rule: `README.md`. The naming convention itself: `naming.py`.
