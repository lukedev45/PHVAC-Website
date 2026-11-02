"""
Intranet Team Tasks App — single-file MVP

Tech stack:
- FastAPI (API + server-rendered pages via Jinja2)
- SQLite (via SQLModel / SQLAlchemy)
- Tailwind (CDN) + HTMX (CDN) for simple interactivity
- Session auth (Starlette SessionMiddleware) with bcrypt password hashing

Features:
- Users (manager/member) sign in with username+password
- Tasks with title, description, due date, status, assignee
- Notes on tasks (with timestamps, author)
- Filter by assignee, status, and date
- CSV import/export (so you can move from Excel by saving as CSV)
- Audit: status/assignee/notes timestamps tracked

How to run:
1) Install deps:  
   pip install fastapi uvicorn sqlmodel jinja2 passlib[bcrypt] python-multipart itsdangerous

2) Start server:  
   uvicorn app:app --reload --host 0.0.0.0 --port 8000

3) First user: When you start, no users exist. Go to /bootstrap to create the first manager account.

"""

from __future__ import annotations
import os
import csv
import hashlib
import secrets
from datetime import datetime, date, timedelta
from typing import Optional, List
from uuid import uuid4

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext
from sqlmodel import Field, SQLModel, Session, create_engine, select, Column, Date

# Config
SECRET_KEY = os.environ.get("APP_SECRET")
if not SECRET_KEY:
    raise RuntimeError(
        "APP_SECRET is not set. It signs the session cookies, so it must be a long random value. Generate one with:\n"
        "    python -c \"import secrets; print(secrets.token_urlsafe(64))\"\n"
        "and set it in the environment before starting the app (e.g. export APP_SECRET=...)."
    )
DB_URL = os.environ.get("DB_URL", "sqlite:///./tasks.db")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})

# Models
class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    full_name: str
    role: str = Field(default="member")  # 'manager' or 'member'
    password_hash: str

class TaskStatus:
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    ISSUED_FOR_REVIEW = "issued_for_review"
    DONE = "done"

class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    image_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = Field(default="")
    due_date: Optional[date] = Field(sa_column=Column(Date, nullable=True))
    status: str = Field(default=TaskStatus.TODO, index=True)
    assignee_id: Optional[int] = Field(default=None, foreign_key="user.id")
    job_id: Optional[int] = Field(default=None, foreign_key="job.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Note(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id")
    author_id: int = Field(foreign_key="user.id")
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PasswordReset(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    token: str = Field(index=True, unique=True)
    expires_at: datetime = Field(default_factory=lambda: datetime.utcnow() + timedelta(days=1))
    used: bool = Field(default=False)


# App + Templates
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=False)

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Serve static files
app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "assets")), name="assets")

os.makedirs(os.path.join(os.path.dirname(__file__), "assets", "images", "jobs"), exist_ok=True)

# DB init
SQLModel.metadata.create_all(engine)

# Lightweight migration to add job_id to task if it doesn't exist (SQLite-safe)
with engine.connect() as conn:
    try:
        cols = conn.exec_driver_sql("PRAGMA table_info(task)").fetchall()
        names = [c[1] for c in cols]
        if "job_id" not in names:
            conn.exec_driver_sql("ALTER TABLE task ADD COLUMN job_id INTEGER NULL")
    except Exception:
        pass

# Utilities
def get_db():
    with Session(engine) as session:
        yield session

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def hash_token(token: str) -> str:
    # Reset tokens are long random values, so a fast unsalted hash is enough (unlike passwords)
    return hashlib.sha256(token.encode()).hexdigest()

def normalize_username(u: str) -> str:
    return (u or "").strip().lower()

#Auth helpers
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, uid)

def login_required(user: Optional[User]):
    if not user:
        raise HTTPException(status_code=status.HTTP_302_FOUND, detail="Redirect", headers={"Location": "/login"})

def manager_required(user: Optional[User]):
    login_required(user)
    if user.role != "manager":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers can do this")


# Routes
@app.get("/", response_class=HTMLResponse)
def root(request: Request, user: Optional[User] = Depends(get_current_user)):
    if not user:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/dashboard", status_code=302)

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "title": "Login", "current_user": None})

