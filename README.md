# SarkariSaar

Indian government notifications — scraped from official portals, summarised by
Claude in plain English and Hindi, delivered on the web, by email and on WhatsApp.

Built from `docs/PRD.md`.

```
sarkarisaar/
├── frontend/    Next.js 16 (App Router, Tailwind v4) → Vercel
├── backend/     FastAPI (Python 3.12) → Railway
├── supabase/    SQL migrations + seed data
└── docs/        PRD, API reference, scraper guide
```

## Running this for free

The default configuration costs nothing:

| Piece | Service | Free allowance |
|---|---|---|
| Frontend | Vercel Hobby | Free |
| Database + auth | Supabase | 500MB |
| Backend | Render free web service | Sleeps after 15 min idle |
| **AI summaries** | **Groq free tier** | **No card; per-model daily quota** |
| Scheduler | GitHub Actions cron | Free (public repos) |
| Cache | — | In-memory fallback; Upstash optional |
| Email | Resend | 3,000/month |

Two things are deliberately **not** free and are off by default: WhatsApp
(Gupshup charges per message) and Claude (no free tier). Neither is needed to
run the product.

**Why the scheduler moved out of the app.** APScheduler runs in-process, so on a
free host that sleeps when idle it stops firing. `.github/workflows/cron.yml`
drives the same jobs through the admin API instead, and the request wakes the
service on its way in. Set `SCHEDULER_ENABLED=false` when using it, or every job
runs twice.

**Switching to Claude later** is one env var — `AI_PROVIDER=anthropic`. The
summaries, especially the Hindi, are better; budget roughly ₹2.5 per
notification.

## Quick start

You need a Supabase project and a Groq API key
([free, no credit card](https://console.groq.com/keys)). `AI_PROVIDER=gemini`
is an equally free alternative if you'd rather use Google.

**1. Database**

Run the migrations in order in the Supabase SQL editor (`supabase/migrations/001…008`),
then `supabase/seed.sql` for test sources and entries.

Or just run `./scripts/dev-setup.sh`, which does all of steps 2 and 3 and then
lists whichever secrets are still blank.

**2. Backend**

Use Python 3.13 (or 3.12 — what the Dockerfile ships). On 3.14 there is no
prebuilt `cryptography` wheel yet, so pip drops to compiling it from Rust and
the install fails on most machines. `backend/.python-version` pins this for
pyenv; `python3 -m venv` ignores it, so name the interpreter explicitly:

```bash
cd backend
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # fill in SUPABASE_* and GROQ_API_KEY
.venv/bin/uvicorn app.main:app --reload
```

API on http://localhost:8000, docs at `/docs`.

**3. Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in NEXT_PUBLIC_SUPABASE_*
npm run dev
```

App on http://localhost:3000.

**4. Fetch and summarise some real entries**

```bash
./scripts/real-data.sh --purge
```

`--purge` deletes the seed rows first, so what you are left with is only what
the scrapers actually pulled from the government portals — the seed data is
invented and its URLs do not resolve. The script scrapes every active source,
then loops `/api/admin/process` until the queue drains, because Groq's free
tier caps tokens per minute and one call only summarises ten entries.

By hand, if you prefer:

```bash
curl -X POST localhost:8000/api/admin/scrape -H "X-Admin-Key: $ADMIN_API_KEY"
curl -X POST localhost:8000/api/admin/process -H "X-Admin-Key: $ADMIN_API_KEY"
```

Anything the AI scores below 0.90 confidence waits in `/admin` for review.

## Tests

```bash
cd backend && .venv/bin/python -m pytest    # 153 tests
cd frontend && npm run build                # type-check + build
```

## Source status

Scraping government portals is mostly an access problem, not a parsing one.
What actually works today:

| Source | Status | Notes |
|---|---|---|
| PIB (`pib`) | **Working** — 24 entries/run | Behind an Akamai WAF that fingerprints the TLS handshake: httpx and headless Chromium both get 403, `curl_cffi` gets 200. Uses the English edition (`?reg=3&lang=1`). |
| SSC (`ssc`) | **Working** — JSON API | ssc.gov.in is an Angular SPA whose HTML has zero anchors, so HTML scraping cannot work. Uses the site's own public API instead. Covers Selection Post advertisements; the wider notice board needs more work. |
| GeM (`gem`) | **Working** — 50 bids/run | `/all-bids` is a shell; the listing comes from a JSON endpoint. CSRF token arrives as the `csrf_gem_cookie` cookie and must be echoed in a field named `csrf_bd_gem_nk` — the names deliberately differ, and a mismatch is a bare 403. ~47,000 live bids; we take the newest 5 pages. |
| Rajasthan eProc (`raj_eproc`) | **Blocked** — inactive | CAPTCHA-gated. The scraper raises rather than returning data; see the module docstring. |
| CPPP (`cppp`) | **Blocked** — inactive | Same NIC platform as Rajasthan, same CAPTCHA gate. |

**The NIC eProcurement family is a single blocker, not five.** CPPP, UP
(`etender.up.nic.in`), Maharashtra (`mahatenders`), MP (`mptenders`) and
Rajasthan all run the same `nicgep` software, and all five answer
*"Provide Captcha and click on Search button to list all active tenders."*
Solving one solves them all; until then, none of them are worth writing. That
covers most of the PRD's Batch 1 and Batch 4.

Also probed and blocked for other reasons: RRB, IBPS, eGazette and Bihar
eProc all fail TLS certificate verification (incomplete chains). MyScheme is a
Next.js SPA whose API returns 401 without a key. These need decisions, not just
parsing — see `docs/SCRAPER_GUIDE.md`.

`docs/SCRAPER_GUIDE.md` covers how to add a source and how to work through
these access problems.

## Deployment

**Free path (recommended to start):**

1. **Frontend → Vercel.** Root directory `frontend/`, add the `NEXT_PUBLIC_*` vars.
2. **Backend → Render.** New → Blueprint, pointed at this repo; `render.yaml`
   does the rest. Set the secret env vars in the dashboard.
3. **Scheduler → GitHub Actions.** Add repo secrets `API_BASE_URL` and
   `ADMIN_API_KEY`, and leave `SCHEDULER_ENABLED=false` on Render.
4. **Supabase.** Separate project for production.

**Paid path**, if you outgrow the free tiers: `backend/railway.toml` is still
here. Railway has no permanent free tier ($5/month Hobby minimum), but it
doesn't sleep, so you can set `SCHEDULER_ENABLED=true` and delete the cron
workflow. **Keep it at one replica** — the in-process scheduler would otherwise
double every scrape and send every digest twice.

## Disclaimer

Not affiliated with any government body. Summaries are AI-generated from public
notifications and can be wrong — the original source is linked on every entry
and is what counts.
# sarkari-site-design-practice
