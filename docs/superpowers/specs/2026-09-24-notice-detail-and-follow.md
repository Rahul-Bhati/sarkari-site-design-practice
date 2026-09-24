# Spec: Notice detail, deadline follow, WhatsApp forward

**Date:** 2026-09-24
**Status:** Spec only. Do not start code until this is accepted.
**Builds on:** `docs/superpowers/specs/2026-09-24-scale-gaps.md`. A changed deadline already updates the stored row. This spec is what a reader sees and what brings them back.

## Assumptions

1. The first reader is someone looking at one vacancy or one scheme, then sending it to a family WhatsApp group. A comment feed is out of scope.
2. “Follow” means one notice, not every future notice from that department. A standing “all SSC” follow stays on the filters a subscriber already has.
3. The reminder goes to a signed-in user, by email, 3 days before the deadline. WhatsApp is sent only when that user already has a verified phone on a plan that includes WhatsApp. Gupshup stays off unless those keys are set.
4. Facts on the page come from the notice PDF’s text layer, using the extractor that already exists (`extract_pdf_text`). Scanned PDFs that come back almost empty stay as a link to the official file. OCR is not part of this spec.
5. A portal date still wins over a date guessed by the model.
6. Migration `009` is not applied and is not required here. A new migration file is written and not run until you say so.
7. `tasks/plan.md` and `tasks/todo.md` stay as they are.

## Objective

A vacancy or scheme page shows the facts a person would otherwise read the PDF for, they can ask to be told before it closes and if the date moves, and the WhatsApp share already contains those facts.

### Who it is for

Someone comparing one government job or one scheme, and the person they forward it to.

## The three things

### 1. Detail block from the notice

While a naukri or yojana entry has a `pdf_url`, when it is scraped or revised, the system shall download that PDF, extract its text, and store the text on the entry. The public page shall show a fixed block. Missing fields are omitted, not filled with a guess.

**Vacancy (`naukri`)**

| Label on the page | Stored as |
|---|---|
| Post | `key_details.post` |
| Vacancies | `key_details.vacancies` (already exists) |
| Pay | `key_details.pay` |
| Age | `key_details.age` |
| Qualification | `key_details.qualification` |
| Fee | `key_details.fee` |
| Important dates | `key_details.important_dates` (list of `{label, date}`) |
| How to apply | `key_details.how_to_apply` |
| Apply link | `key_details.application_link` (already exists) |
| Last date | `entries.deadline` (already exists) |

**Scheme (`yojana`)**

| Label on the page | Stored as |
|---|---|
| Who it is for | `eligibility` text (already exists) |
| What you get | `key_details.benefit` |
| How to apply | `key_details.how_to_apply` |
| Last date | `entries.deadline` |

The English and Hindi summaries stay above this block. They are not a substitute for it. If the PDF has no text layer, the page says the notice could not be read and keeps the official link.

The model may fill a field only when that value appears in the extracted text. It must not invent a vacancy count or a fee. Portal-extracted dates are not overwritten.

### 2. Follow one notice

While a signed-in user is on a notice that has a deadline, when they choose Follow, the system shall store that pair and email them once when the deadline is 3 days away in IST. If the stored deadline later changes, the system shall email them once that it moved, and the 3-day reminder is scheduled from the new date.

A notice with no deadline cannot be followed for a reminder. It can still be bookmarked, which already exists and does not send mail.

Unfollow stops both the closing reminder and the date-moved mail. A second follow of the same notice does not create a second row.

### 3. WhatsApp forward

While the detail page is open, when the reader presses Share on WhatsApp, the message shall be:

```
{title}
Last date: {deadline or "not listed"}
Posts: {vacancies or omitted}
{page url}
```

The page URL is this site’s entry page, so the next person sees the detail block. The official PDF stays a button on that page.

## Tech stack

- Backend: Python 3.13, FastAPI, the existing PyMuPDF extractor, Resend for the reminder email
- Frontend: Next.js 16, the existing entry page and `ShareButtons`
- Database: Supabase Postgres. New table in `supabase/migrations/010_notice_follows.sql`, not applied by the agent

## Commands

```bash
cd backend && .venv/bin/python -m pytest tests/test_notice_facts.py tests/test_follows.py -q
cd backend && .venv/bin/python -m pytest
cd frontend && npm run build
```

## Project structure

