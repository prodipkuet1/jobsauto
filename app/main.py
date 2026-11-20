import os
import sqlite3
import re
import secrets
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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

app = FastAPI(title="JobsAuto - AI Job Search Assistant", version="0.2.0")
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


@app.get("/health")
def health():
    return {"status": "ok", "app": "JobsAuto"}
