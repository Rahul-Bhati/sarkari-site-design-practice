# SarkariSaar — Implementation PRD for Claude Code

> **Purpose:** This document is the single source of truth for building SarkariSaar. Follow each milestone in order. Do NOT skip ahead. Complete every acceptance test before moving to the next milestone.

---

## PROJECT OVERVIEW

**What:** An AI-powered platform that scrapes Indian government websites, summarizes notifications in simple language, and delivers them to users via web, email, and WhatsApp.

**Architecture:**
- **Frontend:** Next.js 14 (App Router) → deployed on Vercel
- **Backend API + Scraping:** FastAPI (Python 3.12) → deployed on Railway
- **Database:** Supabase (PostgreSQL 15 + Auth + Storage + Realtime)
- **AI:** Anthropic Claude API (claude-sonnet-4-6)
- **Search:** Supabase full-text search (pg_trgm + tsvector) — upgrade to Meilisearch later if needed
- **Cache:** Upstash Redis (serverless, free tier)
- **Email:** Resend
- **WhatsApp:** Gupshup WhatsApp Business API
- **Payments:** Razorpay
- **Monitoring:** Sentry (both frontend and backend)

**Why this stack:**
- Vercel + Supabase = fastest to ship, generous free tiers, no DevOps overhead
- FastAPI on Railway = Python ecosystem for scraping (Scrapy, BeautifulSoup) + AI (Claude SDK), Railway has $5/month hobby plan with enough compute for scrapers
- Supabase = PostgreSQL with built-in auth, row-level security, realtime subscriptions, and storage — eliminates 4 separate services

---

## REPO STRUCTURE

```
sarkarisaar/
├── frontend/                    # Next.js app (deployed to Vercel)
│   ├── src/
│   │   ├── app/                 # App Router pages
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx         # Landing + feed
│   │   │   ├── feed/
│   │   │   │   └── page.tsx     # Full feed with filters
│   │   │   ├── entry/
│   │   │   │   └── [id]/
│   │   │   │       └── page.tsx # Single entry detail
│   │   │   ├── dashboard/
│   │   │   │   └── page.tsx     # User dashboard (saved, prefs)
│   │   │   ├── admin/
│   │   │   │   └── page.tsx     # Admin review queue
│   │   │   ├── pricing/
│   │   │   │   └── page.tsx
│   │   │   └── auth/
│   │   │       ├── login/
│   │   │       │   └── page.tsx
│   │   │       └── callback/
│   │   │           └── page.tsx
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── Navbar.tsx
│   │   │   │   ├── Footer.tsx
│   │   │   │   └── MobileNav.tsx
│   │   │   ├── feed/
│   │   │   │   ├── FeedCard.tsx
│   │   │   │   ├── CategoryFilter.tsx
│   │   │   │   ├── StateFilter.tsx
│   │   │   │   ├── SearchBar.tsx
│   │   │   │   ├── DeadlineBadge.tsx
│   │   │   │   └── FeedSkeleton.tsx
│   │   │   ├── subscribe/
│   │   │   │   └── SubscribeForm.tsx
│   │   │   └── ui/              # Shared UI primitives
│   │   │       ├── Button.tsx
│   │   │       ├── Input.tsx
│   │   │       ├── Select.tsx
│   │   │       ├── Badge.tsx
│   │   │       └── Toast.tsx
│   │   ├── lib/
│   │   │   ├── supabase/
│   │   │   │   ├── client.ts    # Browser client
│   │   │   │   ├── server.ts    # Server client (RSC)
│   │   │   │   └── middleware.ts
│   │   │   ├── api.ts           # FastAPI client wrapper
│   │   │   ├── constants.ts     # Categories, states, etc.
│   │   │   └── utils.ts
│   │   ├── hooks/
│   │   │   ├── useEntries.ts
│   │   │   ├── useAuth.ts
│   │   │   └── useSubscription.ts
│   │   └── types/
│   │       └── index.ts         # Shared TypeScript types
│   ├── public/
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── package.json
│
├── backend/                     # FastAPI app (deployed to Railway)
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── database.py          # Supabase client setup
│   │   ├── routers/
│   │   │   ├── entries.py       # GET /entries, GET /entries/{id}
│   │   │   ├── admin.py         # Admin review endpoints
│   │   │   ├── subscribe.py     # Subscription management
│   │   │   ├── webhooks.py      # Razorpay, Gupshup webhooks
│   │   │   └── health.py        # Health check
│   │   ├── services/
│   │   │   ├── summarizer.py    # Claude API summarization
│   │   │   ├── notifier.py      # Email + WhatsApp dispatch
│   │   │   ├── scheduler.py     # APScheduler for cron jobs
│   │   │   └── payment.py       # Razorpay integration
│   │   ├── scrapers/
│   │   │   ├── base.py          # BaseScraper class
│   │   │   ├── runner.py        # Orchestrates all scrapers
│   │   │   ├── sources/
│   │   │   │   ├── cppp.py      # Central Public Procurement Portal
│   │   │   │   ├── gem.py       # Government e-Marketplace
│   │   │   │   ├── ssc.py       # Staff Selection Commission
│   │   │   │   ├── gazette.py   # India Gazette
│   │   │   │   ├── pib.py       # Press Information Bureau
│   │   │   │   ├── raj_eproc.py # Rajasthan eProcurement
│   │   │   │   └── ...          # More sources added over time
│   │   │   └── utils/
│   │   │       ├── pdf_extractor.py
│   │   │       ├── ocr.py
│   │   │       └── dedup.py
│   │   └── models/
│   │       ├── entry.py         # Pydantic models
│   │       ├── user.py
│   │       └── notification.py
│   ├── tests/
│   │   ├── test_scrapers.py
│   │   ├── test_summarizer.py
│   │   └── test_api.py
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── railway.toml
│   └── .env.example
│
├── supabase/                    # Supabase migrations
│   ├── migrations/
│   │   ├── 001_create_entries.sql
│   │   ├── 002_create_users.sql
│   │   ├── 003_create_notifications.sql
│   │   ├── 004_create_sources.sql
│   │   ├── 005_create_bookmarks.sql
│   │   ├── 006_rls_policies.sql
│   │   └── 007_search_indexes.sql
│   └── seed.sql                 # Test data
│
├── docs/
│   ├── PRD.md                   # This file
│   ├── API.md                   # API documentation
│   └── SCRAPER_GUIDE.md         # How to add new scrapers
│
├── .github/
│   └── workflows/
│       ├── frontend.yml         # Vercel auto-deploys, but lint/test here
│       └── backend.yml          # Test + deploy to Railway
│
├── .gitignore
├── README.md
└── docker-compose.yml           # Local dev: Supabase local + backend
```

---

## ENVIRONMENT VARIABLES

### Frontend (.env.local)
```
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
NEXT_PUBLIC_API_URL=https://api.sarkarisaar.com  # Railway backend URL
NEXT_PUBLIC_RAZORPAY_KEY_ID=rzp_live_xxx
SENTRY_DSN=https://xxx@sentry.io/xxx
```

