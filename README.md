# Job Application Agent

An automated job application system that finds relevant roles on LinkedIn, writes personalised cover letters using OpenAI, sends them via Gmail, follows up automatically, and A/B tests email variants to improve reply rates over time.

Built to automate my own job search while studying at NUS — applies AI across scraping, personalisation, and A/B testing to turn job hunting into a measurable, self-improving system.

---

## How It Works

The engine runs a 4-phase loop:

```
SENDING → FOLLOW_UP → COLLECTING → EVALUATING → (repeat)
```

| Phase | What happens |
|-------|-------------|
| **SENDING** | Generates a personalised cover letter for each pending job and sends it via Gmail with your resume attached |
| **FOLLOW_UP** | 3 days later, sends a consolidated follow-up to any contacts that haven't replied |
| **COLLECTING** | Waits 5 days for replies; you check Gmail daily with the orchestrator |
| **EVALUATING** | Measures the reply rate for the current email variant, logs the result, then uses OpenAI to generate an improved variant for the next batch |

Each cycle teaches the system what email style actually gets responses.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure `.env`

Create a `.env` file (see `.env.example`):

```env
OPENAI_API_KEY=sk-...
APIFY_API_KEY=apify_api_...
SENDER_EMAIL=you@gmail.com
SENDER_NAME=Your Name
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
hunter_api_key=...
LINKEDIN_COOKIE=AQE...   # li_at cookie from browser
```

**Gmail App Password:** Go to myaccount.google.com → Security → 2-Step Verification → App Passwords.

### 3. Configure `config.json`

```json
{
  "applicant_name": "Your Name",
  "resume_path": "/absolute/path/to/resume.pdf",
  "sender_email": "you@gmail.com",
  "batch_size": 20,
  "follow_up_delay_days": 3,
  "eval_window_days": 5,
  "email_provider": "gmail",
  "follow_up_subject_prefix": "Following up — "
}
```

---

## Usage

### Step 1 — Find jobs

Scrapes LinkedIn for matching roles, scores each against your resume (GPT-4o-mini), and saves qualifying jobs to `jobs.csv`:

```bash
python3 scrapers/linkedin_scraper.py
```

### Step 2 — Run the engine (daily)

Executes whichever phase the system is currently in:

```bash
python3 engine.py
```

### Step 3 — Check for replies

Scans Gmail for replies and updates job statuses. Run this daily during the COLLECTING phase:

```bash
python3 orchestrator.py --check
```

### View dashboard

```bash
python3 orchestrator.py
```

### Preview emails before sending

```bash
python3 utils/preview.py          # preview cover letters
python3 utils/preview_followup.py # preview follow-up emails
```

### Mark a job as replied manually

```bash
python3 orchestrator.py --mark-replied job_007
```

### Find HR emails for a specific company

```bash
python3 scrapers/scrape_ncs_hr.py    # company-specific HR contacts via Apify + Hunter.io
python3 scrapers/find_hr_emails.py   # HR emails for all scraped companies via Hunter.io
```

---

## File Structure

```
job-application-agent/
├── README.md
├── requirements.txt
├── config.json                      # Applicant config (name, resume path, batch size)
├── variants.json                    # Active email style template
├── .env.example
├── .gitignore
│
├── engine.py                        # State machine — run daily
├── orchestrator.py                  # Dashboard + reply checker
│
├── core/                            # Email generation & sending
│   ├── cover_letter.py              # AI cover letter generator (OpenAI)
│   ├── email_client.py              # Gmail sender
│   └── generate_variant.py          # A/B variant generator (OpenAI)
│
├── scrapers/                        # Job discovery & HR enrichment
│   ├── linkedin_scraper.py          # LinkedIn job search via Apify + resume scoring
│   ├── scraper.py                   # Base scraper
│   ├── scrape_only.py               # Scrape without scoring
│   ├── score_and_enrich.py          # Score scraped jobs + enrich with HR emails
│   ├── find_hr_emails.py            # HR email lookup via Hunter.io (bulk)
│   └── scrape_ncs_hr.py             # Company-specific HR contact scraper
│
└── utils/                           # Dev tools
    ├── preview.py                   # Preview cover letters in terminal
    ├── preview_followup.py          # Preview follow-up emails in terminal
    └── gmail_mcp_helper.py          # Gmail MCP integration helper
```

**Local-only (gitignored):**

```
├── jobs.csv                         # Full pipeline — every job and its status
├── state.json                       # Current phase + timestamps
├── results.tsv                      # A/B test history (variant → reply rate)
└── job_descriptions/                # Full JD text per job (job_001.txt, ...)
```

---

## Job Statuses

| Status | Meaning |
|--------|---------|
| `pending` | Queued, not yet sent |
| `sent` | Application sent, awaiting follow-up window |
| `followed_up` | Follow-up sent, waiting for reply |
| `replied` | Company replied |
| `no_response` | No reply after follow-up + 5 days |
| `bounced` | Email address invalid |
| `rejected` | Explicit rejection received |

---

## A/B Testing

Each batch of applications uses one email `variant` (tone, structure, opener style, CTA). After the eval window:

- Reply rate ≥ 5% → variant marked `keep`
- Reply rate < 5% → variant marked `discard`

OpenAI then generates the next variant, informed by what has and hasn't worked. Results are logged to `results.tsv`.

Current variant config lives in `variants.json` and controls tone, structure, opener style, length, subject line format, and phrases to avoid.
