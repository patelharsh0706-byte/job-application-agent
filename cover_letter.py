"""
cover_letter.py

Generates a personalized cover letter and email subject line using OpenAI API.

Inputs:
  - variant: the active style template from variants.json
  - job: a row from jobs.csv (company, role, job_description_file)
  - resume_text: plain-text extracted from the applicant's resume PDF
  - applicant_name: from config.json

Output:
  {"subject": str, "cover_letter": str}
"""

import os
from openai import OpenAI


def extract_resume_text(resume_path: str) -> str:
    """Extract plain text from a PDF resume using pdfminer."""
    try:
        from pdfminer.high_level import extract_text
        return extract_text(resume_path)
    except ImportError:
        raise RuntimeError(
            "pdfminer.six is required to read the resume PDF.\n"
            "Install it with: pip install pdfminer.six"
        )


def generate_cover_letter(
    variant: dict,
    job: dict,
    resume_text: str,
    applicant_name: str,
) -> dict:
    """
    Call OpenAI API to generate a personalized cover letter for a single job.

    Returns:
        {"subject": str, "cover_letter": str}
    """
    job_description = _load_job_description(job["job_description_file"])

    prompt = f"""You are writing a professional job application cover letter on behalf of {applicant_name}.

## STEP 1 — Understand the role
Read the job description carefully. Identify:
- The 3 most important responsibilities
- The 3 most critical requirements/skills they are looking for

## STEP 2 — Match the applicant
From the resume, identify ONLY the experiences and skills that directly address those responsibilities and requirements.
IGNORE any experience that is irrelevant to this specific role (e.g. if the role is product/creative/AI, do not mention mechanical engineering, plant shutdowns, or industrial work).

## STEP 3 — Write the letter using this exact structure
1. Salutation: "Dear Hiring Manager,"
2. Opening paragraph: Start with the strongest skill/experience match to their top requirement. Be specific, not generic.
3. Middle paragraph: Map 2 specific achievements from the resume to their key responsibilities. Use metrics where available. Only include achievements relevant to this role.
4. Closing paragraph: Affirm fit + CTA — {variant["cta"]}
5. Sign-off: "Best regards," followed by a blank line, then the applicant's full name and contact details.

## Cover Letter Style
- Tone: {variant["tone"]}
- Length: {variant["length"]}
- Avoid: {variant["avoid"]}
- Subject line style: {variant["subject_line_style"]}

## Applicant Resume
{resume_text}

## Job Details
Company: {job["company"]}
Role: {job["role"]}
Job Description:
{job_description}

## Output Instructions
1. First line: "SUBJECT: <subject line>"
2. Blank line
3. Full cover letter body following the structure above
4. Do NOT use placeholders — use real names, real companies, real achievements from the resume
5. Sign off exactly as: "Best regards,\\n\\n{applicant_name}\\n+65 89036674 | harsh.patel502@gmail.com"

Output format:
SUBJECT: <subject line>

Dear Hiring Manager,

<body>

Best regards,

{applicant_name}
+65 89036674 | harsh.patel502@gmail.com
"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()
    return _parse_output(raw, job)


def generate_follow_up(
    job: dict,
    applicant_name: str,
    original_subject: str,
) -> dict:
    """
    Generate a short, non-pushy follow-up email for an application sent 3 days ago.

    Returns:
        {"subject": str, "cover_letter": str}
    """
    prompt = f"""Write a brief, professional follow-up email for a job application sent 3 days ago.

Applicant: {applicant_name}
Company: {job["company"]}
Role: {job["role"]}
Original subject: {original_subject}

Requirements:
- Start with "Dear Hiring Manager,"
- 2-3 sentences only — polite, warm, not pushy
- Reaffirm genuine interest in the role and company
- Offer to provide any additional information if needed
- Sign off exactly as:
  Best regards,

  {applicant_name}
  +65 89036674 | harsh.patel502@gmail.com

Output format:
SUBJECT: Re: {original_subject}

Dear Hiring Manager,

<body>

Best regards,

{applicant_name}
+65 89036674 | harsh.patel502@gmail.com
"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=256,
    )

    raw = response.choices[0].message.content.strip()
    return _parse_output(raw, job)


def generate_consolidated_follow_up(
    jobs: list[dict],
    applicant_name: str,
) -> dict:
    """
    Generate ONE follow-up email for multiple roles at the same company/email.
    Used when multiple jobs share the same contact_email (e.g. Snaphunt).

    Returns:
        {"subject": str, "cover_letter": str}
    """
    company = jobs[0]["company"]
    roles = [j["role"] for j in jobs]
    roles_list = "\n".join(f"- {r}" for r in roles)

    # Use first job as the representative for parsing
    representative_job = jobs[0]

    if len(jobs) == 1:
        subject_line = f"Following up — {roles[0]}"
    else:
        subject_line = f"Following up — {len(roles)} applications at {company}"

    prompt = f"""Write a brief, professional follow-up email covering multiple job applications sent 3 days ago to the same company.

Applicant: {applicant_name}
Company: {company}
Roles applied for:
{roles_list}

Requirements:
- Start with "Dear Hiring Manager,"
- 3-4 sentences only — polite, not pushy
- Mention you applied for multiple roles (list them briefly)
- Reaffirm genuine interest and offer to provide any additional information
- Sign off exactly as:
  Best regards,

  {applicant_name}
  +65 89036674 | harsh.patel502@gmail.com

Output format:
SUBJECT: {subject_line}

Dear Hiring Manager,

<body>

Best regards,

{applicant_name}
+65 89036674 | harsh.patel502@gmail.com
"""

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
    )

    raw = response.choices[0].message.content.strip()
    return _parse_output(raw, representative_job)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_job_description(filename: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, "job_descriptions", filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Job description file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _parse_output(raw: str, job: dict) -> dict:
    """Parse model output into subject + body."""
    lines = raw.splitlines()
    subject = ""
    body_lines = []
    found_subject = False

    for line in lines:
        if not found_subject and line.startswith("SUBJECT:"):
            subject = line[len("SUBJECT:"):].strip()
            found_subject = True
        elif found_subject:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()

    if not subject:
        subject = f"Application: {job['role']} at {job['company']}"
        body = raw

    return {"subject": subject, "cover_letter": body}