### Backend (.env)
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...              # Service role key (full access)
ANTHROPIC_API_KEY=sk-ant-xxx
RESEND_API_KEY=re_xxx
GUPSHUP_API_KEY=xxx
GUPSHUP_APP_NAME=SarkariSaar
RAZORPAY_KEY_ID=rzp_live_xxx
RAZORPAY_KEY_SECRET=xxx
UPSTASH_REDIS_URL=rediss://xxx
SENTRY_DSN=https://xxx@sentry.io/xxx
ENVIRONMENT=development                  # development | staging | production
```

---

## DATABASE SCHEMA

All tables live in Supabase PostgreSQL. Run these as Supabase migrations.

### Migration 001: entries
```sql
-- The core content table
CREATE TYPE entry_category AS ENUM (
  'yojana', 'naukri', 'tender', 'rule', 'auction', 'notice'
);

CREATE TYPE entry_urgency AS ENUM (
  'low', 'medium', 'high', 'critical'
);

CREATE TYPE entry_status AS ENUM (
  'pending', 'approved', 'rejected', 'expired'
);

CREATE TABLE entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id INTEGER REFERENCES sources(id),
  
  -- Content
  title TEXT NOT NULL,
  summary_en TEXT NOT NULL,
  summary_hi TEXT,
  original_text TEXT,            -- Raw scraped text (for debugging)
  
  -- Classification
  category entry_category NOT NULL,
  state VARCHAR(4) NOT NULL,     -- RJ, UP, MH, ALL, DL etc.
  district VARCHAR(100),
  department VARCHAR(200),
  
  -- Links
  original_url TEXT NOT NULL,
  pdf_url TEXT,                  -- If notification is a PDF
  snapshot_path TEXT,            -- Supabase Storage path to page screenshot
  
  -- Dates
  deadline DATE,
  published_date DATE,           -- When govt published it
  
  -- Structured data
  budget_amount BIGINT,          -- In paisa (₹1 = 100 paisa)
  salary_range JSONB,            -- {"min": 25000, "max": 80000}
  eligibility JSONB,             -- {"age_min": 18, "age_max": 32, "education": "graduate"}
  key_details JSONB,             -- Flexible extra data
  
  -- AI metadata
  ai_confidence FLOAT DEFAULT 0,
  urgency entry_urgency DEFAULT 'low',
  
  -- Deduplication
  content_hash VARCHAR(64) NOT NULL,  -- SHA256 of title+url+date
  
  -- Status
  status entry_status DEFAULT 'pending',
  reviewed_by UUID REFERENCES auth.users(id),
  reviewed_at TIMESTAMPTZ,
  
  -- Timestamps
  published_at TIMESTAMPTZ,      -- When we published it on our feed
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Constraints
  UNIQUE(content_hash)
);

-- Indexes for fast queries
CREATE INDEX idx_entries_category ON entries(category);
CREATE INDEX idx_entries_state ON entries(state);
CREATE INDEX idx_entries_status ON entries(status);
CREATE INDEX idx_entries_deadline ON entries(deadline) WHERE deadline IS NOT NULL;
CREATE INDEX idx_entries_published_at ON entries(published_at DESC);
CREATE INDEX idx_entries_category_state ON entries(category, state);

-- Full-text search index (Hindi + English)
ALTER TABLE entries ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(summary_en, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(department, '')), 'C')
  ) STORED;

CREATE INDEX idx_entries_search ON entries USING gin(search_vector);

