import os, sqlite3, json, re, secrets
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus
import requests
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

APP_DIR = os.path.dirname(__file__)
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
    "education": ["BSc in Computer Science & Engineering, KUET", "MSc in Computer Science & Engineering, KUET"],
    "experience": ["Assistant Programmer", "Network Engineer", "System Analyst"],
    "languages": ["English (Fluent)", "Bengali (Native)", "Hindi (Conversational)"]
}

app = FastAPI(title="JobsAuto - AI Job Search Assistant", version="0.1.0")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(APP_DIR), "static")), name="static")

def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, company TEXT,
        location TEXT, work_type TEXT, salary TEXT, source TEXT, url TEXT UNIQUE,
        description TEXT, posted_at TEXT, score INTEGER DEFAULT 0, status TEXT DEFAULT 'new',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, cover_letter TEXT,
        proposal TEXT, status TEXT DEFAULT 'needs_review', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(job_id) REFERENCES jobs(id)
    )""")
    conn.commit()
    return conn

def require_auth(authorization: Optional[str] = Header(default=None)):
    # Set ADMIN_TOKEN in Render. In local development, no token is required.
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

def score_job(title, description, location="", work_type=""):
    text = " ".join([title or "", description or ""]).lower()
    groups = {
        "wordpress": ["wordpress", "elementor", "woocommerce", "wp developer", "website maintenance"],
        "web_support": ["website support", "technical support", "web developer", "php", "javascript"],
        "infra": ["linux", "system administrator", "network engineer", "network administrator", "dns", "server administrator", "it support"],
        "automation_data": ["automation", "workflow", "data analyst", "data analysis"]
    }
    points = 0
    for words in groups.values():
        if any(w in text for w in words):
            points += 22
    if any(x in text for x in ["remote", "work from home", "anywhere"]):
        points += 8
    if any(x in (location or "").lower() for x in ["europe", "worldwide", "remote"]):
        points += 5
    if any(x in text for x in ["senior", "lead", "principal"]) and not any(x in text for x in ["junior", "entry level"]):
        points -= 5
    return max(0, min(100, points))

def insert_job(conn, item):
    score = score_job(item.get("title",""), item.get("description",""), item.get("location",""), item.get("work_type",""))
    try:
        conn.execute("""INSERT OR IGNORE INTO jobs(title,company,location,work_type,salary,source,url,description,posted_at,score)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (item.get("title",""), item.get("company",""), item.get("location",""), item.get("work_type",""),
             item.get("salary",""), item.get("source",""), item.get("url",""), item.get("description",""),
             item.get("posted_at",""), score))
        return conn.execute("SELECT changes()").fetchone()[0] == 1
    except sqlite3.Error:
        return False

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(os.path.dirname(APP_DIR), "static", "index.html"), encoding="utf-8") as f:
        return f.read()

@app.get("/api/profile")
def profile(_=Depends(require_auth)):
    return PROFILE

@app.get("/api/jobs")
def jobs(limit: int = 100, _=Depends(require_auth)):
    conn = db()
    rows = conn.execute("SELECT * FROM jobs ORDER BY score DESC, created_at DESC LIMIT ?", (min(limit,300),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

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
    """Fetches public listings from public APIs. Add API credentials for commercial providers separately."""
    conn = db()
    added, errors = 0, []
    sources = [
        ("Arbeitnow", "https://www.arbeitnow.com/api/job-board-api"),
        ("Remotive", "https://remotive.com/api/remote-jobs?limit=50")
    ]
    for source, url in sources:
        try:
            response = requests.get(url, timeout=20, headers={"User-Agent":"JobsAuto/0.1"})
            response.raise_for_status()
            payload = response.json()
            items = payload.get("data", []) if source == "Arbeitnow" else payload.get("jobs", [])
            for j in items:
                title = j.get("title", "")
                description = re.sub("<[^>]+>", " ", j.get("description", "") or "")
                item = {
                    "title": title, "company": j.get("company_name") or j.get("company") or "",
                    "location": j.get("location") or "Remote", "work_type": j.get("job_type") or "Remote",
                    "salary": j.get("salary") or "", "source": source,
                    "url": j.get("url") or j.get("job_url") or "",
                    "description": description[:12000], "posted_at": j.get("created_at") or j.get("publication_date") or ""
                }
                if item["title"] and item["url"] and insert_job(conn, item):
                    added += 1
        except Exception as e:
            errors.append(f"{source}: {str(e)[:180]}")
    conn.commit()
    conn.close()
    return {"added": added, "errors": errors, "message": "Public-source search complete. Listings may be incomplete; always verify on the original job page."}

@app.post("/api/drafts/{job_id}")
def create_draft(job_id: int, _=Depends(require_auth)):
    conn = db()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Job not found")
    job = dict(row)
    letter = f"""Dear Hiring Team,

I am interested in the {job['title']} opportunity{(' at ' + job['company']) if job['company'] else ''}. I have a BSc and MSc in Computer Science & Engineering from Khulna University of Engineering and Technology (KUET), along with professional experience as an Assistant Programmer, Network Engineer and System Analyst.

My practical experience includes WordPress and website maintenance, Elementor and WooCommerce, PHP, JavaScript, Linux and web-server administration, DNS, email and FTP services, networking, infrastructure troubleshooting and automation systems. I focus on dependable delivery, clear communication and careful technical problem-solving.

I would welcome the opportunity to discuss how my experience aligns with your requirements. I can provide further details and relevant examples upon request.

Kind regards,
Prodip Kumer Das
"""
    proposal = f"""Hello,

I reviewed your {job['title']} opportunity and would be glad to help. My background combines WordPress development and maintenance with broader IT infrastructure experience, including Linux/web servers, DNS, networking and technical troubleshooting.

I hold BSc and MSc degrees in Computer Science & Engineering from KUET and have worked as an Assistant Programmer, Network Engineer and System Analyst. I value clear communication, practical solutions and reliable ongoing support.

I would be happy to discuss the scope, priorities and expected outcomes.

Best regards,
Prodip Kumer Das
"""
    cur = conn.execute("INSERT INTO drafts(job_id,cover_letter,proposal) VALUES(?,?,?)", (job_id, letter, proposal))
    conn.commit()
    draft = conn.execute("SELECT * FROM drafts WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return dict(draft)

@app.get("/api/drafts")
def drafts(_=Depends(require_auth)):
    conn = db()
    rows = conn.execute("""SELECT drafts.*, jobs.title, jobs.company, jobs.url FROM drafts
        JOIN jobs ON jobs.id=drafts.job_id ORDER BY drafts.created_at DESC""").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/drafts/{draft_id}/approve")
def approve_draft(draft_id: int, _=Depends(require_auth)):
    # Approval means the user has reviewed the draft; it NEVER submits the application.
    conn = db()
    cur = conn.execute("UPDATE drafts SET status='approved_for_manual_submission' WHERE id=?", (draft_id,))
    conn.commit()
    changed = cur.rowcount
    conn.close()
    if not changed:
        raise HTTPException(404, "Draft not found")
    return {"status":"approved_for_manual_submission", "message":"Draft marked approved. No application was submitted."}

@app.get("/health")
def health():
    return {"status":"ok", "app":"JobsAuto"}
