# API reference

Base URL: `http://localhost:8000` (prod: `https://api.sarkarisaar.com`).
Interactive docs at `/docs` outside production.

## Auth

| Caller | Header |
|---|---|
| Public feed | none |
| Signed-in user | `Authorization: Bearer <supabase access token>` |
| Admin (human) | `Authorization: Bearer <token>` — must have a row in `admin_users` |
| Admin (machine) | `X-Admin-Key: <ADMIN_API_KEY>` |

## Public

### `GET /api/entries`

Approved entries only. Cached 5 minutes per filter combination.

| Param | Type | Notes |
|---|---|---|
| `category` | string | Comma-separated: `tender,naukri` |
| `state` | string | Comma-separated: `RJ,UP` |
| `search` | string | Full-text, with a trigram fallback when it finds nothing |
| `urgency` | string | Comma-separated: `high,critical` |
| `deadline_before` | date | ISO |
| `sort` | string | `published_at` (default), `deadline` |
| `page` | int | ≥ 1 |
| `limit` | int | ≤ 50, default 20 |

```json
{ "entries": [...], "total": 156, "page": 1, "limit": 20, "has_more": true }
```

Unknown filter values are dropped rather than erroring, so a bad `category`
returns an unfiltered page, and a filter matching nothing returns `entries: []`
with `total: 0`.

### `GET /api/entries/{id}`

One approved entry. `404` if missing, rejected or still pending.

### `GET /api/entries/{id}/related`

Up to 10 approved entries sharing the category and state.

### `GET /api/stats`

```json
{ "total_entries": 2847, "entries_today": 43, "states_covered": 36,
  "sources_active": 52, "categories": { "tender": 1203, "naukri": 891 } }
```

## Subscriptions

### `POST /api/subscribe`

```json
{ "email": "user@example.com", "phone": "+919876543210",
  "channel": "email", "frequency": "weekly",
  "categories": ["tender"], "states": ["RJ"] }
```

`email` or `phone` is required; `channel` decides which. Subscribing an address
that already exists **updates** it rather than creating a duplicate. Rate limited
to 3 attempts per identity per hour (`429` beyond that).

### `GET /api/verify?token=…` · `GET /api/unsubscribe?token=…`

Both redirect back to the frontend. Unsubscribe is one click, no login.

## User (bearer token)

| Endpoint | Purpose |
|---|---|
| `POST /api/bookmarks/{entry_id}` | Toggle; returns `{"bookmarked": bool}` |
| `GET /api/bookmarks` | The user's saved entries |
| `GET /api/preferences` | Digest settings |
| `PATCH /api/preferences` | Update channel, frequency, categories, states |
| `GET /api/payments/plan` | Effective plan + unlocked features |
| `POST /api/payments/create-subscription` | `{plan, period}` → Razorpay checkout URL |

An expired paid plan reports as `free` — expiry is applied on read, not only by
the nightly job.

## Admin

| Endpoint | Purpose |
|---|---|
| `GET /api/admin/entries/pending` | Review queue (AI-summarised, unapproved) |
| `PATCH /api/admin/entries/{id}/approve` | Publish; invalidates the feed cache |
| `PATCH /api/admin/entries/{id}/reject` | Never appears publicly |
| `PATCH /api/admin/entries/{id}` | Edit title, summaries, category, deadline… |
| `POST /api/admin/entries/bulk-approve` | `{entry_ids: [...]}` |
| `POST /api/admin/entries/bulk-approve-confident` | `{min_confidence, limit}` |
| `POST /api/admin/scrape?source=&wait=` | Run one scraper or all |
| `GET /api/admin/scraper-status` | Source health, colour-coded |
| `POST /api/admin/process?batch_size=` | Run an AI batch; `429` at either daily cap |
| `POST /api/admin/send-digests?frequency=` | `daily` or `weekly` |
| `POST /api/admin/maintenance` | Expire past-deadline entries, downgrade lapsed plans |
| `GET /api/admin/pending-count` | Queue depth, today's AI spend and request count |

The last three exist so an external scheduler can drive the same jobs the
in-process one runs — see `.github/workflows/cron.yml`, which is how the free
deployment schedules work on a host that sleeps.

Two daily caps guard AI processing, and `/api/admin/process` returns `429` when
either is hit: a **spend** cap in rupees (`AI_DAILY_CAP_INR`, meaningful on paid
providers) and a **request** cap (`AI_DAILY_REQUEST_CAP`, which is what actually
protects a free tier, where spend is always ₹0).

Approving an entry with no summary returns `400` — run AI processing first.

## Webhooks

| Endpoint | Notes |
|---|---|
| `POST /api/webhooks/razorpay` | HMAC-SHA256 over the raw body in `X-Razorpay-Signature`. Fails closed if `RAZORPAY_WEBHOOK_SECRET` is unset. |
| `POST /api/webhooks/gupshup` | Delivery receipts and inbound messages. `STOP` unsubscribes. |

## Health

`GET /health` — liveness. `GET /health/deep` — also touches the database.

## Errors

Standard FastAPI shape: `{"detail": "..."}`. `422` for validation, `401`/`403`
for auth, `429` for rate limits and the AI daily cap, `500` with a generic
message in production.