-- Trigram index for fuzzy search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_entries_title_trgm ON entries USING gin(title gin_trgm_ops);
```

### Migration 002: sources
```sql
CREATE TABLE sources (
  id SERIAL PRIMARY KEY,
  name VARCHAR(200) NOT NULL,
  url TEXT NOT NULL,
  category entry_category,
  state VARCHAR(4) DEFAULT 'ALL',
  scraper_key VARCHAR(100) NOT NULL UNIQUE,  -- Maps to Python scraper class
  frequency_minutes INTEGER DEFAULT 60,
  
  -- Health tracking
  last_run_at TIMESTAMPTZ,
  last_success_at TIMESTAMPTZ,
  last_failure_at TIMESTAMPTZ,
  last_error TEXT,
  consecutive_failures INTEGER DEFAULT 0,
  total_entries_scraped INTEGER DEFAULT 0,
  
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Migration 003: subscribers
```sql
CREATE TYPE sub_channel AS ENUM ('email', 'whatsapp', 'both');
CREATE TYPE sub_frequency AS ENUM ('instant', 'daily', 'weekly');
CREATE TYPE user_plan AS ENUM ('free', 'pro', 'thekedar');

CREATE TABLE subscribers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id),  -- NULL for anonymous subscribers
  
  email VARCHAR(255),
  phone VARCHAR(15),                        -- With country code: +919876543210
  
  channel sub_channel DEFAULT 'email',
  frequency sub_frequency DEFAULT 'weekly',
  
  -- Filter preferences
  categories entry_category[] DEFAULT '{}',  -- Empty = all categories
  states VARCHAR(4)[] DEFAULT '{}',          -- Empty = all states
  keywords TEXT[] DEFAULT '{}',
  
  -- Thekedar-specific filters
  min_budget BIGINT,
  max_budget BIGINT,
  departments TEXT[] DEFAULT '{}',
  
  plan user_plan DEFAULT 'free',
  
  -- Status
  is_active BOOLEAN DEFAULT true,
  is_verified BOOLEAN DEFAULT false,
  verification_token VARCHAR(64),
  unsubscribe_token VARCHAR(64) DEFAULT encode(gen_random_bytes(32), 'hex'),
  
  -- Razorpay
  razorpay_customer_id VARCHAR(100),
  razorpay_subscription_id VARCHAR(100),
  plan_expires_at TIMESTAMPTZ,
  
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  CONSTRAINT email_or_phone CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

CREATE INDEX idx_subscribers_email ON subscribers(email) WHERE email IS NOT NULL;
CREATE INDEX idx_subscribers_phone ON subscribers(phone) WHERE phone IS NOT NULL;
CREATE INDEX idx_subscribers_active ON subscribers(is_active) WHERE is_active = true;
```

### Migration 004: bookmarks
```sql
CREATE TABLE bookmarks (
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  entry_id UUID REFERENCES entries(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (user_id, entry_id)
);
```

### Migration 005: notification_log
```sql
CREATE TYPE notification_status AS ENUM ('queued', 'sent', 'delivered', 'failed');

CREATE TABLE notification_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subscriber_id UUID REFERENCES subscribers(id),
  entry_ids UUID[] NOT NULL,                     -- Can be a digest of multiple entries
  channel VARCHAR(20) NOT NULL,
  status notification_status DEFAULT 'queued',
  
  -- Tracking
  sent_at TIMESTAMPTZ,
  delivered_at TIMESTAMPTZ,
  error TEXT,
  
  -- WhatsApp/Email specifics
  external_message_id VARCHAR(200),              -- Gupshup/Resend message ID
  
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notif_log_subscriber ON notification_log(subscriber_id);
CREATE INDEX idx_notif_log_status ON notification_log(status);
```

### Migration 006: scraper_runs (observability)
```sql
CREATE TABLE scraper_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id INTEGER REFERENCES sources(id),
  
  started_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  
  status VARCHAR(20) DEFAULT 'running',  -- running, success, failed
  entries_found INTEGER DEFAULT 0,
  entries_new INTEGER DEFAULT 0,
  entries_duplicate INTEGER DEFAULT 0,
  error TEXT,
  
  duration_seconds FLOAT
);

CREATE INDEX idx_scraper_runs_source ON scraper_runs(source_id, started_at DESC);
```

### Migration 007: RLS Policies
```sql
-- Entries: everyone can read approved entries, only admins can write
ALTER TABLE entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Public can read approved entries"
  ON entries FOR SELECT
  USING (status = 'approved');

CREATE POLICY "Service role has full access"
  ON entries FOR ALL
  USING (auth.role() = 'service_role');

-- Subscribers: users can only see their own
ALTER TABLE subscribers ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own subscriptions"
  ON subscribers FOR SELECT
  USING (user_id = auth.uid() OR user_id IS NULL);

CREATE POLICY "Users can update own subscriptions"
  ON subscribers FOR UPDATE
  USING (user_id = auth.uid());

CREATE POLICY "Anyone can insert subscription"
  ON subscribers FOR INSERT
  WITH CHECK (true);

CREATE POLICY "Service role has full access to subscribers"
  ON subscribers FOR ALL
  USING (auth.role() = 'service_role');

-- Bookmarks
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own bookmarks"
  ON bookmarks FOR ALL
  USING (user_id = auth.uid());
```

---

## MILESTONES

Each milestone is a self-contained unit. Build it, test it, confirm it works, then move on.

---

## MILESTONE 1: Project Setup & Database
**Goal:** Both repos initialized, Supabase database ready, local dev running.
**Time estimate:** 2-3 hours

### Step 1.1 — Initialize monorepo
```bash
mkdir sarkarisaar && cd sarkarisaar
git init

# Frontend
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --import-alias "@/*" --no-eslint
cd frontend
npm install @supabase/supabase-js @supabase/ssr zustand sonner date-fns
npm install -D @types/node
cd ..

# Backend
mkdir -p backend/app/routers backend/app/services backend/app/scrapers/sources backend/app/scrapers/utils backend/app/models backend/tests
cd backend
touch app/__init__.py app/main.py app/config.py app/database.py
touch app/routers/__init__.py app/services/__init__.py app/scrapers/__init__.py
touch app/scrapers/sources/__init__.py app/scrapers/utils/__init__.py
touch app/models/__init__.py
cd ..

# Supabase migrations
mkdir -p supabase/migrations
```

### Step 1.2 — Backend requirements.txt
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
pydantic==2.9.0
pydantic-settings==2.5.0
supabase==2.9.0
anthropic==0.39.0
httpx==0.27.0
beautifulsoup4==4.12.3
lxml==5.3.0
selectolax==0.3.21
PyMuPDF==1.24.0
apscheduler==3.10.4
python-multipart==0.0.12
resend==2.0.0
razorpay==1.4.2
redis==5.0.0
sentry-sdk[fastapi]==2.14.0
python-dotenv==1.0.1
pytest==8.3.0
pytest-asyncio==0.24.0
```

### Step 1.3 — Backend config.py
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_key: str
    
    # AI
    anthropic_api_key: str
    
    # Notifications
    resend_api_key: str = ""
    gupshup_api_key: str = ""
    gupshup_app_name: str = "SarkariSaar"
    
    # Payments
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    
    # Cache
    upstash_redis_url: str = ""
    
    # App
    environment: str = "development"
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Step 1.4 — Backend main.py (minimal)
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

app = FastAPI(
    title="SarkariSaar API",
    version="0.1.0",
    docs_url="/docs" if settings.environment != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.frontend_url,
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
```

### Step 1.5 — Run Supabase migrations
Create all migration files (001 through 007) from the DATABASE SCHEMA section above. Apply them via Supabase dashboard SQL editor or Supabase CLI.

### Step 1.6 — Seed test data
Create `supabase/seed.sql` with 5 test sources and 15-20 test entries across different categories and states. Use realistic data matching real government portals.

### Acceptance Tests — Milestone 1
```
[ ] `cd frontend && npm run dev` → Next.js runs on localhost:3000
[ ] `cd backend && uvicorn app.main:app --reload` → FastAPI runs on localhost:8000
[ ] GET localhost:8000/health returns {"status": "ok"}
[ ] GET localhost:8000/docs shows Swagger UI
[ ] Supabase dashboard shows all 7 tables created
[ ] Seed data visible in Supabase table editor
[ ] Frontend can import supabase client without errors
```

---

## MILESTONE 2: Scraping Pipeline (First 3 Sources)
**Goal:** Working scraper that fetches real data from 3 government websites, extracts content, and stores raw entries in the database.
**Time estimate:** 6-8 hours

### Step 2.1 — Base Scraper Class

Create `backend/app/scrapers/base.py`:

```python
"""
Base scraper that all source-specific scrapers inherit from.

Every scraper must implement:
  - source_key: str (matches sources.scraper_key in DB)
  - scrape() -> list[RawEntry]

The base class handles:
  - Deduplication (content_hash check)
  - Database insertion
  - Error logging
  - Run tracking in scraper_runs table
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import hashlib
import traceback

@dataclass
class RawEntry:
    """What a scraper outputs before AI processing."""
    title: str
    raw_text: str                    # Full extracted text
    original_url: str
    category: str                    # Best guess; AI will verify
    state: str                       # State code: RJ, UP, ALL, etc.
    department: str
    published_date: Optional[str]    # ISO format or None
    deadline: Optional[str]          # ISO format or None
    pdf_url: Optional[str] = None
    budget_amount: Optional[int] = None  # In paisa
    extra: Optional[dict] = None     # Source-specific structured data

class BaseScraper(ABC):
    @property
    @abstractmethod
    def source_key(self) -> str:
        """Must match sources.scraper_key in database."""
        pass
    
    @abstractmethod
    async def scrape(self) -> list[RawEntry]:
        """Fetch and parse the source. Return list of RawEntry."""
        pass
    
    def content_hash(self, entry: RawEntry) -> str:
        """Generate dedup hash from title + URL + date."""
        raw = f"{entry.title}|{entry.original_url}|{entry.published_date or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()
```

### Step 2.2 — Scraper Runner

Create `backend/app/scrapers/runner.py` that:
1. Loads all registered scrapers
2. For each scraper: creates a `scraper_runs` record, calls `scrape()`, deduplicates against existing `content_hash` values, inserts new raw entries with `status='pending'`, updates the run record with counts
3. Handles errors gracefully — one scraper failing must NOT stop others
4. Logs everything

### Step 2.3 — First Scraper: PIB (Press Information Bureau)

Create `backend/app/scrapers/sources/pib.py`:
- Source: `https://pib.gov.in/allRel.aspx`
- PIB has relatively clean HTML and publishes in both Hindi and English
- Scrape the latest press releases
- Extract: title, full text, date, ministry/department
- Category: mostly 'notice' or 'yojana'
- State: 'ALL' (central government)

This is the easiest source to start with because PIB has structured, well-formatted content.

### Step 2.4 — Second Scraper: SSC (Staff Selection Commission)

Create `backend/app/scrapers/sources/ssc.py`:
- Source: `https://ssc.gov.in` → Latest News / Notices section
- Extract: notification title, exam name, dates, vacancies count, PDF download link
- Category: 'naukri'
- State: 'ALL'
- Parse the notification list table on the homepage

### Step 2.5 — Third Scraper: Rajasthan eProcurement

Create `backend/app/scrapers/sources/raj_eproc.py`:
- Source: `https://eproc.rajasthan.gov.in`
- This may require Playwright (JavaScript-rendered content)
- Extract: tender title, department, estimated cost, EMD, deadline, tender ID
- Category: 'tender'
- State: 'RJ'
- Budget amount in paisa

### Step 2.6 — API Endpoint to Trigger Scraping

Add `POST /admin/scrape` endpoint (protected, only callable with service key) that triggers the scraper runner. Also add `GET /admin/scraper-status` to check last run results.

### Step 2.7 — Scheduled Scraping

Set up APScheduler in FastAPI's lifespan to run scrapers automatically:
- PIB: every 60 minutes
- SSC: every 120 minutes
- Raj eProc: every 60 minutes

### Acceptance Tests — Milestone 2
```
[ ] POST /admin/scrape triggers all 3 scrapers
[ ] PIB scraper returns 5+ real entries from pib.gov.in
[ ] SSC scraper returns 3+ real entries from ssc.gov.in
[ ] Raj eProc scraper returns 3+ real entries
[ ] Entries are inserted into Supabase 'entries' table with status='pending'
[ ] Duplicate entries (same content_hash) are skipped on re-run
[ ] scraper_runs table shows run history with counts
[ ] If one scraper fails, others still complete
[ ] GET /admin/scraper-status shows last run time and counts per source
[ ] Scheduler auto-runs scrapers on configured intervals
```

---

## MILESTONE 3: AI Summarization Layer
**Goal:** Raw scraped entries are processed by Claude API to generate clean summaries, categorization, deadline extraction, and urgency scoring.
**Time estimate:** 4-5 hours

### Step 3.1 — Summarizer Service

Create `backend/app/services/summarizer.py`:

Use this system prompt for Claude:

```
You are a government notification summarizer for Indian citizens.
Your job is to make complex government notifications understandable
to ordinary people — a farmer, a student, a small contractor.

Given the raw text of a government notification, extract and return
a JSON object with these fields:

{
  "title": "Clear, plain-language title (max 80 characters). No jargon.",
  "summary_en": "2-3 sentence summary in simple English. What is this about? Who is it for? What should they do? Include the most important number (salary, budget, subsidy amount) if applicable.",
  "summary_hi": "Same summary in simple Hindi (Devanagari script). Use everyday Hindi, not Shudh Hindi.",
  "category": "One of: yojana | naukri | tender | rule | auction | notice",
  "urgency": "One of: low | medium | high | critical. Critical = deadline within 7 days. High = deadline within 30 days or major policy change.",
  "deadline": "ISO date (YYYY-MM-DD) or null. Extract from phrases like 'last date', 'अंतिम तिथि', 'closing date', 'bid submission deadline'.",
  "department": "Issuing department or ministry name",
  "eligibility": "Who is eligible? Brief text or null",
  "budget_or_salary": "Key financial figure as integer (in INR, not paisa) or null",
  "key_details": {
    "application_link": "URL if mentioned, or null",
    "helpline": "Phone number if mentioned, or null",
    "vacancies": "Number if job posting, or null",
    "emd_amount": "EMD in INR if tender, or null"
  }
}

IMPORTANT RULES:
- Respond with ONLY the JSON object. No markdown, no explanation.
- If you're unsure about a field, set it to null rather than guessing.
- The summary must be understandable by someone with a 10th-grade education.
- Always mention the deadline prominently in the summary if one exists.
- For tenders: always mention estimated cost and EMD if available.
- For jobs: always mention number of vacancies and eligibility.
- For yojanas: always mention who is eligible and how to apply.
```

### Step 3.2 — Processing Pipeline

Create a function `process_pending_entries()` that:
1. Fetches entries with `status='pending'` from database (batch of 10)
2. For each entry, sends `raw_text` to Claude API
3. Parses the JSON response
4. Updates the entry with: summary_en, summary_hi, category (AI-verified), urgency, deadline, department, key_details, ai_confidence
5. Sets `status='approved'` if confidence > 0.90 AND source is trusted
6. Sets `status='pending'` (stays pending for human review) if confidence <= 0.90
7. Handles API errors gracefully — retry with exponential backoff, max 3 attempts

### Step 3.3 — Add to Scheduler

Add a job that runs `process_pending_entries()` every 5 minutes. This processes pending entries in small batches to avoid hitting Claude API rate limits.

### Step 3.4 — Cost Control

- Track Claude API token usage per entry
- Log estimated cost per run
- Set a daily spending cap (configurable via env var, default ₹500/day)
- Alert if daily spend exceeds 80% of cap

### Step 3.5 — API Endpoint for Manual Processing

Add `POST /admin/process` to manually trigger AI processing of pending entries. Add `GET /admin/pending-count` to check how many entries await processing.

### Acceptance Tests — Milestone 3
```
[ ] process_pending_entries() picks up raw entries from Milestone 2
[ ] Claude API returns valid JSON with all required fields
[ ] summary_en is 2-3 sentences in simple language (not bureaucratic)
[ ] summary_hi is proper Hindi in Devanagari script
[ ] category is correctly identified (verify against 5 known entries)
[ ] deadline is extracted as valid ISO date where applicable
[ ] Entries with confidence > 0.90 are auto-approved
[ ] Low-confidence entries stay as 'pending' for review
[ ] API errors are retried (test by temporarily using wrong API key)
[ ] Token usage is logged per entry
[ ] POST /admin/process works and processes a batch
```

---

## MILESTONE 4: Feed API
**Goal:** RESTful API that serves processed entries with filtering, pagination, and search.
**Time estimate:** 3-4 hours

### Step 4.1 — GET /api/entries

Create `backend/app/routers/entries.py`:

```
GET /api/entries
  Query params:
    - category: string (optional, comma-separated: "tender,naukri")
    - state: string (optional, comma-separated: "RJ,UP")
    - search: string (optional, full-text search query)
    - urgency: string (optional: "high,critical")
    - deadline_before: date (optional, ISO format)
    - sort: string (default: "published_at", options: "deadline", "urgency")
    - page: int (default: 1)
    - limit: int (default: 20, max: 50)
  
  Response:
    {
      "entries": [...],
      "total": 156,
      "page": 1,
      "limit": 20,
      "has_more": true
    }
  
  Only returns entries with status='approved'.
  Sorted by published_at DESC by default.
```

### Step 4.2 — GET /api/entries/{id}

Returns a single entry with full details including key_details JSONB.

### Step 4.3 — GET /api/stats

Returns aggregate stats for the landing page:
```json
{
  "total_entries": 2847,
  "entries_today": 43,
  "states_covered": 36,
  "sources_active": 52,
  "categories": {
    "yojana": 412,
    "naukri": 891,
    "tender": 1203,
    "rule": 189,
    "auction": 98,
    "notice": 54
  }
}
```

### Step 4.4 — Search Implementation

Use PostgreSQL full-text search with the `search_vector` column:
```sql
SELECT * FROM entries
WHERE status = 'approved'
  AND search_vector @@ plainto_tsquery('english', :query)
ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query)) DESC
LIMIT :limit OFFSET :offset;
```

Also add fuzzy matching fallback using pg_trgm for when exact text search returns no results:
```sql
SELECT * FROM entries
WHERE status = 'approved'
  AND title % :query  -- trigram similarity
ORDER BY similarity(title, :query) DESC
LIMIT :limit;
```

### Step 4.5 — Caching with Upstash Redis

Cache the feed response for 5 minutes per unique filter combination. Cache key format: `feed:{category}:{state}:{page}:{sort}`. Invalidate relevant caches when new entries are approved.

### Acceptance Tests — Milestone 4
```
[ ] GET /api/entries returns paginated approved entries
[ ] category filter works: ?category=tender returns only tenders
[ ] state filter works: ?state=RJ returns only Rajasthan entries
[ ] Combined filters work: ?category=tender&state=RJ
[ ] search works: ?search=highway returns relevant results
[ ] Pagination works: page=2 returns different results than page=1
[ ] Sort by deadline works: nearest deadlines first
[ ] GET /api/entries/{id} returns full entry details
[ ] GET /api/stats returns correct aggregate counts
[ ] Invalid filters return empty results, not errors
[ ] Response time < 200ms for unfiltered feed (with cache)
[ ] Response time < 500ms for search queries
```

---

## MILESTONE 5: Frontend Feed UI
**Goal:** Working web feed page with category filters, state filter, search, and feed cards showing AI summaries.
**Time estimate:** 6-8 hours

### Step 5.1 — Supabase Client Setup

Create `frontend/src/lib/supabase/client.ts` (browser) and `frontend/src/lib/supabase/server.ts` (RSC). Set up the Supabase JS client with the anon key.

### Step 5.2 — API Client

Create `frontend/src/lib/api.ts`:
- Wrapper around `fetch()` that hits the FastAPI backend
- Handles errors, loading states
- Types all responses

### Step 5.3 — Types

Create `frontend/src/types/index.ts` with TypeScript interfaces matching the API response shapes: `Entry`, `EntriesResponse`, `StatsResponse`, etc.

### Step 5.4 — Constants

Create `frontend/src/lib/constants.ts`:
```typescript
export const CATEGORIES = [
  { id: "all", label: "All", icon: "◉", color: "#FF6B35" },
  { id: "yojana", label: "Yojana", icon: "🏛", color: "#8B5CF6" },
  { id: "naukri", label: "Naukri", icon: "💼", color: "#10B981" },
  { id: "tender", label: "Tender / Theka", icon: "📋", color: "#F59E0B" },
  { id: "rule", label: "Rule Change", icon: "⚖️", color: "#EF4444" },
  { id: "auction", label: "Auction", icon: "🔨", color: "#06B6D4" },
  { id: "notice", label: "Notice / Circular", icon: "📢", color: "#EC4899" },
] as const;

export const STATES = [
  { code: "ALL", label: "All India" },
  { code: "RJ", label: "Rajasthan" },
  { code: "UP", label: "Uttar Pradesh" },
  // ... all 28 states + 8 UTs
] as const;
```

### Step 5.5 — Design System

Implement the dark mode design from the existing prototype (sarkarisaar.jsx):
- Background: #0A0A0F
- Surface: #111122
- Card: #111122 with #1a1a30 border
- Primary accent: #FF6B35 (saffron)
- Secondary: #10B981 (green)
- Text primary: #E8E6E3
- Text muted: #8B8A94

Use Tailwind with custom theme colors configured in `tailwind.config.ts`.

### Step 5.6 — Components

Build these components using the design from the existing sarkarisaar.jsx prototype. Adapt the inline styles to Tailwind classes:

1. **Navbar** — Logo, nav links (Feed, Premium, Subscribe), Get Started button
2. **CategoryFilter** — Horizontal scrollable pills for each category
3. **StateFilter** — Dropdown select for states
4. **SearchBar** — Search input with icon and button
5. **FeedCard** — Category tag, state tag, NEW badge, deadline badge, title, summary, source, date, "View Original →" link
6. **DeadlineBadge** — Color-coded: red (≤7 days), yellow (≤30 days), green (>30 days)
7. **FeedSkeleton** — Loading skeleton matching FeedCard shape
8. **Footer** — Logo, disclaimer, links

### Step 5.7 — Feed Page

Build `frontend/src/app/feed/page.tsx`:
- Server component that fetches initial data
- Client components for interactive filters
- URL-based state: `/feed?category=tender&state=RJ&search=highway`
- Infinite scroll or "Load More" button for pagination
- Loading skeleton while fetching
- Empty state when no results match filters

### Step 5.8 — Landing Page

Build `frontend/src/app/page.tsx`:
- Hero section with search bar
- Stats bar (from /api/stats)
- Preview of latest 5 entries
- "How it works" section
- Contractor/Thekedar section
- CTA to subscribe

### Step 5.9 — Entry Detail Page

Build `frontend/src/app/entry/[id]/page.tsx`:
- Full entry display with all details
- "View Original on [source]" prominent button
- Related entries (same category + state)
- Share button (copy link, WhatsApp share)
- SEO: dynamic meta tags from entry title + summary for social sharing

### Acceptance Tests — Milestone 5
```
[ ] Landing page loads with hero, stats, and preview entries
[ ] /feed page shows all approved entries from API
[ ] Category filter pills work — clicking "Tender" shows only tenders
[ ] State dropdown works — selecting "Rajasthan" filters to RJ entries
[ ] Search works — typing "highway" filters relevant results
[ ] Combined filters work: Tender + Rajasthan + search
[ ] Feed cards show: category tag, state, title, summary, deadline badge, source, "View Original"
[ ] "View Original" link opens correct government URL in new tab
[ ] Deadline badges are color-coded correctly (red/yellow/green)
[ ] Loading skeleton shows while data is fetching
[ ] Empty state shows when no results match
[ ] /entry/[id] page shows full entry details
[ ] Page is responsive: works on 375px mobile viewport
[ ] Dark mode looks correct — no white flashes, no broken colors
[ ] Page loads in < 2 seconds (check with Lighthouse)
```

---

## MILESTONE 6: Admin Review Dashboard
**Goal:** Protected admin page where team members can review, approve, edit, or reject AI-processed entries.
**Time estimate:** 4-5 hours

### Step 6.1 — Admin Authentication

Use Supabase Auth. Create an `admin_users` table or use Supabase user metadata to flag admin accounts. Protect admin routes with middleware that checks for the admin flag.

### Step 6.2 — Review Queue Page

Build `frontend/src/app/admin/page.tsx`:
- List of entries with `status='pending'`, newest first
- Each entry shows: title, AI-generated summary (en + hi), category, state, urgency, confidence score, original URL
- Action buttons: Approve, Edit, Reject
- Click "Edit" to modify the summary, category, or deadline before approving
- Bulk approve option for high-confidence entries (>0.95)

### Step 6.3 — Admin API Endpoints

```
PATCH /api/admin/entries/{id}/approve
PATCH /api/admin/entries/{id}/reject
PATCH /api/admin/entries/{id}          # Edit fields
GET   /api/admin/entries/pending       # List pending entries
GET   /api/admin/scraper-dashboard     # Source health overview
```

### Step 6.4 — Scraper Health Dashboard

Show on the admin page:
- Table of all sources with: name, last run time, last success, consecutive failures, total entries
- Color-coded status: green (healthy), yellow (1-2 failures), red (3+ failures)
- Button to manually trigger a specific scraper

### Acceptance Tests — Milestone 6
```
[ ] Non-admin users cannot access /admin (redirected to login)
[ ] Admin users see pending entries queue
[ ] Approving an entry sets status='approved' and it appears in public feed
[ ] Rejecting an entry sets status='rejected' and it never appears publicly
[ ] Editing summary/category/deadline updates the entry before approval
[ ] Bulk approve works for 5+ entries at once
[ ] Scraper health dashboard shows real status of all sources
[ ] Manual scraper trigger works from admin dashboard
```

---

## MILESTONE 7: Email Subscription
**Goal:** Users can subscribe with email and receive weekly/daily digests.
**Time estimate:** 4-5 hours

### Step 7.1 — Subscribe API

```
POST /api/subscribe
  Body: {
    "email": "user@example.com",
    "phone": "+919876543210",     // optional
    "channel": "email",
    "frequency": "weekly",
    "categories": ["tender", "naukri"],
    "states": ["RJ", "ALL"]
  }
  
  Response: { "success": true, "message": "Verification email sent" }
```

Send a verification email via Resend with a token link. Only activate subscription after email is verified.

### Step 7.2 — Unsubscribe

```
GET /api/unsubscribe?token={unsubscribe_token}
```

Every email includes an unsubscribe link at the bottom. One-click unsubscribe, no login required.

### Step 7.3 — Digest Generator

Create `backend/app/services/notifier.py`:

`generate_digest(subscriber)` function that:
1. Fetches entries published since last digest was sent to this subscriber
2. Filters by subscriber's category and state preferences
3. Groups entries by category
4. Returns a structured digest object

### Step 7.4 — Email Template

Build an HTML email template (inline CSS for email client compatibility):
- SarkariSaar header with logo
- "Your [Daily/Weekly] Government Update" heading
- Entries grouped by category
- Each entry: title, 1-line summary, deadline badge, "Read More →" link
- Stats footer: "X new updates this week across Y states"
- Unsubscribe link

### Step 7.5 — Digest Scheduler

Schedule digest jobs via APScheduler:
- Daily digests: run at 7:00 AM IST
- Weekly digests: run at 7:00 AM IST every Monday

Batch email sending: process 50 subscribers at a time with 1-second delay between batches to respect Resend rate limits.

### Step 7.6 — Subscribe Form on Frontend

Build `frontend/src/components/subscribe/SubscribeForm.tsx`:
- Email input, optional WhatsApp number
- Channel selector (Email / WhatsApp / Both)
- Frequency selector (Daily / Weekly)
- Category multi-select checkboxes
- State multi-select or dropdown
- Submit button with loading state
- Success/error toast notifications

### Acceptance Tests — Milestone 7
```
[ ] POST /api/subscribe creates a subscriber record with is_verified=false
[ ] Verification email is sent via Resend with correct token link
[ ] Clicking verification link sets is_verified=true
[ ] Unsubscribe link deactivates subscription (is_active=false)
[ ] generate_digest() returns correct entries matching subscriber preferences
[ ] Daily digest email renders correctly in Gmail/Outlook (check with Litmus or manual)
[ ] Weekly digest email includes all entries from the past 7 days
[ ] Scheduler triggers at correct times (test with short interval first)
[ ] Subscribe form on frontend works end-to-end
[ ] Duplicate email subscription is handled gracefully (update existing, not duplicate)
[ ] Rate limiting: max 3 subscribe attempts per email per hour
```

---

## MILESTONE 8: User Authentication
**Goal:** Users can sign up/login to save preferences, bookmark entries, and manage subscriptions.
**Time estimate:** 4-5 hours

### Step 8.1 — Supabase Auth Setup

Configure in Supabase dashboard:
- Enable Email/Password provider
- Enable Phone (OTP) provider — critical for India, many users prefer phone login
- Enable Google OAuth provider
- Set redirect URLs for Vercel deployment
- Customize email templates (verification, password reset)

### Step 8.2 — Auth Pages

Build:
- `frontend/src/app/auth/login/page.tsx` — Email/password, phone OTP, Google sign-in
- `frontend/src/app/auth/callback/page.tsx` — OAuth callback handler

### Step 8.3 — Auth Middleware

Create `frontend/src/middleware.ts`:
- Refresh Supabase session on every request
- Protect `/dashboard` and `/admin` routes
- Redirect to login if unauthenticated

### Step 8.4 — User Dashboard

Build `frontend/src/app/dashboard/page.tsx`:
- Bookmarked entries list
- Subscription preferences (edit categories, states, frequency)
- Account settings (email, phone, language preference)
- Plan status (Free / Pro / Thekedar) with upgrade CTA

### Step 8.5 — Bookmark Feature

- Add bookmark button (heart/flag icon) to every FeedCard
- `POST /api/bookmarks/{entry_id}` — toggle bookmark
- `GET /api/bookmarks` — list user's bookmarks
- Requires authentication; show login prompt if not logged in

### Acceptance Tests — Milestone 8
```
[ ] User can sign up with email/password
[ ] User can sign up with phone OTP (+91 number)
[ ] User can sign in with Google
[ ] Session persists across page refreshes
[ ] /dashboard is protected — redirects to login if not authenticated
[ ] /admin is protected — only admin-flagged users can access
[ ] User can bookmark an entry from the feed
[ ] Bookmarked entries appear in /dashboard
[ ] User can edit subscription preferences from dashboard
[ ] Logout works and clears session
```

---

## MILESTONE 9: WhatsApp Notifications
**Goal:** Subscribers receive government updates on WhatsApp via Gupshup Business API.
**Time estimate:** 5-6 hours

### Step 9.1 — Gupshup Setup

1. Create Gupshup account and register for WhatsApp Business API
2. Get a WhatsApp Business number verified
3. Create message templates (Gupshup requires pre-approved templates):

**Template 1: Daily Digest**
```
🇮🇳 SarkariSaar Daily Update

📋 {{1}} new updates today

{{2}}

👉 Full feed: sarkarisaar.com/feed
Reply STOP to unsubscribe
```

**Template 2: Instant Tender Alert (Premium)**
```
🔔 New Tender Alert!

📋 {{1}}
💰 Est. Cost: ₹{{2}}
📍 {{3}}
⏰ Deadline: {{4}}

👉 Details: {{5}}
Reply 1 for more info
Reply STOP to unsubscribe
```

**Template 3: Deadline Reminder**
```
⏰ Deadline Reminder!

"{{1}}" deadline is in {{2}} days.

📅 Last date: {{3}}
👉 {{4}}

Reply STOP to unsubscribe
```

### Step 9.2 — WhatsApp Service

Create `backend/app/services/whatsapp.py`:
- `send_template_message(phone, template_name, params)` — sends via Gupshup API
- `send_digest(subscriber)` — generates digest and sends as WhatsApp template
- `send_instant_alert(subscriber, entry)` — for premium instant alerts
- Handle Gupshup webhook for delivery status and incoming replies (STOP = unsubscribe)

### Step 9.3 — Incoming Message Handler

Create webhook endpoint `POST /api/webhooks/gupshup`:
- Handle "STOP" → deactivate subscription
- Handle "1" (in response to tender alert) → send full details
- Handle other messages → send auto-reply with menu options

### Step 9.4 — WhatsApp Digest Scheduler

- Daily WhatsApp digests: 7:30 AM IST (30 min after email so they don't compete)
- Instant alerts (Thekedar plan only): send within 5 minutes of entry approval
- Respect WhatsApp Business API rate limits (1,000 messages/day on basic tier)

### Step 9.5 — Phone Verification for WhatsApp

Before sending WhatsApp messages, verify the phone number by sending an OTP via WhatsApp itself. Store verification status in subscribers table.

### Acceptance Tests — Milestone 9
```
[ ] Gupshup API connection works (test with a single message to your own number)
[ ] Daily digest template sends correctly with formatted content
[ ] Instant tender alert sends correctly
[ ] Deadline reminder sends correctly
[ ] "STOP" reply unsubscribes the user
[ ] "1" reply sends full tender details
[ ] Phone verification OTP flow works
[ ] Rate limiting prevents exceeding Gupshup daily limits
[ ] Delivery status webhook updates notification_log
[ ] Failed messages are retried once after 5 minutes
```

---

## MILESTONE 10: Payments & Premium Plans
**Goal:** Users can upgrade to Pro (₹199/mo) or Thekedar (₹499/mo) plans via Razorpay.
**Time estimate:** 5-6 hours

### Step 10.1 — Razorpay Setup

1. Create Razorpay account, complete KYC
2. Create subscription plans in Razorpay dashboard:
   - Plan: "SarkariSaar Pro" — ₹199/month, ₹1999/year
   - Plan: "SarkariSaar Thekedar" — ₹499/month, ₹4999/year
3. Set up webhook URL for payment events

### Step 10.2 — Payment API

```
POST /api/payments/create-subscription
  Body: { "plan": "pro" | "thekedar", "period": "monthly" | "yearly" }
  Response: { "subscription_id": "sub_xxx", "short_url": "https://rzp.io/xxx" }

POST /api/webhooks/razorpay
  Handles: subscription.activated, subscription.charged, subscription.cancelled,
           subscription.halted, payment.failed
```

### Step 10.3 — Plan Enforcement

- Free users: web feed + weekly email digest
- Pro users: daily email + WhatsApp digest, custom filters, bookmarks, deadline reminders
- Thekedar users: everything in Pro + instant WhatsApp alerts + advanced tender filters + tender comparison

Check plan status on every API request that's plan-gated. Cache plan status in Redis for 5 minutes.

### Step 10.4 — Pricing Page

Build `frontend/src/app/pricing/page.tsx`:
- Three-column pricing cards (Free / Pro / Thekedar)
- Feature comparison table
- "Start 7-Day Free Trial" buttons for Pro and Thekedar
- Monthly/Yearly toggle (show yearly savings)
- FAQ section

### Step 10.5 — Razorpay Checkout Integration

- Use Razorpay's hosted checkout page (simplest, no PCI compliance needed)
- On successful payment, redirect to `/dashboard?payment=success`
- Update subscriber's plan and plan_expires_at in database

### Acceptance Tests — Milestone 10
```
[ ] Razorpay checkout opens with correct plan amount
[ ] Test payment in Razorpay test mode completes successfully
[ ] Webhook correctly updates subscriber plan to 'pro' on payment success
[ ] Pro features are unlocked after payment (daily digest, custom filters)
[ ] Thekedar features are unlocked (instant alerts, tender filters)
[ ] Free users cannot access Pro features (returns 403)
[ ] Subscription cancellation via Razorpay dashboard triggers webhook and downgrades plan
[ ] Failed payment triggers retry and user notification
[ ] Plan expiry automatically downgrades to free tier
[ ] Pricing page renders correctly on mobile
```

---

## MILESTONE 11: Expand Scrapers (30 Sources)
**Goal:** Add scrapers for the top 30 government sources from the priority list.
**Time estimate:** 15-20 hours (2-3 days)

### Approach

Add scrapers in batches of 5-7, testing each batch before moving on:

**Batch 1 (Central Tenders):** CPPP (eprocure.gov.in), GeM (gem.gov.in), NHAI
**Batch 2 (Central Jobs):** UPSC, Railway Recruitment, IBPS
**Batch 3 (Central Schemes/Rules):** MyScheme, CBIC, PIB (already done), Gazette
**Batch 4 (State Tenders):** UP eProcurement, Maharashtra, MP, Gujarat, Bihar
**Batch 5 (State Jobs):** UPPSC, MPSC, RSMSSB (already done), KPSC, TNPSC
**Batch 6 (More States):** Karnataka, Haryana, Punjab, Delhi, Tamil Nadu eProcurement

For each source, create a scraper file in `backend/app/scrapers/sources/` following the BaseScraper pattern. Add the source to the `sources` database table.

### Common Challenges & Solutions

- **JavaScript-rendered pages:** Use Playwright with headless Chromium. Railway supports running Playwright in Docker.
- **PDF-only notifications:** Use PyMuPDF to extract text. For scanned PDFs, use Google Cloud Vision OCR API.
- **CAPTCHA-protected pages:** Skip these sources initially. Consider using anti-CAPTCHA services later if the source is high-value.
- **Rate limiting by govt servers:** Respect robots.txt. Add random delays (2-5 seconds) between requests. Use at most 1 request per 3 seconds per domain.
- **Structure changes:** Store raw HTML snapshots. Alert admin when a scraper returns 0 entries for 3 consecutive runs.

### Acceptance Tests — Milestone 11
```
[ ] All 30 sources have working scrapers
[ ] Each scraper returns real data from its source
[ ] sources table has 30 active entries
[ ] Scraper health dashboard shows all 30 sources
[ ] No single scraper failure affects others
[ ] Daily entry count is 50-100+ across all sources
[ ] Entries cover all 6 categories
[ ] Entries cover at least 10 different states
```

---

## MILESTONE 12: Production Deployment
**Goal:** Deploy everything to production with monitoring, error tracking, and CI/CD.
**Time estimate:** 4-6 hours

### Step 12.1 — Frontend Deployment (Vercel)

1. Connect GitHub repo to Vercel
2. Set root directory to `frontend/`
3. Add all environment variables
4. Configure custom domain: sarkarisaar.com
5. Enable Vercel Analytics
6. Configure ISR: feed pages revalidate every 300 seconds

### Step 12.2 — Backend Deployment (Railway)

1. Create Railway project
2. Connect GitHub repo, set root directory to `backend/`
3. Use Dockerfile for deployment:
```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system deps for Playwright, PyMuPDF, lxml
RUN apt-get update && apt-get install -y \
    build-essential libxml2-dev libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
4. Add all environment variables
5. Configure custom domain: api.sarkarisaar.com
6. Set health check: `/health`

### Step 12.3 — Supabase Production

1. Create a new Supabase project for production (separate from development)
2. Run all migrations
3. Enable Point-in-Time Recovery
4. Configure database connection pooling (Supavisor)
5. Set up daily backups

### Step 12.4 — Monitoring & Alerting

1. **Sentry:** Install SDK in both frontend and backend. Configure error alerts to Slack/email.
2. **Uptime monitoring:** Set up UptimeRobot or Better Uptime for:
   - https://sarkarisaar.com (frontend)
   - https://api.sarkarisaar.com/health (backend)
   - Check every 5 minutes, alert on 2 consecutive failures
3. **Scraper monitoring:** Daily Slack alert summarizing: sources checked, entries found, failures.

### Step 12.5 — CI/CD

GitHub Actions workflows:

**Frontend (.github/workflows/frontend.yml):**
- On push to main: run `npm run lint`, `npm run build`
- Vercel auto-deploys from main branch

**Backend (.github/workflows/backend.yml):**
- On push to main: run `pytest`, build Docker image
- Railway auto-deploys from main branch

### Step 12.6 — Security Checklist

```
[ ] All API keys in environment variables, never in code
[ ] CORS restricted to sarkarisaar.com and api.sarkarisaar.com
[ ] Rate limiting on all public API endpoints
[ ] Supabase RLS policies active on all tables
[ ] Admin endpoints require authentication + admin role check
[ ] Razorpay webhook signature verification enabled
[ ] Gupshup webhook IP whitelist configured
[ ] HTTPS enforced on all endpoints
[ ] SQL injection impossible (using parameterized queries via Supabase client)
[ ] XSS prevented (React auto-escapes, no dangerouslySetInnerHTML)
```

### Acceptance Tests — Milestone 12
```
[ ] sarkarisaar.com loads in production
[ ] api.sarkarisaar.com/health returns 200
[ ] Feed shows real scraped data in production
[ ] Subscription flow works end-to-end in production
[ ] Razorpay payment works in live mode
[ ] WhatsApp messages deliver in production
[ ] Sentry captures errors from both frontend and backend
[ ] Uptime monitor is active and alerting
[ ] Lighthouse score > 85 for performance on mobile
[ ] All environment variables are set and not exposed
```

---

## MILESTONE 13: SEO & Growth (Post-Launch)
**Goal:** Organic traffic acquisition — target "sarkari yojana", "government tender", "ssc notification" keywords.
**Time estimate:** Ongoing

### SEO Optimizations

1. **Dynamic meta tags** on every entry page: `<title>{entry.title} | SarkariSaar</title>`, `<meta name="description" content="{entry.summary_en}">`
2. **Sitemap.xml** auto-generated from all approved entries, submitted to Google Search Console
3. **Structured data** (JSON-LD) on entry pages: JobPosting schema for naukri, GovernmentService schema for yojanas
4. **Hindi content indexing** — summary_hi content improves ranking for Hindi searches
5. **State-specific landing pages:** `/rajasthan`, `/uttar-pradesh` with filtered feeds
6. **Category landing pages:** `/tenders`, `/yojanas`, `/jobs` with filtered feeds

### Growth Channels

1. **WhatsApp forwards** — include "Forward to someone who needs this" CTA in digests
2. **Telegram channel** — auto-post entries for organic reach
3. **YouTube Shorts / Instagram Reels** — AI-generated video summaries of top daily updates (Phase 2)
4. **Contractor community partnerships** — partner with contractor associations for distribution

---

## COST SUMMARY (Monthly at Scale)

| Service | Free Tier | At 10K Users | At 100K Users |
|---------|-----------|--------------|---------------|
| Vercel | Free (hobby) | $20 (Pro) | $20 (Pro) |
| Supabase | Free (500MB) | $25 (Pro) | $75 (Team) |
| Railway | $5 (hobby) | $20 | $50 |
| Upstash Redis | Free (10K/day) | $10 | $30 |
| Claude API | ~₹300 | ~₹8,000 | ~₹25,000 |
| Resend | Free (3K/mo) | $20 | $80 |
| Gupshup WhatsApp | ₹0 | ₹10,000 | ₹50,000 |
| Google Vision OCR | Free (1K/mo) | ₹3,000 | ₹8,000 |
| Sentry | Free | Free | $26 |
| Domain + DNS | ₹800/yr | ₹800/yr | ₹800/yr |
| **Total** | **~₹1,500/mo** | **~₹25,000/mo** | **~₹1,00,000/mo** |

---

## QUICK REFERENCE: Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Monorepo vs polyrepo | Monorepo | Simpler for small team, shared types |
| ORM vs query builder | Supabase client (PostgREST) | No ORM needed, Supabase SDK handles queries |
| Server components vs client | Default to server, client for interactivity | Better SEO, faster page loads |
| Auth solution | Supabase Auth | Already in the stack, phone OTP built-in |
| Image/file storage | Supabase Storage | Already in the stack, free 1GB |
| Background jobs | APScheduler (in-process) | Simpler than Celery for early stage. Migrate to Celery + Redis when running multiple workers |
| Full-text search | PostgreSQL tsvector + pg_trgm | Good enough until 1M+ entries; migrate to Meilisearch then |
| WhatsApp API | Gupshup | Indian company, INR billing, good Hindi support |
| Email | Resend | Simple API, good deliverability, generous free tier |
| Payments | Razorpay | Indian standard, UPI support, subscription billing |

---

## HOW TO USE THIS DOCUMENT WITH CLAUDE CODE

1. Start Claude Code in the project root directory
2. Share this entire document as context
3. Say: "Follow the SarkariSaar PRD. Start with Milestone 1. Complete all steps and acceptance tests before asking me to review."
4. After each milestone, review and test the acceptance criteria yourself
5. When satisfied, say: "Milestone X is complete. Proceed to Milestone X+1."
6. If something is broken, describe the issue and ask Claude Code to fix it before proceeding

**Do NOT skip milestones. Do NOT start Milestone N+1 until Milestone N passes all acceptance tests.**
