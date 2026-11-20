import os
import sqlite3
import re
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urlparse, urlencode

import requests
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.eligibility import eligible_record, valid_https

APP_DIR = os.path.dirname(__file__)
PROJECT_DIR = os.path.dirname(APP_DIR)
DB_PATH = os.getenv("DATABASE_PATH", "/tmp/jobsauto.db")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

PROFILE = {
    "headline": "WordPress Developer | Website Maintenance & Technical Support",
    "summary": (
        "Computer Science and Engineering graduate and postgraduate from KUET, Bangladesh. "
        "Experience as Assistant Programmer, Network Engineer and System Analyst, including "
        "automation systems, WordPress and website maintenance, Linux/web servers, DNS, email, "
        "FTP, networking, infrastructure troubleshooting and technical support."
    ),
    "skills": [
        "WordPress", "Elementor", "WooCommerce", "PHP", "JavaScript", "HTML", "CSS",
        "Linux", "Web Servers", "DNS", "Email", "FTP", "Website Maintenance",
        "Website Migration", "Technical Support", "Networking", "System Administration",
        "AI Automation", "Data Analysis"
    ],
    "education": [
        "BSc in Computer Science & Engineering, KUET",
        "MSc in Computer Science & Engineering, KUET"
    ],
    "experience": ["Assistant Programmer", "Network Engineer", "System Analyst"],
    "languages": ["English (Fluent)", "Bengali (Native)", "Hindi (Conversational)"]
}

app = FastAPI(title="JobsAuto - Job & Scholarship Discovery", version="0.4.0")
app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_DIR, "static")), name="static")


def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, company TEXT, location TEXT, work_type TEXT,
            salary TEXT, source TEXT, url TEXT UNIQUE, description TEXT,
            posted_at TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    for name, declaration in {
        "deadline": "TEXT", "foreign_eligibility": "TEXT DEFAULT 'unknown'",
        "eligibility_evidence": "TEXT", "official_url": "TEXT", "description_url": "TEXT",
        "source_portal_url": "TEXT", "verification_status": "TEXT DEFAULT 'needs_verification'"
    }.items():
        if name not in job_columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER, cover_letter TEXT, proposal TEXT,
            status TEXT DEFAULT 'needs_review',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(job_id) REFERENCES jobs(id)
        )
    """)
    # Safe additive migrations for databases created by earlier JobsAuto versions.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()}
    migrations = {
        "approved_at": "TEXT",
        "submission_method": "TEXT",
        "submission_status": "TEXT DEFAULT 'not_submitted'",
        "submitted_at": "TEXT",
        "last_submission_note": "TEXT"
    }
    for name, declaration in migrations.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE drafts ADD COLUMN {name} {declaration}")
    # Opportunity records are separate from ordinary job-feed records. A listing
    # cannot appear in the eligible view until its deadline, foreign eligibility,
    # official URLs and evidence have been explicitly verified.
    conn.execute("""CREATE TABLE IF NOT EXISTS opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, employer TEXT,
        location TEXT, work_type TEXT, compensation TEXT, deadline TEXT,
        foreign_eligibility TEXT DEFAULT 'unknown', bangladesh_eligibility TEXT DEFAULT 'unknown', eligibility_evidence TEXT,
        official_url TEXT, description_url TEXT, source_portal_url TEXT,
        verification_status TEXT DEFAULT 'needs_verification', verified_at TEXT,
        source_name TEXT, summary TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(official_url))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scholarships (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, provider TEXT,
        country TEXT, degree_level TEXT, funding TEXT, deadline TEXT,
        foreign_eligibility TEXT DEFAULT 'unknown', bangladesh_eligibility TEXT DEFAULT 'unknown', eligibility_evidence TEXT,
        current_phd_eligible TEXT DEFAULT 'unknown', ielts_requirement TEXT DEFAULT 'unknown',
        recommendation_requirement TEXT DEFAULT 'unknown', official_url TEXT,
        description_url TEXT, source_portal_url TEXT, professor_name TEXT,
        professor_title TEXT, professor_email TEXT, professor_profile_url TEXT,
        department TEXT, institution_url TEXT, contact_verification TEXT DEFAULT 'unknown',
        verification_status TEXT DEFAULT 'needs_verification', verified_at TEXT,
        research_fit TEXT, summary TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(official_url))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS discovery_leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
        title TEXT NOT NULL, result_url TEXT NOT NULL UNIQUE, source_name TEXT,
        source_url TEXT, published_at TEXT, search_query TEXT, summary TEXT,
        verification_status TEXT DEFAULT 'needs_verification',
        discovered_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    for table in ("opportunities", "scholarships"):
        table_columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "bangladesh_eligibility" not in table_columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN bangladesh_eligibility TEXT DEFAULT 'unknown'")
    conn.commit()
    return conn


