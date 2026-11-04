# SEO Writer: status and next steps

Owner: Gloria Melidoni (handed over by Sanskriti Akhoury, 2026-10-02)
Last checked: 2026-11-04

## State: live

| | |
|---|---|
| App | https://seo-writer-production-4bec.up.railway.app (Google sign-in, @aflalonyc.com accounts only) |
| Service | Railway `aflalo-seo-writer` → `seo-writer` |
| Shopify app | **SEO-WRITER-AI**: installed, its keys on Railway since 2026-10-05. Read/write products and files. |
| Webhooks | products/create and products/update, registered for SEO-WRITER-AI on 2026-10-14. |
| SEO title + meta description | Working. New Shopify products get copy written and parked in the **Approval queue**. Nothing goes live until someone approves it. 155 waiting on 2026-11-04. |
| Photo alt text | Working. Applied automatically to new photos. |
| Photo file renames | Working (e.g. `aflalo-nicolette-dress-balloon-iris-front-05.png`, 2026-11-03). |
| Tests | 36 pass |

## The old app's webhooks

The old app (*Product Agent*) still has webhooks pointing here. They're signed with its secret, not
the new app's, so the service has answered them with 401 since 2026-10-05. That's expected. Shopify
drops a webhook that keeps failing and emails the store about it ("Your webhook has been removed"):

- **products/update**: removed by Shopify on 2026-11-04 at 00:55 UTC. Sarena got the email.
- **products/create**: still there and failing. It fires less often, so Shopify will remove it later
  and send one more email like it. Nothing to do.

Neither email touches the new app's webhooks, which keep working. The old app's keys were only on
Sanskriti's laptop, so they can't be removed sooner with `register_webhooks.py --remove`.

To check: `railway logs --http --filter '@path:/webhooks/products/update'`. A 200 is the new app. A
401 is the old app, until Shopify removes its webhook.

## Open, not blocking

- **Who approves the queue?** SEO copy only goes live after a person approves it, so the Approval
  queue needs an owner from merch.
- **Older products.** Automatic tagging only touches photos uploaded in the last 48 h. To fix alt text
  and file names on the existing ~590 products, use the Photos tab one category at a time.
- **Repo is public** (still, on 2026-11-04). No secrets in it. Make it private with the other three,
  then confirm a Railway redeploy still builds.

## Where things are

How to run it, settings and the naming rule: `README.md`. The naming convention itself: `naming.py`.
