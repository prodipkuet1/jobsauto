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