def require_auth(authorization: Optional[str] = Header(default=None)):
    if not ADMIN_TOKEN:
        return True
    expected = f"Bearer {ADMIN_TOKEN}"
    if not secrets.compare_digest(authorization or "", expected):
        raise HTTPException(status_code=401, detail="Set Authorization: Bearer <ADMIN_TOKEN>")
    return True


class JobIn(BaseModel):
    title: str
    company: str = ""
    location: str = ""
    work_type: str = ""
    salary: str = ""
    source: str = "Manual"
    url: str
    description: str = ""
    posted_at: str = ""


class DraftEdit(BaseModel):
    cover_letter: str = Field(min_length=1)
    proposal: str = Field(min_length=1)


class SubmissionChoice(BaseModel):
    method: str
    confirmed: bool = False


class OpportunityIn(BaseModel):
    title: str = Field(min_length=2)
    employer: str = ""
    location: str = ""
    work_type: str = ""
    compensation: str = ""
    deadline: str
    foreign_eligibility: str = "unknown"
    bangladesh_eligibility: str = "unknown"
    eligibility_evidence: str = ""
    official_url: str
    description_url: str
    source_portal_url: str = ""
    source_name: str = ""
    summary: str = ""
    verification_status: str = "needs_verification"


class ScholarshipIn(BaseModel):
    title: str = Field(min_length=2)
    provider: str = ""
    country: str = ""
    degree_level: str = "PhD/research funding"
    funding: str = ""
    deadline: str
    foreign_eligibility: str = "unknown"
    bangladesh_eligibility: str = "unknown"
    eligibility_evidence: str = ""
    current_phd_eligible: str = "unknown"
    ielts_requirement: str = "unknown"
    recommendation_requirement: str = "unknown"
    official_url: str
    description_url: str
    source_portal_url: str = ""
    professor_name: str = ""
    professor_title: str = ""
    professor_email: str = ""
    professor_profile_url: str = ""
    department: str = ""
    institution_url: str = ""
    contact_verification: str = "unknown"
    verification_status: str = "needs_verification"
    research_fit: str = ""
    summary: str = ""


def validate_record_urls(data):
    for field in ("official_url", "description_url"):
        if not valid_https(data.get(field)):
            raise HTTPException(400, f"{field} must be a full HTTPS URL.")
    for field in ("source_portal_url", "professor_profile_url", "institution_url"):
        value = data.get(field)
        if value and not valid_https(value):
            raise HTTPException(400, f"{field} must be HTTPS when provided.")
    if data.get("foreign_eligibility") not in {"yes", "no", "unknown"}:
        raise HTTPException(400, "foreign_eligibility must be yes, no, or unknown.")
    if data.get("bangladesh_eligibility", "unknown") not in {"yes", "no", "unknown"}:
        raise HTTPException(400, "bangladesh_eligibility must be yes, no, or unknown.")
    if data.get("verification_status") not in {"verified", "needs_verification", "rejected"}:
        raise HTTPException(400, "Invalid verification_status.")
    if data.get("verification_status") == "verified" and not data.get("eligibility_evidence", "").strip():
        raise HTTPException(400, "Verified records require quoted or summarized official eligibility evidence.")
    if data.get("verification_status") == "verified" and data.get("foreign_eligibility") != "yes":
        raise HTTPException(400, "Only records explicitly verified as open to foreign applicants can be marked verified.")
    if data.get("verification_status") == "verified" and data.get("bangladesh_eligibility") != "yes":
        raise HTTPException(400, "Verified records must explicitly confirm eligibility for Bangladeshi applicants.")


