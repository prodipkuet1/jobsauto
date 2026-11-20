# JobsAuto — AI-assisted Job Search Agent (starter)

A deploy-ready starter for discovering public job listings, ranking them against a candidate profile, and preparing application drafts for human review.

## Safety by design
- **No automatic application submission.**
- No automated messages, contract acceptance, payments, or commitments.
- Draft approval only marks a draft as approved for manual use; it does not submit anything.
- The starter does not scrape login-protected LinkedIn, Upwork, Freelancer, Indeed, or bypass CAPTCHAs/access controls.
- Always verify job availability, salary, eligibility, visa requirements and requirements on the original listing.

## Features
- FastAPI backend and lightweight responsive dashboard.
- Public listings from Arbeitnow and Remotive APIs.
- Duplicate prevention by canonical listing URL.
- Transparent keyword-based relevance score (not an AI guarantee).
- Candidate profile seeded from information supplied by the owner.
- Cover-letter and proposal draft generation.
- Manual job entry API: `POST /api/jobs`.
- Health endpoint: `/health`.

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000

For local development, `ADMIN_TOKEN` may be left unset. Before exposing the app publicly, set a strong `ADMIN_TOKEN` and use the Bearer token for `/api/*` endpoints. The dashboard currently assumes trusted/private access; see Security notes.

## Deploy on Render
1. Push this repository to GitHub.
2. In Render, select **New → Blueprint** and connect this repository.
3. Render reads `render.yaml`. Review the proposed resources and plan before applying.
4. Select the free web-service plan if available in your account/region. Do not approve any paid resources.
5. After deployment, set a strong `ADMIN_TOKEN` in the service Environment page if you prefer to manage it yourself. The Blueprint generates one by default.
6. Verify `https://YOUR-SERVICE.onrender.com/health`.

### Persistence warning
The default database path `/tmp/jobsauto.db` is ephemeral on Render. Saved jobs and drafts may be lost when the service restarts or redeploys. For persistent data, configure a persistent disk (which may incur a charge) or connect a database only after reviewing its cost. This starter intentionally does not provision paid storage.

## API
- `GET /health`
- `GET /api/profile`
- `GET /api/jobs`
- `POST /api/search`
- `POST /api/jobs`
- `POST /api/drafts/{job_id}`
- `GET /api/drafts`
- `POST /api/drafts/{draft_id}/approve`

If `ADMIN_TOKEN` is set, send `Authorization: Bearer <token>` for `/api/*`.

## Next development milestones
1. Add proper login/session management and CSRF protection for a multi-user public dashboard.
2. Add persistent database and scheduled search (review costs first).
3. Add compliant integrations using official APIs or user-authorized browser sessions where allowed.
4. Add configurable salary, region, contract type and visa filters.
5. Improve matching with explainable skill/requirement evidence and gap analysis.
6. Add editing/export of CV and application drafts.

## Disclaimer
This is an initial working scaffold, not a production-ready autonomous recruiter. Job source coverage is limited to the public feeds listed above. Matching scores are heuristic estimates and must be reviewed.

## International jobs and scholarship eligibility filters (v0.4)

The update adds separate `opportunities` and `scholarships` tables and API views. A record appears in the **eligible** view only when all of these are true:

- The stated deadline is more than 7 full days after the current UTC search time.
- `foreign_eligibility` is explicitly `yes`, `bangladesh_eligibility` is explicitly `yes`, and an eligibility evidence note is supplied.
- For scholarships, `current_phd_eligible` must also be `yes`, because this profile is already enrolled in a full-time PhD at Chandigarh University.
- `verification_status` is `verified`.
- Both `official_url` and `description_url` are valid HTTPS URLs.

Unknown deadlines, unknown nationality rules, expired/near-deadline calls, and unverified URLs are excluded. Existing Arbeitnow/Remotive job-feed records are retained as general leads because those feeds do not reliably provide closing dates or Bangladeshi applicant eligibility; they are not promoted into the verified shortlist automatically.

