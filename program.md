# job-application-agent

Autonomous job application optimizer. Iterates on cover letter style to maximize recruiter reply rate — the same loop as email-outreach-optimizer, applied to job hunting.

Each "variant" is a cover letter *style template* (tone, structure, angle). Claude reads the variant + the job description + your resume and generates a fully personalized cover letter per application. The optimization loop learns which style gets replies.

## The analogy

| email-outreach-optimizer | job-application-agent |
|---|---|
| Cold email variants | Cover letter style variants |
| `prospects.csv` | `jobs.csv` |
| reply_rate (higher = better) | reply_rate (higher = better) |
| 48-hour eval window | 5-day eval window |
| `generate_variant.py` | `generate_variant.py` |
| `results.tsv` | `results.tsv` |

## Directory layout

```
job-application-agent/
├── program.md              ← this file
├── config.json             ← your name, email, resume path, timing config
├── variants.json           ← active cover letter style template
├── jobs.csv                ← job postings to apply to
├── state.json              ← current phase + timestamps
├── results.tsv             ← variant performance history
├── job_descriptions/       ← .txt files, one per job (referenced in jobs.csv)
├── cover_letter.py         ← generates personalized cover letter via Claude API
├── email_client.py         ← sends email with PDF resume attached + reply tracking
├── engine.py               ← state machine (run this on a schedule)
├── generate_variant.py     ← generates next cover letter style via Claude API
└── orchestrator.py         ← live dashboard: shows status of all applications + agents
```

## Setup

1. Drop your resume PDF at the path set in `config.json` → `resume_path`
2. Set Gmail credentials (or SMTP) as environment variables
3. Set `ANTHROPIC_API_KEY` environment variable
4. Add jobs to `jobs.csv` — one row per job, with a `.txt` file in `job_descriptions/`
5. Run engine: `python engine.py`
6. View dashboard: `python orchestrator.py`

## The state machine

Each run moves through one of four phases:

### Phase: SENDING
Active variant. Engine sends applications (resume + personalized cover letter) to unsent jobs — `BATCH_SIZE` at a time. Transitions to FOLLOW_UP once batch is sent.

### Phase: FOLLOW_UP
Wait `FOLLOW_UP_DELAY_DAYS` days (default: 3), then send a short follow-up email to each application in the batch. Transitions to COLLECTING after follow-ups are sent.

### Phase: COLLECTING
All follow-ups sent. Waiting for the eval window to elapse (default: 5 days from initial send). Each run checks for new replies. Transitions to EVALUATING once window elapses.

### Phase: EVALUATING
Eval window over. Engine:
1. Makes final reply check
2. Calculates `reply_rate = replies / applications_sent`
3. Logs to `results.tsv`
4. Calls `generate_variant.py` → Claude generates next style variant
5. Writes new variant to `variants.json`
6. Resets state to SENDING with new variant

## jobs.csv schema

| Column | Description |
|---|---|
| `id` | Unique job ID (e.g. `job_001`) |
| `company` | Company name |
| `role` | Job title |
| `contact_email` | Recruiter or hiring manager email |
| `job_description_file` | Filename in `job_descriptions/` (e.g. `job_001.txt`) |
| `variant_id` | Filled by engine when application is sent |
| `status` | `pending`, `sent`, `followed_up`, `replied`, `rejected` |
| `sent_at` | ISO8601 timestamp |
| `follow_up_at` | ISO8601 timestamp (scheduled) |
| `follow_up_sent_at` | ISO8601 timestamp |
| `replied_at` | ISO8601 timestamp |
| `message_id` | Email message ID (for reply tracking) |

## variants.json schema

A variant describes a **cover letter style approach** — NOT the actual letter. Claude uses this as a brief when writing each personalized letter.

```json
{
  "id": "v1",
  "description": "Skills-match opener, achievement-led, formal tone",
  "tone": "formal",
  "structure": "opener → skills match → 2 key achievements → fit statement → CTA",
  "opener_style": "Lead with the most relevant skill match to the role",
  "length": "3 paragraphs, under 250 words",
  "cta": "Request a 20-minute call to discuss further",
  "avoid": "Generic phrases like 'I am excited to apply', buzzwords"
}
```

## The metric

**reply_rate = replies / applications_sent** (higher is better)

A "reply" is any response — interest, interview request, rejection, even a polite no. We optimize for response because a reply opens the conversation.

Benchmarks:
- < 5%: poor — try a fundamentally different approach
- 5–15%: average job application response rate
- 15–30%: strong — iterate from this base
- > 30%: exceptional — treat as new baseline

## Experimentation strategy

The first run establishes a baseline. Do not modify `variants.json` before the first run.

Ideas to iterate on (roughly by leverage):
1. **Opener** — first sentence determines if they read further
2. **Length** — 3 tight paragraphs vs 5 detailed ones
3. **Framing** — skills-match vs story-led vs problem-solver angle
4. **Achievements** — metric-heavy vs narrative vs specific-to-role
5. **CTA** — low friction ("worth a quick chat?") vs formal ("happy to discuss")
6. **Tone** — peer-to-peer vs respectful applicant vs confident expert
7. **Subject line** — "Application for [Role]" vs something that stands out

## results.tsv format

```
variant_id  reply_rate  applications_sent  replies  status  description
v1          0.000       20                 0        discard  baseline — skills-match opener, formal
v2          0.100       20                 2        keep     story-led opener, conversational, short CTA
```

## Orchestrator

Run `python orchestrator.py` at any time to see:
- Current phase and variant
- All applications with their status (pending / sent / followed_up / replied)
- Follow-ups due today
- Reply rate per variant (from results.tsv)
- Next scheduled action

## Configuration (config.json)

```json
{
  "applicant_name": "Your Name",
  "resume_path": "/path/to/resume.pdf",
  "sender_email": "you@gmail.com",
  "batch_size": 20,
  "follow_up_delay_days": 3,
  "eval_window_days": 5
}
```

Environment variables (never hardcode in config.json):
- `ANTHROPIC_API_KEY` — Claude API key
- `GMAIL_APP_PASSWORD` — Gmail app password (or `SMTP_PASSWORD` for other providers)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` — if not using Gmail
- `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD` — for reply checking