def score_job(title, description, location="", work_type=""):
    text = " ".join([title or "", description or ""]).lower()
    groups = {
        "wordpress": ["wordpress", "elementor", "woocommerce", "wp developer", "website maintenance"],
        "web_support": ["website support", "technical support", "web developer", "php", "javascript"],
        "infra": ["linux", "system administrator", "network engineer", "network administrator", "dns", "server administrator", "it support"],
        "automation_data": ["automation", "workflow", "data analyst", "data analysis"]
    }
    points = sum(22 for words in groups.values() if any(word in text for word in words))
    if any(term in text for term in ["remote", "work from home", "anywhere"]):
        points += 8
    if any(term in (location or "").lower() for term in ["europe", "worldwide", "remote"]):
        points += 5
    if any(term in text for term in ["senior", "lead", "principal"]) and not any(term in text for term in ["junior", "entry level"]):
        points -= 5
    return max(0, min(100, points))


def insert_job(conn, item):
    score = score_job(item.get("title", ""), item.get("description", ""), item.get("location", ""), item.get("work_type", ""))
    conn.execute("""
        INSERT OR IGNORE INTO jobs(title,company,location,work_type,salary,source,url,description,posted_at,score)
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        item.get("title", ""), item.get("company", ""), item.get("location", ""),
        item.get("work_type", ""), item.get("salary", ""), item.get("source", ""),
        item.get("url", ""), item.get("description", ""), item.get("posted_at", ""), score
    ))
    return conn.execute("SELECT changes()").fetchone()[0] == 1


def draft_row(conn, draft_id):
    row = conn.execute("""
        SELECT drafts.*, jobs.title, jobs.company, jobs.url, jobs.location, jobs.salary, jobs.source
        FROM drafts JOIN jobs ON jobs.id=drafts.job_id WHERE drafts.id=?
    """, (draft_id,)).fetchone()
    return dict(row) if row else None


@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(PROJECT_DIR, "static", "index.html"), encoding="utf-8") as file:
        return file.read()


@app.get("/api/profile")
def profile(_=Depends(require_auth)):
    return PROFILE


@app.get("/api/jobs")
def jobs(limit: int = 100, _=Depends(require_auth)):
    conn = db()
    rows = conn.execute("SELECT * FROM jobs ORDER BY score DESC, created_at DESC LIMIT ?", (min(limit, 300),)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/jobs")
def add_job(job: JobIn, _=Depends(require_auth)):
    conn = db()
    data = job.model_dump()
    inserted = insert_job(conn, data)
    conn.commit()
    row = conn.execute("SELECT * FROM jobs WHERE url=?", (data["url"],)).fetchone()
    conn.close()
    return {"inserted": inserted, "job": dict(row) if row else None}


@app.post("/api/search")
def search_jobs(_=Depends(require_auth)):
    conn = db()
    added, errors = 0, []
    sources = [
        ("Arbeitnow", "https://www.arbeitnow.com/api/job-board-api"),
        ("Remotive", "https://remotive.com/api/remote-jobs?limit=50")
    ]
    for source, url in sources:
        try:
            response = requests.get(url, timeout=20, headers={"User-Agent": "JobsAuto/0.2"})
            response.raise_for_status()
            payload = response.json()
            items = payload.get("data", []) if source == "Arbeitnow" else payload.get("jobs", [])
            for item in items:
                description = re.sub(r"<[^>]+>", " ", item.get("description", "") or "")
                job = {
                    "title": item.get("title", ""),
                    "company": item.get("company_name") or item.get("company") or "",
                    "location": item.get("location") or "Remote",
                    "work_type": item.get("job_type") or "Remote",
                    "salary": item.get("salary") or "",
                    "source": source,
                    "url": item.get("url") or item.get("job_url") or "",
                    "description": description[:12000],
                    "posted_at": item.get("created_at") or item.get("publication_date") or ""
                }
                if job["title"] and job["url"] and insert_job(conn, job):
                    added += 1
        except Exception as exc:
            errors.append(f"{source}: {str(exc)[:180]}")
    conn.commit()
    conn.close()
    return {"added": added, "errors": errors, "message": "Public-source search complete. Verify every listing on its original page."}


@app.post("/api/drafts/{job_id}")
def create_draft(job_id: int, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Job not found")
    job = dict(row)
    letter = f"""Dear Hiring Team,

I am interested in the {job['title']} opportunity{(' at ' + job['company']) if job['company'] else ''}. I have BSc and MSc degrees in Computer Science & Engineering from Khulna University of Engineering and Technology (KUET), along with professional experience as an Assistant Programmer, Network Engineer and System Analyst.

My practical experience includes WordPress and website maintenance, Elementor and WooCommerce, PHP, JavaScript, Linux and web-server administration, DNS, email and FTP services, networking, infrastructure troubleshooting and automation systems. I focus on dependable delivery, clear communication and careful technical problem-solving.

I would welcome the opportunity to discuss how my experience aligns with your requirements.

Kind regards,
Prodip Kumer Das"""
    proposal = f"""Hello,

I reviewed your {job['title']} opportunity and would be glad to help. My background combines WordPress development and maintenance with broader IT infrastructure experience, including Linux/web servers, DNS, networking and technical troubleshooting.

I hold BSc and MSc degrees in Computer Science & Engineering from KUET and have worked as an Assistant Programmer, Network Engineer and System Analyst. I value clear communication, practical solutions and reliable ongoing support.

I would be happy to discuss the scope, priorities and expected outcomes.

Best regards,
Prodip Kumer Das"""
    cursor = conn.execute(
        "INSERT INTO drafts(job_id,cover_letter,proposal,status,submission_status) VALUES(?,?,?,'needs_review','not_submitted')",
        (job_id, letter, proposal)
    )
    conn.commit()
    result = draft_row(conn, cursor.lastrowid)
    conn.close()
    return result


@app.get("/api/drafts")
def drafts(_=Depends(require_auth)):
    conn = db()
    rows = conn.execute("""
        SELECT drafts.*, jobs.title, jobs.company, jobs.url, jobs.location, jobs.salary, jobs.source
        FROM drafts JOIN jobs ON jobs.id=drafts.job_id
        ORDER BY drafts.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.put("/api/drafts/{draft_id}")
def update_draft(draft_id: int, data: DraftEdit, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Draft not found")
    if row["status"] == "submitted":
        conn.close()
        raise HTTPException(409, "A submitted application draft cannot be edited.")
    conn.execute("""
        UPDATE drafts SET cover_letter=?, proposal=?, status='needs_review',
        approved_at=NULL, submission_method=NULL, submission_status='not_submitted',
        last_submission_note=NULL WHERE id=?
    """, (data.cover_letter, data.proposal, draft_id))
    conn.commit()
    result = draft_row(conn, draft_id)
    conn.close()
    return result


@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT status FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Draft not found")
    if row["status"] == "submitted":
        conn.close()
        raise HTTPException(409, "This application is already marked submitted.")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE drafts SET status='approved', approved_at=?, submission_status='ready'
        WHERE id=?
    """, (now, draft_id))
    conn.commit()
    result = draft_row(conn, draft_id)
    conn.close()
    result["message"] = "Draft approved by user. No application has been submitted."
    return result


@app.post("/api/drafts/{draft_id}/submission")
def prepare_submission(draft_id: int, choice: SubmissionChoice, _=Depends(require_auth)):
    if not choice.confirmed:
        raise HTTPException(400, "Explicit user confirmation is required.")
    if choice.method not in {"manual", "authorized_integration"}:
        raise HTTPException(400, "Choose manual or authorized_integration.")
    conn = db()
    row = draft_row(conn, draft_id)
    if not row:
        conn.close()
        raise HTTPException(404, "Draft not found")
    if row["status"] != "approved":
        conn.close()
        raise HTTPException(409, "Review and approve this exact draft before proceeding.")
    parsed = urlparse(row["url"] or "")
    if parsed.scheme != "https" or not parsed.netloc:
        conn.close()
        raise HTTPException(400, "The original listing does not have a valid HTTPS URL.")
    if choice.method == "authorized_integration":
        # Deliberately fail closed until a supported provider integration is configured.
        conn.execute(
            "UPDATE drafts SET submission_method=?, submission_status='integration_unavailable', last_submission_note=? WHERE id=?",
            ("authorized_integration", "No authorized submission provider is configured. Nothing was submitted.", draft_id)
        )
        conn.commit()
        conn.close()
        raise HTTPException(501, "No authorized platform submission integration is configured. Nothing was submitted. Use manual submission.")
    conn.execute(
        "UPDATE drafts SET submission_method='manual', submission_status='manual_page_opened', last_submission_note=? WHERE id=?",
        ("Original application page opened for you to submit manually. JobsAuto has not submitted anything.", draft_id)
    )
    conn.commit()
    result = draft_row(conn, draft_id)
    conn.close()
    result["message"] = "Open the original listing and submit there yourself. JobsAuto has not submitted anything."
    return result


@app.post("/api/drafts/{draft_id}/mark-submitted")
def mark_submitted(draft_id: int, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT status, submission_method FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Draft not found")
    if row["status"] != "approved" or row["submission_method"] != "manual":
        conn.close()
        raise HTTPException(409, "Only an approved draft opened through manual submission can be marked submitted.")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE drafts SET status='submitted', submission_status='user_confirmed_submitted',
        submitted_at=?, last_submission_note=? WHERE id=?
    """, (now, "User confirmed that they submitted the application on the original platform.", draft_id))
    conn.commit()
    result = draft_row(conn, draft_id)
    conn.close()
    result["message"] = "Submission recorded based on your confirmation. JobsAuto did not submit it."
    return result


OFFICIAL_PORTALS = {
    "jobs": [
        {"name": "EURAXESS Jobs", "url": "https://euraxess.ec.europa.eu/jobs", "scope": "European research and academic vacancies; check each vacancy's work-permit and nationality rules."},
        {"name": "EURES", "url": "https://eures.europa.eu/index_en", "scope": "European vacancies; non-EU work authorization varies by employer and country."},
        {"name": "UN Careers", "url": "https://careers.un.org/", "scope": "International organization vacancies; nationality and residency requirements are vacancy-specific."},
        {"name": "ReliefWeb Jobs", "url": "https://reliefweb.int/jobs", "scope": "Humanitarian and development roles; verify national eligibility and duty-station rules."},
        {"name": "Canonical Careers", "url": "https://canonical.com/careers", "scope": "Technology roles; remote-country eligibility is role-specific."},
        {"name": "Wikimedia Careers", "url": "https://wikimediafoundation.org/about/jobs/", "scope": "Technology and global remote roles; verify country payroll eligibility."},
        {"name": "Wellfound Jobs", "url": "https://wellfound.com/jobs", "scope": "Startup vacancies; verify employer sponsorship and location restrictions."},
        {"name": "Make it in Germany – Job Listings", "url": "https://www.make-it-in-germany.com/en/working-in-germany/job-listings", "scope": "German Federal Government portal. Its listed employers have agreed to receive applications from foreign skilled workers; verify each vacancy deadline, qualifications and visa route."},
        {"name": "Germany Federal Employment Agency Job Search", "url": "https://www.arbeitsagentur.de/jobsuche/", "scope": "Official German public employment service vacancies; many listings are German-language and not all employers sponsor or accept applicants abroad."},
        {"name": "Canada Job Bank – Foreign Candidates", "url": "https://www.jobbank.gc.ca/findajob/foreign-candidates", "scope": "Official Canadian government search for employers recruiting candidates from outside Canada. Apply only to postings marked open to international candidates."},
        {"name": "Canada Job Bank – Temporary Foreign Workers", "url": "https://www.jobbank.gc.ca/temporary-foreign-workers", "scope": "Official listings from employers who have obtained or applied for an LMIA; confirm current status and work-permit requirements."}
    ],
    "scholarships": [
        {"name": "DAAD – Scholarships and Research Grants", "url": "https://www.daad.de/en/studying-in-germany/scholarships/", "scope": "Includes research stays and doctoral funding; Bangladesh-specific calls and current-enrolment rules vary."},
        {"name": "DAAD India – Scholarships for/During PhD", "url": "https://www.daad.in/en/study-research-in-germany/daad-verticals-in-south-asia/daad-scholarships-to-and-from-germany/scholarships-for-germany/", "scope": "Includes research stays and cotutelle routes for enrolled PhD candidates; verify Bangladesh eligibility and home-institution conditions."},
        {"name": "EURAXESS Funding & Jobs", "url": "https://euraxess.ec.europa.eu/", "scope": "Research funding, mobility and academic opportunities; check host and nationality rules."},
        {"name": "Bangladesh UGC International Scholarships", "url": "https://ugc.gov.bd/service-details/scholarshipfellowship", "scope": "Official Bangladesh scholarship/fellowship notices; many calls are restricted to university teachers or specific cohorts."},
        {"name": "Chandigarh University Research & PhD", "url": "https://www.cuchd.in/", "scope": "Check current-scholar eligibility with the university research office; admission awards may not apply to enrolled scholars."},
        {"name": "Research Professional / Grants.gov", "url": "https://www.grants.gov/", "scope": "US federal grant opportunities; many awards are institution-led and not individual student scholarships."}
    ],
    "migration_pathways": [
        {"name": "Germany – Make it in Germany Quick-Check", "url": "https://www.make-it-in-germany.com/en/visa-recognition/quick-check", "scope": "Official federal portal to compare work, study, research and job-search routes for skilled professionals from outside the EU."},
        {"name": "Germany – Opportunity Card (Chancenkarte)", "url": "https://www.make-it-in-germany.com/en/visa-recognition/opportunity-card/job-search", "scope": "Job-search residence route for eligible non-EU applicants. Requires a recognised qualification or points-route eligibility and proof of sufficient funds; it is not a job offer or guaranteed visa."},
        {"name": "Germany – EU Blue Card", "url": "https://www.make-it-in-germany.com/en/visa-recognition/visa-types/eu-blue-card", "scope": "For qualified applicants with a qualifying German job offer and salary threshold. Check the current annual threshold, degree comparability and shortage-occupation rules."},
        {"name": "Germany – Skilled Worker / Research / Experienced Professional Visas", "url": "https://www.make-it-in-germany.com/en/visa-recognition/visa-types", "scope": "Official overview of qualified-professional, experienced-professional and research visas; research route generally needs a hosting agreement or employment contract."},
        {"name": "Canada – Explore Immigration Programs (IRCC)", "url": "https://ircc.canada.ca/explore-programs/index.asp", "scope": "Official program finder for economic immigration and regional routes. Eligibility depends on language tests, education assessment, work history, age, funds and program criteria."},
        {"name": "Canada – Express Entry / Federal Skilled Worker", "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry/who-can-apply.html", "scope": "Potential permanent-residence route for skilled workers with qualifying foreign work experience. A Canadian job offer is not generally required for Federal Skilled Worker eligibility; language testing and an ECA are important."},
        {"name": "Canada – Provincial Nominee Program (PNP)", "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/provincial-nominees.html", "scope": "Province-specific nomination routes. Some streams require a job offer, local ties or occupation criteria; requirements vary by province and stream."},
        {"name": "Canada – Atlantic Immigration Program", "url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/atlantic-immigration.html", "scope": "Employer-led route requiring a job offer from a designated employer in an Atlantic province and other program requirements."},
        {"name": "Canada – Job Bank Foreign Candidate Guidance", "url": "https://www.jobbank.gc.ca/findajob/foreign-candidates", "scope": "Job search route for candidates outside Canada. Filter for employers recruiting international candidates; a job listing alone does not grant a work permit."},
        {"name": "Netherlands – Highly Skilled Migrant (IND)", "url": "https://ind.nl/en/residence-permits/work/highly-skilled-migrant", "scope": "Employer-sponsored residence route. The employer generally must be an IND-recognised sponsor and salary criteria apply."},
        {"name": "United Kingdom – Skilled Worker Visa", "url": "https://www.gov.uk/skilled-worker-visa", "scope": "Requires an eligible job with a Home Office-approved sponsor, a certificate of sponsorship and applicable salary/occupation requirements."},
        {"name": "Australia – SkillSelect", "url": "https://immi.homeaffairs.gov.au/visas/working-in-australia/skillselect", "scope": "Expression-of-interest system for selected skilled visas. Occupation, skills assessment, points, age and English requirements apply."},
        {"name": "Australia – Employer Sponsored Skills in Demand Visa", "url": "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/skills-in-demand-visa-subclass-482", "scope": "Employer-sponsored temporary skilled work route; requires an eligible sponsoring employer, occupation and visa criteria."}
    ]
}


DISCOVERY_QUERIES = {
    "jobs": [
        'site:make-it-in-germany.com/en/working-in-germany/job-listings IT software developer system administrator',
        'site:arbeitsagentur.de/jobsuche IT administrator software developer international applicants Germany',
        'site:jobbank.gc.ca/jobsearch/jobsearch foreign candidates software developer IT administrator Canada',
        'site:euraxess.ec.europa.eu/jobs computer science artificial intelligence research engineer',
        'site:careers.un.org information technology data scientist cybersecurity',
        'site:gov.uk/find-a-job software developer visa sponsorship',
        'site:jobsandskills.gov.au technology ICT jobs Australia skilled'
    ],
    "scholarships": [
        'site:daad.de scholarship doctoral research grant Bangladesh computer science',
        'site:euraxess.ec.europa.eu/funding computer science doctoral research fellowship international',
        'site:ugc.gov.bd scholarship fellowship PhD Bangladesh international',
        'site:cuchd.in PhD fellowship research scholarship Chandigarh University',
        'site:mitacs.ca research awards international graduate students computer science',
        'site:research.gov grants doctoral research computer science international',
        'PhD research funding artificial intelligence machine learning data privacy weather data international students'
    ]
}


def discover_search_results(category):
    """Return indexed discovery leads. These are never treated as verified vacancies/calls."""
    conn = db()
    added, found, errors = 0, 0, []
    for query in DISCOVERY_QUERIES[category]:
        rss_url = "https://news.google.com/rss/search?" + urlencode({"q": query, "hl": "en", "gl": "US", "ceid": "US:en"})
        try:
            response = requests.get(rss_url, timeout=18, headers={"User-Agent": "JobsAuto/1.0 (opportunity discovery)"})
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall(".//item")[:12]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                published = (item.findtext("pubDate") or "").strip()
                description = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
                description = re.sub(r"\s+", " ", description).strip()[:1200]
                source_el = item.find("source")
                source_name = (source_el.text or "Search index") if source_el is not None else "Search index"
                source_url = source_el.attrib.get("url", "") if source_el is not None else ""
                if not title or not valid_https(link):
                    continue
                found += 1
                cur = conn.execute("""INSERT OR IGNORE INTO discovery_leads
                    (category,title,result_url,source_name,source_url,published_at,search_query,summary)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (category, title, link, source_name, source_url, published, query, description))
                added += max(cur.rowcount, 0)
        except Exception as exc:
            errors.append(f"{query[:65]}: {str(exc)[:140]}")
    conn.commit()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM discovery_leads WHERE category=? ORDER BY discovered_at DESC, published_at DESC LIMIT 100", (category,)
    ).fetchall()]
    conn.close()
    return {"category": category, "added": added, "found": len(rows), "leads": rows,
            "errors": errors,
            "message": "Discovery search complete. Search-index results are leads only; open the official provider page and verify deadline, Bangladesh eligibility and exact application URL before adding a verified record."}


@app.post("/api/discovery/jobs")
def discover_jobs(_=Depends(require_auth)):
    return discover_search_results("jobs")


@app.post("/api/discovery/scholarships")
def discover_scholarships(_=Depends(require_auth)):
    return discover_search_results("scholarships")


@app.get("/api/discovery/{category}")
def list_discovery_leads(category: str, _=Depends(require_auth)):
    if category not in DISCOVERY_QUERIES:
        raise HTTPException(404, "Unknown discovery category")
    conn = db()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM discovery_leads WHERE category=? ORDER BY discovered_at DESC LIMIT 100", (category,)
    ).fetchall()]
    conn.close()
    return rows


@app.get("/api/portals")
def portals(_=Depends(require_auth)):
    return OFFICIAL_PORTALS


@app.get("/api/opportunities")
def list_opportunities(eligible_only: bool = True, _=Depends(require_auth)):
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM opportunities ORDER BY deadline ASC, created_at DESC").fetchall()]
    conn.close()
    if eligible_only:
        rows = [r for r in rows if eligible_record(r)]
    return rows


@app.post("/api/opportunities")
def add_opportunity(item: OpportunityIn, _=Depends(require_auth)):
    data = item.model_dump()
    validate_record_urls(data)
    if data["verification_status"] == "verified" and data["bangladesh_eligibility"] != "yes":
        raise HTTPException(400, "Bangladeshi applicant eligibility must be explicitly confirmed.")
    conn = db()
    fields = list(data.keys())
    conn.execute(f"INSERT INTO opportunities ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(official_url) DO UPDATE SET " + ",".join(f"{f}=excluded.{f}" for f in fields if f != "official_url"), [data[f] for f in fields])
    if data["verification_status"] == "verified":
        conn.execute("UPDATE opportunities SET verified_at=? WHERE official_url=?", (datetime.now(timezone.utc).isoformat(), data["official_url"]))
    conn.commit()
    row = conn.execute("SELECT * FROM opportunities WHERE official_url=?", (data["official_url"],)).fetchone()
    conn.close()
    return dict(row)


@app.get("/api/scholarships")
def list_scholarships(eligible_only: bool = True, _=Depends(require_auth)):
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM scholarships ORDER BY deadline ASC, created_at DESC").fetchall()]
    conn.close()
    if eligible_only:
        rows = [r for r in rows if eligible_record(r, require_current_phd=True)]
    return rows


@app.post("/api/scholarships")
def add_scholarship(item: ScholarshipIn, _=Depends(require_auth)):
    data = item.model_dump()
    validate_record_urls(data)
    if data.get("professor_profile_url") and not valid_https(data["professor_profile_url"]):
        raise HTTPException(400, "Professor profile must be HTTPS.")
    if data["verification_status"] == "verified" and data["bangladesh_eligibility"] != "yes":
        raise HTTPException(400, "Bangladeshi applicant eligibility must be explicitly confirmed.")
    if data["contact_verification"] == "verified":
        if not data.get("professor_name") or not data.get("professor_email") or not data.get("professor_profile_url"):
            raise HTTPException(400, "Verified professor contact requires name, institutional email and official profile URL.")
        if not data.get("institution_url") or not valid_https(data["institution_url"]):
            raise HTTPException(400, "Verified professor contact requires the official institution URL.")
    conn = db()
    fields = list(data.keys())
    conn.execute(f"INSERT INTO scholarships ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)}) ON CONFLICT(official_url) DO UPDATE SET " + ",".join(f"{f}=excluded.{f}" for f in fields if f != "official_url"), [data[f] for f in fields])
    if data["verification_status"] == "verified":
        conn.execute("UPDATE scholarships SET verified_at=? WHERE official_url=?", (datetime.now(timezone.utc).isoformat(), data["official_url"]))
    conn.commit()
    row = conn.execute("SELECT * FROM scholarships WHERE official_url=?", (data["official_url"],)).fetchone()
    conn.close()
    return dict(row)


@app.get("/health")
def health():
    return {"status": "ok", "app": "JobsAuto"}