### New endpoints
- `GET /api/portals` — official job and scholarship portal directory.
- `GET /api/opportunities` — verified jobs meeting the >7-day and foreign-eligibility filters.
- `GET /api/opportunities?eligible_only=false` — all saved job opportunity records, including verification queue.
- `POST /api/opportunities` — add/update an opportunity after checking its official call.
- `GET /api/scholarships` — verified scholarship/research funding calls meeting the same filters.
- `GET /api/scholarships?eligible_only=false` — all saved scholarship records, including verification queue.
- `POST /api/scholarships` — add/update a scholarship after checking its official call and faculty contacts.

### Scholarship record fields
Use `professor_name`, `professor_title`, `professor_email`, `professor_profile_url`, `department`, `institution_url`, and `contact_verification`. Set `contact_verification` to `verified` only when the name, institutional email and faculty profile are published on official university pages. If a call has no named contact, leave the contact fields blank and state that no professor contact is published; never infer or fabricate an email address.

### Important verification boundary
The portal directory provides official starting pages, not proof that a particular opening is live or accepts Bangladeshi nationals. JobsAuto does not automatically certify a page's contents. The administrator must inspect the official call, record the exact closing date, confirm foreign-national eligibility and cite the wording in `eligibility_evidence` before marking a record `verified`. This avoids presenting aggregator snippets or guessed eligibility as verified facts.

### Example job record
```json
{
  "title": "Research Software Engineer",
  "employer": "Example Institute",
  "location": "Remote / country-specific",
  "deadline": "2026-12-20T23:59:00Z",
  "foreign_eligibility": "yes",
  "bangladesh_eligibility": "yes",
  "eligibility_evidence": "Official vacancy explicitly confirms Bangladeshi applicants may apply; work authorization conditions are stated on the employer page.",
  "official_url": "https://example.edu/jobs/123",
  "description_url": "https://example.edu/jobs/123/details",
  "source_portal_url": "https://example.edu/careers",
  "source_name": "Example Institute Careers",
  "verification_status": "verified"
}
```

### Example scholarship record
```json
{
  "title": "Doctoral Research Mobility Grant",
  "provider": "Example University",
  "country": "Germany",
  "degree_level": "Research stay for currently enrolled PhD candidates",
  "deadline": "2026-12-20T23:59:00Z",
  "foreign_eligibility": "yes",
  "bangladesh_eligibility": "yes",
  "eligibility_evidence": "Official call explicitly lists Bangladesh as an eligible country.",
  "current_phd_eligible": "yes",
  "ielts_requirement": "not_required",
  "recommendation_requirement": "required",
  "official_url": "https://example.edu/funding/123",
  "description_url": "https://example.edu/funding/123/call",
  "source_portal_url": "https://example.edu/funding",
  "professor_name": "Dr Example",
  "professor_title": "Professor",
  "professor_email": "name@example.edu",
  "professor_profile_url": "https://example.edu/people/example",
  "department": "Computer Science",
  "institution_url": "https://example.edu",
  "contact_verification": "verified",
  "verification_status": "verified",
  "research_fit": "AI-based weather forecasting and privacy-preserving data analytics"
}
```

The example URLs and names above are placeholders for documentation only; do not save them as real opportunities.


## International migration pathway directory

JobsAuto now includes official government information portals for Germany (Make it in Germany, Opportunity Card, EU Blue Card, skilled-worker and research visas), Canada (Job Bank foreign candidates, Express Entry/Federal Skilled Worker, Provincial Nominee Program and Atlantic Immigration Program), plus the Netherlands, United Kingdom and Australia. These are informational starting points only; JobsAuto does not provide legal advice or guarantee visa eligibility. Verify current criteria with the destination government's immigration authority before paying fees or making decisions.

Germany's Make it in Germany job listings are specifically described by the Federal Government as vacancies whose employers agreed to receive applications from foreign skilled workers. Canada's Job Bank foreign-candidate pages distinguish postings open to international candidates from postings restricted to Canadian citizens, permanent residents or existing work-permit holders. JobsAuto lists the official portals but does not infer that every vacancy on a country's general job boards sponsors visas.