@app.post("/login")
def login_post(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    username_norm = normalize_username(username)
    stmt = select(User).where(User.username == username_norm)
    user = db.exec(stmt).first()
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse("/login", status_code=302)
    request.session["user_id"] = user.id
    return RedirectResponse("/dashboard", status_code=302)

@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

@app.get("/bootstrap", response_class=HTMLResponse)
def bootstrap_get(request: Request, db: Session = Depends(get_db)):
    count = db.exec(select(User)).all()
    if count:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("bootstrap.html", {"request": request, "title": "Bootstrap", "current_user": None})

@app.post("/bootstrap")
def bootstrap_post(request: Request, full_name: str = Form(...), username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    count = db.exec(select(User)).all()
    if count:
        return RedirectResponse("/login", status_code=302)
    username_norm = normalize_username(username)
    user = User(full_name=full_name, username=username_norm, password_hash=hash_password(password), role="manager")
    db.add(user)
    db.commit()
    return RedirectResponse("/login", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, assignee_id: Optional[int] = None, status: Optional[str] = None, from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    users = db.exec(select(User)).all()
    stmt = select(Task)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if from_:
        try:
            fdate = datetime.strptime(from_, "%Y-%m-%d").date()
            stmt = stmt.where(Task.due_date >= fdate)
        except:
            pass
    if to:
        try:
            tdate = datetime.strptime(to, "%Y-%m-%d").date()
            stmt = stmt.where(Task.due_date <= tdate)
        except:
            pass
    # Sort by due date (closest first), then by updated_at for tasks without due dates
    stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date.asc(), Task.updated_at.desc())
    tasks = db.exec(stmt).all()
    user_by_id = {u.id: u for u in users}
    
    today = date.today()
    return templates.TemplateResponse("dashboard.html", {"request": request, "title": "Dashboard", "current_user": user, "users": users, "tasks": tasks, "user_by_id": user_by_id, "assignee_id": assignee_id, "status_val": status, "from": from_, "to": to, "today": today})

@app.get("/tasks/new", response_class=HTMLResponse)
def task_new_get(request: Request, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    users = db.exec(select(User)).all()
    jobs = db.exec(select(Job).order_by(Job.created_at.desc())).all()
    return templates.TemplateResponse("task_new.html", {"request": request, "title": "New Task", "current_user": user, "users": users, "jobs": jobs})

@app.post("/tasks/new")
def task_new_post(request: Request, title: str = Form(...), description: str = Form(""), due_date: Optional[str] = Form(None), assignee_id: Optional[str] = Form(None), job_id: Optional[str] = Form(None), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    due = datetime.strptime(due_date, "%Y-%m-%d").date() if due_date else None
    assignee = int(assignee_id) if assignee_id else None
    job = int(job_id) if job_id else None
    t = Task(title=title, description=description, due_date=due, assignee_id=assignee, job_id=job)
    db.add(t)
    db.commit()
    return RedirectResponse(f"/tasks/{t.id}", status_code=302)

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_detail(request: Request, task_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    assignee = db.get(User, t.assignee_id) if t.assignee_id else None
    notes = db.exec(select(Note).where(Note.task_id == task_id).order_by(Note.created_at)).all()
    users = db.exec(select(User)).all()
    users_map = {u.id: u for u in users}
    return templates.TemplateResponse("task_detail.html", {"request": request, "title": t.title, "current_user": user, "task": t, "assignee": assignee, "notes": notes, "users_map": users_map})

@app.post("/tasks/{task_id}/status")
def task_status(task_id: int, status: str = Form(...), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    if status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.ISSUED_FOR_REVIEW, TaskStatus.DONE}:
        raise HTTPException(400, "Invalid status")
    t.status = status
    t.updated_at = datetime.utcnow()
    db.add(t)
    db.commit()
    return RedirectResponse(f"/tasks/{task_id}", status_code=302)

@app.post("/tasks/{task_id}/assign")
def task_assign_update(request: Request, task_id: int, assignee_id: Optional[str] = Form(None), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    if user.role != "manager":
        raise HTTPException(403, "Only managers can change task assignments")
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404, "Task not found")
    assignee = int(assignee_id) if assignee_id else None
    t.assignee_id = assignee
    t.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(f"/tasks/{task_id}", status_code=302)

@app.post("/tasks/{task_id}/delete")
def task_delete(task_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    if t.status != TaskStatus.DONE:
        raise HTTPException(400, "Only completed tasks can be deleted")
    notes = db.exec(select(Note).where(Note.task_id == task_id)).all()
    for n in notes:
        db.delete(n)
    db.delete(t)
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)

@app.post("/tasks/{task_id}/notes", response_class=HTMLResponse)
async def add_note(request: Request, task_id: int, content: str = Form(...), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    n = Note(task_id=task_id, author_id=user.id, content=content)
    t.updated_at = datetime.utcnow()
    db.add(n)
    db.add(t)
    db.commit()
    # Return just the note card (for HTMX beforeend)
    html = f'''<div class="border rounded p-2 mb-2">
      <div class="text-xs text-gray-500">{n.created_at.strftime('%Y-%m-%d %H:%M')} • {user.full_name}</div>
      <div class="text-sm whitespace-pre-line">{content}</div>
    </div>'''
    return HTMLResponse(html)

@app.get("/team", response_class=HTMLResponse)
def team_page(request: Request, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    users = db.exec(select(User)).all()
    return templates.TemplateResponse("team.html", {"request": request, "title": "Team", "current_user": user, "users": users})

@app.post("/team/new")
def team_new(full_name: str = Form(...), username: str = Form(...), password: str = Form(...), role: str = Form("member"), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    if user.role != "manager":
        raise HTTPException(403, "Only managers can add users")
    username_norm = normalize_username(username)
    exists = db.exec(select(User).where(User.username == username_norm)).first()
    if exists:
        raise HTTPException(400, "Username exists")
    u = User(full_name=full_name, username=username_norm, role=role, password_hash=hash_password(password))
    db.add(u)
    db.commit()
    return RedirectResponse("/team", status_code=302)

@app.post("/team/{user_id}/delete")
def team_delete(request: Request, user_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    if user.role != "manager":
        raise HTTPException(403, "Only managers can delete users")
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(404, "User not found")
    if target_user.id == user.id:
        raise HTTPException(400, "Cannot delete yourself")
    # Delete all tasks assigned to this user
    tasks = db.exec(select(Task).where(Task.assignee_id == user_id)).all()
    for t in tasks:
        # Delete notes for each task
        notes = db.exec(select(Note).where(Note.task_id == t.id)).all()
        for n in notes:
            db.delete(n)
        db.delete(t)
    # Delete all notes authored by this user
    notes = db.exec(select(Note).where(Note.author_id == user_id)).all()
    for n in notes:
        db.delete(n)
    db.delete(target_user)
    db.commit()
    return RedirectResponse("/team", status_code=302)

@app.post("/import")
async def import_csv(file: UploadFile = File(...), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    if not file.filename.endswith('.csv'):
        raise HTTPException(400, "Please upload a .csv file")
    content = (await file.read()).decode('utf-8', errors='ignore').splitlines()
    reader = csv.DictReader(content)
    # Expected columns: title,description,due_date(YYYY-MM-DD),status,assignee_username
    users = {u.username.lower(): u for u in db.exec(select(User)).all()}
    for row in reader:
        title = row.get('title') or 'Untitled'
        description = row.get('description') or ''
        due = row.get('due_date') or ''
        status_val = (row.get('status') or TaskStatus.TODO).lower()
        if status_val not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.ISSUED_FOR_REVIEW, TaskStatus.DONE}:
            status_val = TaskStatus.TODO
        assignee_username = (row.get('assignee_username') or '').strip().lower()
        assignee = users.get(assignee_username).id if assignee_username in users else None
        due_parsed = None
        if due:
            try:
                due_parsed = datetime.strptime(due.strip(), "%Y-%m-%d").date()
            except:
                due_parsed = None
        t = Task(title=title, description=description, due_date=due_parsed, status=status_val, assignee_id=assignee)
        db.add(t)
    db.commit()
    return RedirectResponse("/dashboard", status_code=302)

@app.get("/export")
def export_csv(db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    tasks = db.exec(select(Task)).all()
    users = {u.id: u for u in db.exec(select(User)).all()}
    def gen():
        yield "title,description,due_date,status,assignee_username\n"
        for t in tasks:
            assignee_username = users[t.assignee_id].username if t.assignee_id and t.assignee_id in users else ''
            due_str = t.due_date.isoformat() if t.due_date else ''
            row = [t.title.replace(',', ' '), t.description.replace('\n',' ').replace(',', ' '), due_str, t.status, assignee_username]
            yield ','.join(row) + "\n"
    return StreamingResponse(gen(), media_type='text/csv', headers={"Content-Disposition": "attachment; filename=tasks.csv"})

@app.get("/jobs", response_class=HTMLResponse)
def jobs_list(request: Request, q: Optional[str] = None, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    stmt = select(Job).order_by(Job.created_at.desc())
    if q:
        like = f"%{q.strip()}%"
        # SQLModel select with where on title using SQLAlchemy .like
        from sqlalchemy import or_
        stmt = stmt.where(Job.title.like(like))
    jobs = db.exec(stmt).all()
    task_counts = {}
    for j in jobs:
        count = db.exec(select(Task).where(Task.job_id == j.id)).all()
        task_counts[j.id] = len(count)
    return templates.TemplateResponse("jobs.html", {"request": request, "title": "Jobs", "current_user": user, "jobs": jobs, "task_counts": task_counts, "q": q or ""})

@app.get("/jobs/new", response_class=HTMLResponse)
def jobs_new_get(request: Request, user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    return templates.TemplateResponse("job_new.html", {"request": request, "title": "New Job", "current_user": user})

@app.post("/jobs/new")
async def jobs_new_post(request: Request, title: str = Form(...), image: UploadFile = File(None), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    image_path = None
    if image and image.filename:
        ext = os.path.splitext(image.filename)[1].lower()
        safe_ext = ext if ext in [".jpg", ".jpeg", ".png", ".webp"] else ".jpg"
        fname = f"{uuid4().hex}{safe_ext}"
        folder = os.path.join(os.path.dirname(__file__), "assets", "images", "jobs")
        os.makedirs(folder, exist_ok=True)
        full_path = os.path.join(folder, fname)
        data = await image.read()
        with open(full_path, "wb") as f:
            f.write(data)
        image_path = f"/assets/images/jobs/{fname}"
    j = Job(title=title, image_path=image_path)
    db.add(j)
    db.commit()
    return RedirectResponse("/jobs", status_code=302)

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    users = db.exec(select(User)).all()
    user_by_id = {u.id: u for u in users}
    tasks = db.exec(select(Task).where(Task.job_id == job_id).order_by(Task.due_date.is_(None), Task.due_date, Task.updated_at.desc())).all()
    return templates.TemplateResponse("job_detail.html", {"request": request, "title": j.title, "current_user": user, "job": j, "tasks": tasks, "user_by_id": user_by_id})

@app.post("/jobs/{job_id}/delete")
def job_delete(request: Request, job_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    if user.role != "manager":
        raise HTTPException(403, "Only managers can delete jobs")
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    # Delete all tasks in this job first
    tasks = db.exec(select(Task).where(Task.job_id == job_id)).all()
    for t in tasks:
        # Delete notes for each task
        notes = db.exec(select(Note).where(Note.task_id == t.id)).all()
        for n in notes:
            db.delete(n)
        db.delete(t)
    db.delete(j)
    db.commit()
    return RedirectResponse("/jobs", status_code=302)

@app.post("/jobs/{job_id}/image")
def job_image_update(request: Request, job_id: int, image: UploadFile = File(...), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    if user.role != "manager":
        raise HTTPException(403, "Only managers can update job images")
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "File must be an image")
    
    # Save the image
    image_path = f"assets/images/jobs/job_{job_id}_{int(time.time())}.{image.filename.split('.')[-1]}"
    full_path = os.path.join(os.path.dirname(__file__), image_path)
    
    with open(full_path, "wb") as f:
        content = image.file.read()
        f.write(content)
    
    # Update job with new image path
    j.image_path = f"/{image_path}"
    db.commit()
    
    return RedirectResponse(f"/jobs/{job_id}", status_code=302)


# Forgot password flow
@app.get("/forgot", response_class=HTMLResponse)
def forgot_get(request: Request, user: Optional[User] = Depends(get_current_user)):
    return templates.TemplateResponse("forgot.html", {"request": request, "title": "Forgot password", "current_user": user})

@app.post("/team/{user_id}/reset-link", response_class=HTMLResponse)
def team_reset_link(request: Request, user_id: int, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    # Only a manager can create a reset link; they pass it on to the team member themselves
    manager_required(user)
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(404, "User not found")
    # Only the newest link should work, so retire this user's older unused ones
    old_resets = db.exec(select(PasswordReset).where(PasswordReset.user_id == target_user.id, PasswordReset.used.is_(False))).all()
    for old in old_resets:
        old.used = True
        db.add(old)
    token = secrets.token_urlsafe(32)
    # Store only the hash, so someone who can read the database can't use it to reset passwords
    pr = PasswordReset(user_id=target_user.id, token=hash_token(token))
    db.add(pr)
    db.commit()
    host = request.headers.get("host", "localhost:8000")
    scheme = "https" if request.url.scheme == "https" else "http"
    reset_url = f"{scheme}://{host}/reset/{token}"
    users = db.exec(select(User)).all()
    return templates.TemplateResponse("team.html", {"request": request, "title": "Team", "current_user": user, "users": users, "reset_url": reset_url, "reset_user": target_user})

@app.get("/reset/{token}", response_class=HTMLResponse)
def reset_get(request: Request, token: str, db: Session = Depends(get_db)):
    pr = db.exec(select(PasswordReset).where(PasswordReset.token == hash_token(token))).first()
    if not pr or pr.used or pr.expires_at < datetime.utcnow():
        return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": "Invalid or expired reset link."})
    return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": None})

@app.post("/reset/{token}")
def reset_post(request: Request, token: str, password: str = Form(...), password2: str = Form(...), db: Session = Depends(get_db)):
    if password != password2:
        return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": "Passwords do not match."})
    pr = db.exec(select(PasswordReset).where(PasswordReset.token == hash_token(token))).first()
    if not pr or pr.used or pr.expires_at < datetime.utcnow():
        return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": "Invalid or expired reset link."})
    u = db.get(User, pr.user_id)
    if not u:
        return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": "User not found."})
    u.password_hash = hash_password(password)
    pr.used = True
    db.add(u)
    db.add(pr)
    db.commit()
    return RedirectResponse("/login", status_code=302)


# Healthcheck / favicon
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/favicon.ico")
def favicon():
    return RedirectResponse("/assets/images/favicon.ico", status_code=302)