```
docs/superpowers/specs/2026-09-24-notice-detail-and-follow.md   → this spec
backend/app/scrapers/utils/pdf_extractor.py                     → already extracts text; call it
backend/app/services/notice_facts.py                            → which fields are safe to store
backend/app/services/follows.py                                 → who to remind, and for which date
frontend/src/app/entry/[id]/page.tsx                            → detail block
frontend/src/components/entry/ShareButtons.tsx                  → WhatsApp text
frontend/src/components/entry/FollowButton.tsx                  → follow / unfollow
supabase/migrations/010_notice_follows.sql                      → follows table, not applied
```

## Code style

One function decides the message and the reminder. The database call sits outside it.

```python
def whatsapp_text(title: str, deadline: str | None, vacancies: int | None, url: str) -> str:
    """The forward a family group already expects. Omit posts when we do not have a count."""
```

```python
def reminder_due(deadline: date, today: date, already_sent: bool) -> bool:
    """True on the IST day that is three days before `deadline`, once."""
```

## Testing strategy

- pytest for the fact filter, the WhatsApp string, and the reminder calendar. No network, no Supabase.
- A PDF with no text layer does not call the model and does not write vacancies.
- Frontend build is the check once the entry page and the share button change.
- Do not send a real email or WhatsApp from tests.

## Boundaries

- Always: show the official link. Leave a field blank when the text does not contain it. Run the targeted pytest before calling a slice done.
- Ask first: applying migration 010, turning on Gupshup, adding an OCR provider, deploying.
- Never: invent eligibility or a fee, overwrite a portal deadline, send a reminder to someone who did not follow, put the admin key in the browser.

## What to build

Already in the repo, so these are wiring, not new systems:

- `extract_pdf_text` reads a PDF and is never called from the scraper.
- The entry page already renders vacancies, eligibility, last date, and an apply link when `key_details` has them.
- `ShareButtons` opens WhatsApp with the title and the URL only.
- Bookmarks save a notice and send nothing.
- Email sending exists on the digest path.

Build these, in this order:

1. **Fetch the PDF and keep its text.** After a naukri or yojana row is inserted or its `pdf_url` changes, download the file and store the extracted text in `original_text`. Skip the download when the text is already there and the PDF URL did not change. If `needs_ocr` is true, store nothing new and leave the official link.
2. **Fill only the detail fields the text supports.** Extend `KeyDetails` with `post`, `pay`, `age`, `qualification`, `fee`, `important_dates`, `how_to_apply`, `benefit`. A writer rejects a number or a fee that does not occur in the extracted text. The entry page lists the vacancy rows and the scheme rows from the tables above, and hides empty ones.
3. **Follow table and button.** `notice_follows(user_id, entry_id, remind_days default 3, last_deadline, reminded_at, moved_notified_at)`. Signed-in only. Follow and unfollow on the entry page. RLS: a user reads and writes their own rows. The API uses the existing user token, not the admin key.
4. **Reminder job.** Once a day, select follows whose deadline is three IST days away and `reminded_at` is empty, send one email, then set `reminded_at`. Separately, if `entries.deadline` differs from `last_deadline`, send one “date moved” email and store the new date. A failed send does not mark the row as sent.
5. **WhatsApp text.** `ShareButtons` receives title, deadline, and vacancies and uses `whatsapp_text`. No backend call.

## Success criteria

- [ ] A naukri entry with a text PDF shows post, vacancies, pay, age, qualification, fee, dates, and how to apply when those strings are in the PDF, and hides the ones that are not.
- [ ] A yojana entry shows who it is for, what you get, how to apply, and the last date on the same rule.
- [ ] A scanned PDF does not invent those fields.
- [ ] Follow creates one row per user and notice. Unfollow removes it.
- [ ] The reminder email is due only on the day three days before the deadline, and only once.
- [ ] A deadline change produces one “date moved” mail and resets the closing reminder to the new date.
- [ ] The WhatsApp message contains the title, the last date, the post count when known, and this site’s entry URL.
- [ ] A visitor who is not signed in can still share. Follow asks them to sign in.
- [ ] Migration 010 is in the repo and has not been applied by the agent.

## Open questions

- Whether the 3-day reminder should also be offered as 1 day. The spec ships 3 days only until you want the choice.
- Whether a follow without an account, using only an email typed on the page, is required. This spec uses the account that already exists.
