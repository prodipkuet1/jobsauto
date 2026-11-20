import os
import sqlite3
import re
import secrets
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse, urlencode
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

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


SCHOLARSHIP_PROFILE = {
    "nationality": "Bangladeshi",
    "current_country": "India",
    "university": "Chandigarh University",
    "enrollment_status": "Currently enrolled",
    "study_mode": "Full-time",
    "degree": "PhD",
    "discipline": "Computer Science and Engineering",
    "research_interests": [
        "Artificial Intelligence", "Machine Learning", "Deep Learning",
        "Cybersecurity", "Computer Networks", "Cloud Computing",
        "Data Science", "Data Privacy", "Weather Data", "Weather Forecasting",
        "Climate Data Analytics", "Privacy-Preserving Machine Learning",
        "Spatiotemporal Data Analysis"
    ],
    "funding_types": [
        "PhD Fellowship", "Research Grant", "Doctoral Scholarship",
        "Research Assistantship", "Research Mobility Grant",
        "Conference Grant", "Publication Grant"
    ],
    "matching_policy": (
        "Prioritize funding that accepts currently enrolled international PhD "
        "researchers. Do not assume eligibility from a title or snippet."
    )
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

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scholarships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            provider TEXT DEFAULT '',
            country TEXT DEFAULT '',
            funding TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            source TEXT DEFAULT '',
            url TEXT UNIQUE,
            summary TEXT DEFAULT '',
            research_match INTEGER DEFAULT 0,
            eligibility_status TEXT DEFAULT 'needs_verification',
            ielts_status TEXT DEFAULT 'not_stated',
            recommendation_status TEXT DEFAULT 'not_stated',
            enrollment_status TEXT DEFAULT 'unclear',
            score INTEGER DEFAULT 0,
            verification_status TEXT DEFAULT 'unverified',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scholarship_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scholarship_id INTEGER NOT NULL,
            motivation_letter TEXT DEFAULT '',
            research_statement TEXT DEFAULT '',
            status TEXT DEFAULT 'needs_review',
            approved_at TEXT,
            submission_method TEXT,
            submission_status TEXT DEFAULT 'not_submitted',
            submitted_at TEXT,
            last_submission_note TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(scholarship_id) REFERENCES scholarships(id)
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



class ScholarshipIn(BaseModel):
    title: str = Field(min_length=2)
    provider: str = ""
    country: str = ""
    funding: str = ""
    deadline: str = ""
    source: str = "Manually added"
    url: str
    summary: str = ""


class ScholarshipDraftEdit(BaseModel):
    motivation_letter: str = Field(min_length=1)
    research_statement: str = Field(min_length=1)


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


SCHOLARSHIP_QUERIES = [
    '"currently enrolled" PhD fellowship international students computer science',
    'Bangladeshi PhD research fellowship international research grant computer science',
    'PhD scholarship without IELTS without recommendation letter computer science',
    'PhD scholarship without IELTS with recommendation letter computer science',
    'PhD scholarship with IELTS without recommendation letter computer science',
    'PhD scholarship with IELTS with recommendation letter computer science',
    'AI machine learning deep learning PhD research grant international enrolled scholar',
    'weather data climate AI machine learning research grant PhD',
    'cybersecurity data privacy research fellowship PhD international',
    'computer networks cloud computing data science doctoral mobility research grant',
    'India research fellowship international PhD scholars computer science',
    'Chandigarh University PhD research fellowship existing scholars'
]


def scholarship_score(title, summary):
    text = f"{title or ''} {summary or ''}".lower()
    research_terms = [
        "artificial intelligence", "machine learning", "deep learning", "cybersecurity",
        "cyber security", "computer science", "computer network", "cloud computing",
        "data science", "data privacy", "privacy-preserving", "weather", "climate",
        "forecasting", "spatiotemporal", "meteorological"
    ]
    matched = sum(1 for term in research_terms if term in text)
    research = min(20, matched * 4)
    enrolled = 30 if any(x in text for x in ["currently enrolled", "already enrolled", "continuing phd", "doctoral researcher", "research scholar"]) else 10
    international = 10 if any(x in text for x in ["international", "foreign national", "bangladesh", "global"]) else 5
    funding = 15 if any(x in text for x in ["fully funded", "funded", "fellowship", "grant", "stipend", "scholarship"]) else 5
    docs = 10
    deadline = 5 if any(x in text for x in ["2026", "2027", "rolling", "ongoing"]) else 2
    return min(100, research + enrolled + international + funding + docs + deadline), research


def classify_scholarship(title, summary):
    text = f"{title or ''} {summary or ''}".lower()
    if any(x in text for x in ["ielts required", "must have ielts", "mandatory ielts", "minimum ielts score"]):
        ielts = "required_claimed"
    elif any(x in text for x in ["ielts not required", "without ielts", "ielts waiver", "medium of instruction", "moi certificate accepted"]):
        ielts = "not_required_or_waiver_claimed"
    else:
        ielts = "not_stated"
    if any(x in text for x in ["recommendation letter required", "two recommendation letters", "letters of recommendation required", "reference letter required"]):
        recommendation = "required_claimed"
    elif any(x in text for x in ["no recommendation letter", "without recommendation letter", "recommendation letter not required"]):
        recommendation = "not_required_claimed"
    else:
        recommendation = "not_stated"
    if any(x in text for x in ["currently enrolled", "already enrolled", "continuing phd", "doctoral researcher", "research scholar"]):
        enrollment = "potentially_supports_current_scholars"
    elif any(x in text for x in ["new admission", "admission to", "incoming phd", "prospective students", "apply for admission"]):
        enrollment = "possibly_new_admission_only"
    else:
        enrollment = "unclear"
    if any(x in text for x in ["bangladeshi citizens", "citizens of bangladesh", "bangladesh nationals"]):
        eligibility = "nationality_match_claimed_verify"
    elif any(x in text for x in ["international students", "international applicants", "foreign nationals", "all nationalities"]):
        eligibility = "international_eligibility_claimed_verify"
    else:
        eligibility = "needs_verification"
    return ielts, recommendation, enrollment, eligibility


def document_category(ielts_status, recommendation_status):
    ielts_map = {
        "required_claimed": "required",
        "not_required_or_waiver_claimed": "not_required_claimed"
    }
    rec_map = {
        "required_claimed": "required",
        "not_required_claimed": "not_required_claimed"
    }
    ielts = ielts_map.get(ielts_status)
    recommendation = rec_map.get(recommendation_status)
    if not ielts or not recommendation:
        return "Unverified — one or both requirements not stated"
    if ielts == "not_required_claimed" and recommendation == "not_required_claimed":
        return "A — IELTS not required / no recommendation letter claimed"
    if ielts == "not_required_claimed" and recommendation == "required":
        return "B — IELTS not required / recommendation letter claimed"
    if ielts == "required" and recommendation == "not_required_claimed":
        return "C — IELTS required / no recommendation letter claimed"
    return "D — IELTS required / recommendation letter claimed"


def scholarship_row(conn, scholarship_id):
    row = conn.execute("""
        SELECT * FROM scholarships WHERE id=?
    """, (scholarship_id,)).fetchone()
    return dict(row) if row else None


def scholarship_draft_row(conn, draft_id):
    row = conn.execute("""
        SELECT scholarship_drafts.*, scholarships.title, scholarships.provider,
               scholarships.country, scholarships.funding, scholarships.deadline,
               scholarships.url, scholarships.eligibility_status,
               scholarships.ielts_status, scholarships.recommendation_status
        FROM scholarship_drafts
        JOIN scholarships ON scholarships.id=scholarship_drafts.scholarship_id
        WHERE scholarship_drafts.id=?
    """, (draft_id,)).fetchone()
    return dict(row) if row else None


def insert_scholarship(conn, item):
    ielts, recommendation, enrollment, eligibility = classify_scholarship(
        item.get("title", ""), item.get("summary", "")
    )
    score, research_match = scholarship_score(item.get("title", ""), item.get("summary", ""))
    conn.execute("""
        INSERT OR IGNORE INTO scholarships
        (title,provider,country,funding,deadline,source,url,summary,research_match,
         eligibility_status,ielts_status,recommendation_status,enrollment_status,score)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        item.get("title", ""), item.get("provider", ""), item.get("country", ""),
        item.get("funding", ""), item.get("deadline", ""), item.get("source", ""),
        item.get("url", ""), item.get("summary", "")[:8000], research_match,
        eligibility, ielts, recommendation, enrollment, score
    ))
    return conn.execute("SELECT changes()").fetchone()[0] == 1



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


@app.get("/api/scholarships/profile")
def scholarship_profile(_=Depends(require_auth)):
    return SCHOLARSHIP_PROFILE


@app.get("/api/scholarships")
def scholarships(limit: int = 150, _=Depends(require_auth)):
    conn = db()
    rows = conn.execute("""
        SELECT * FROM scholarships
        ORDER BY score DESC, created_at DESC LIMIT ?
    """, (min(max(limit, 1), 300),)).fetchall()
    conn.close()
    results = [dict(row) for row in rows]
    for item in results:
        item["document_category"] = document_category(item.get("ielts_status"), item.get("recommendation_status"))
    return results


@app.post("/api/scholarships/search")
def search_scholarships(_=Depends(require_auth)):
    conn = db()
    added, errors, checked = 0, [], 0
    for query in SCHOLARSHIP_QUERIES:
        rss_url = "https://news.google.com/rss/search?" + urlencode({
            "q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"
        })
        try:
            response = requests.get(
                rss_url, timeout=18,
                headers={"User-Agent": "JobsAuto/0.3 scholarship-discovery"}
            )
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                url = (item.findtext("link") or "").strip()
                summary_raw = item.findtext("description") or ""
                summary = re.sub(r"<[^>]+>", " ", summary_raw)
                summary = re.sub(r"\\s+", " ", summary).strip()
                publisher = item.findtext("source") or "Publisher not identified"
                pub_date = item.findtext("pubDate") or ""
                if not title or not url:
                    continue
                checked += 1
                added += int(insert_scholarship(conn, {
                    "title": title, "provider": publisher, "country": "",
                    "funding": "", "deadline": pub_date, "source": "Google News RSS",
                    "url": url, "summary": summary
                }))
        except Exception as exc:
            errors.append(f"{query[:55]}: {str(exc)[:140]}")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM scholarships").fetchone()[0]
    conn.close()
    return {
        "added": added, "checked": checked, "total": total, "errors": errors,
        "message": "Discovery search complete. Results are leads, not verified awards. Open the publisher's official page and verify eligibility, deadline and documents."
    }


@app.post("/api/scholarships")
def add_scholarship(item: ScholarshipIn, _=Depends(require_auth)):
    parsed = urlparse(item.url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(400, "Scholarship URL must be a valid HTTPS link.")
    conn = db()
    inserted = insert_scholarship(conn, item.model_dump())
    conn.commit()
    row = conn.execute("SELECT * FROM scholarships WHERE url=?", (item.url,)).fetchone()
    conn.close()
    return {"inserted": inserted, "scholarship": dict(row) if row else None}


@app.get("/api/scholarship-drafts")
def scholarship_drafts(_=Depends(require_auth)):
    conn = db()
    rows = conn.execute("""
        SELECT scholarship_drafts.*, scholarships.title, scholarships.provider,
               scholarships.country, scholarships.funding, scholarships.deadline,
               scholarships.url, scholarships.eligibility_status
        FROM scholarship_drafts JOIN scholarships
        ON scholarships.id=scholarship_drafts.scholarship_id
        ORDER BY scholarship_drafts.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post("/api/scholarship-drafts/{scholarship_id}")
def create_scholarship_draft(scholarship_id: int, _=Depends(require_auth)):
    conn = db()
    item = scholarship_row(conn, scholarship_id)
    if not item:
        conn.close()
        raise HTTPException(404, "Scholarship not found")
    motivation = f"""Dear Scholarship Selection Committee,

I am applying for the {item['title']} opportunity. I am a Bangladeshi full-time PhD research scholar in Computer Science and Engineering at Chandigarh University, India.

My research interests include Artificial Intelligence, Machine Learning, Deep Learning, Cybersecurity, Computer Networks, Cloud Computing, Data Science, Data Privacy and Weather Data. I am particularly interested in interdisciplinary research involving AI-driven weather analysis, privacy-preserving data science and secure computing systems.

I would be grateful for consideration under the published eligibility and funding conditions. I will provide verified academic records and supporting documents as required.

Sincerely,
Prodip Kumer Das"""
    research = """Proposed research-interest statement

Current programme: Full-time PhD in Computer Science and Engineering, Chandigarh University, India.
Nationality: Bangladeshi.

Research-interest areas:
- Artificial Intelligence, Machine Learning and Deep Learning
- Cybersecurity, Computer Networks and Cloud Computing
- Data Science and Data Privacy
- Weather data analysis, forecasting and climate-related analytics

Potential interdisciplinary directions include privacy-preserving machine learning for environmental datasets, spatiotemporal weather-data modelling, AI-assisted forecasting, and secure cloud-based data platforms.

This is a starting draft, not a confirmed thesis title or claim of completed research. Replace it with your approved PhD topic, research objectives, methodology, progress and publications before submitting."""
    cursor = conn.execute("""
        INSERT INTO scholarship_drafts
        (scholarship_id,motivation_letter,research_statement,status,submission_status)
        VALUES(?,?,?,'needs_review','not_submitted')
    """, (scholarship_id, motivation, research))
    conn.commit()
    result = scholarship_draft_row(conn, cursor.lastrowid)
    conn.close()
    if result:
        result["document_category"] = document_category(result.get("ielts_status"), result.get("recommendation_status"))
    return result


@app.put("/api/scholarship-drafts/{draft_id}")
def update_scholarship_draft(draft_id: int, data: ScholarshipDraftEdit, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT status FROM scholarship_drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Scholarship draft not found")
    if row["status"] == "submitted":
        conn.close()
        raise HTTPException(409, "A submitted scholarship application cannot be edited.")
    conn.execute("""
        UPDATE scholarship_drafts SET motivation_letter=?, research_statement=?,
        status='needs_review', approved_at=NULL, submission_method=NULL,
        submission_status='not_submitted', last_submission_note=NULL WHERE id=?
    """, (data.motivation_letter, data.research_statement, draft_id))
    conn.commit()
    result = scholarship_draft_row(conn, draft_id)
    conn.close()
    return result


@app.post("/api/scholarship-drafts/{draft_id}/approve")
def approve_scholarship_draft(draft_id: int, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT status FROM scholarship_drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Scholarship draft not found")
    if row["status"] == "submitted":
        conn.close()
        raise HTTPException(409, "This scholarship application is already submitted.")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE scholarship_drafts SET status='approved', approved_at=?,
        submission_status='ready' WHERE id=?
    """, (now, draft_id))
    conn.commit()
    result = scholarship_draft_row(conn, draft_id)
    conn.close()
    result["message"] = "Scholarship draft approved by user. Nothing has been submitted."
    return result


@app.post("/api/scholarship-drafts/{draft_id}/submission")
def prepare_scholarship_submission(draft_id: int, choice: SubmissionChoice, _=Depends(require_auth)):
    if not choice.confirmed:
        raise HTTPException(400, "Explicit user confirmation is required.")
    if choice.method not in {"manual", "authorized_integration"}:
        raise HTTPException(400, "Choose manual or authorized_integration.")
    conn = db()
    row = scholarship_draft_row(conn, draft_id)
    if not row:
        conn.close()
        raise HTTPException(404, "Scholarship draft not found")
    if row["status"] != "approved":
        conn.close()
        raise HTTPException(409, "Review and approve this exact scholarship draft first.")
    parsed = urlparse(row["url"] or "")
    if parsed.scheme != "https" or not parsed.netloc:
        conn.close()
        raise HTTPException(400, "Scholarship listing does not have a valid HTTPS URL.")
    if choice.method == "authorized_integration":
        conn.execute("""
            UPDATE scholarship_drafts SET submission_method=?,
            submission_status='integration_unavailable',
            last_submission_note=? WHERE id=?
        """, ("authorized_integration", "No authorized scholarship submission integration is configured. Nothing was submitted.", draft_id))
        conn.commit()
        conn.close()
        raise HTTPException(501, "No authorized scholarship application integration is configured. Nothing was submitted. Use manual submission.")
    conn.execute("""
        UPDATE scholarship_drafts SET submission_method='manual',
        submission_status='manual_page_opened',
        last_submission_note=? WHERE id=?
    """, ("Original scholarship page opened for manual application. JobsAuto has not submitted anything.", draft_id))
    conn.commit()
    result = scholarship_draft_row(conn, draft_id)
    conn.close()
    result["message"] = "Open the official scholarship page and submit there yourself. JobsAuto has not submitted anything."
    return result


@app.post("/api/scholarship-drafts/{draft_id}/mark-submitted")
def mark_scholarship_submitted(draft_id: int, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("""
        SELECT status, submission_method FROM scholarship_drafts WHERE id=?
    """, (draft_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Scholarship draft not found")
    if row["status"] != "approved" or row["submission_method"] != "manual":
        conn.close()
        raise HTTPException(409, "Only an approved draft opened through manual submission can be marked submitted.")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        UPDATE scholarship_drafts SET status='submitted',
        submission_status='user_confirmed_submitted', submitted_at=?,
        last_submission_note=? WHERE id=?
    """, (now, "User confirmed submitting the scholarship application on the original platform.", draft_id))
    conn.commit()
    result = scholarship_draft_row(conn, draft_id)
    conn.close()
    result["message"] = "Submission recorded based on your confirmation. JobsAuto did not submit it."
    return result




@app.get("/health")
def health():
    return {"status": "ok", "app": "JobsAuto"}
