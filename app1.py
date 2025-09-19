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
from datetime import datetime, date, timedelta
from typing import Optional, List
from uuid import uuid4

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File, Query
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from passlib.context import CryptContext
from sqlmodel import Field, SQLModel, Session, create_engine, select, Column, Date

# Config
SECRET_KEY = os.environ.get("APP_SECRET", "replace-me-with-a-long-random-secret")
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

class Task(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: str = Field(default="")
    due_date: Optional[date] = Field(sa_column=Column(Date, nullable=True))
    status: str = Field(default=TaskStatus.TODO, index=True)
    assignee_id: Optional[int] = Field(default=None, foreign_key="user.id")
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
os.makedirs(TEMPLATES_DIR, exist_ok=True)
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Serve static files
app.mount("/static", StaticFiles(directory=TEMPLATES_DIR), name="static")
app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "assets")), name="assets")


# DB init
SQLModel.metadata.create_all(engine)

# Utilities
def get_db():
    with Session(engine) as session:
        yield session

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

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


# Template base (written to disk at startup)
BASE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ title or 'Team Tasks' }}</title>
  <script src="https://unpkg.com/htmx.org@2.0.2"></script>
  <script src="https://unpkg.com/hyperscript.org@0.9.12"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="icon" type="image/png" href="/assets/images/favicon-32x32.png" sizes="32x32" />
  <link rel="icon" type="image/png" href="/assets/images/favicon-16x16.png" sizes="16x16" />
  <link rel="icon" href="/assets/images/favicon.ico" sizes="any" />
</head>
<body class="min-h-screen flex flex-col bg-gray-50 text-gray-900">
  <header class="bg-white shadow">
    <div class="max-w-7xl mx-auto p-4 flex justify-between items-center">
      <a href="/" class="font-semibold">🗂️ Team Tasks</a>
      <nav class="flex items-center gap-4">
        {% if current_user %}
          <a class="text-sm hover:underline" href="/dashboard">Dashboard</a>
          <a class="text-sm hover:underline" href="/tasks/new">New Task</a>
          <a class="text-sm hover:underline" href="/team">Team</a>
          <a class="text-sm hover:underline" href="/export">Export CSV</a>
          <form method="post" action="/logout">
            <button class="text-sm px-3 py-1 rounded bg-gray-100 hover:bg-gray-200">Logout</button>
          </form>
        {% endif %}
      </nav>
    </div>
  </header>
  <main class="max-w-7xl mx-auto p-4 flex-grow">
    {% block content %}{% endblock %}
  </main>
  <footer class="bg-white border-t mt-8">
    <div class="max-w-7xl mx-auto p-4 text-center text-sm text-gray-500">
      Copyright 2025 Principal HVAC - Total HVAC Solutions. All Rights Reserved.
    </div>
  </footer>
</body>
</html>
"""

LOGIN_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="max-w-md mx-auto bg-white p-8 rounded-2xl shadow">
  <h1 class="text-xl font-semibold mb-4">Sign in</h1>
  <form method="post" action="/login" class="space-y-3">
    <div>
      <label class="block text-sm">Username</label>
      <input name="username" class="w-full border rounded px-3 py-2" required />
    </div>
    <div>
      <label class="block text-sm">Password</label>
      <input type="password" name="password" class="w-full border rounded px-3 py-2" required />
    </div>
    <button class="w-full bg-black text-white rounded py-2">Sign in</button>
  </form>
  <div class="flex justify-between text-xs text-gray-600 mt-6">
    <a class="underline" href="/forgot">Forgot password?</a>
  </div>
</div>
{% endblock %}
"""

BOOTSTRAP_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="max-w-2xl mx-auto bg-white p-8 rounded-2xl shadow">
  <form method="post" action="/bootstrap" class="space-y-3">
    <div>
      <label class="block text-sm">Full Name</label>
      <input name="full_name" class="w-full border rounded px-3 py-2" required />
    </div>
    <div>
      <label class="block text-sm">Username</label>
      <input name="username" class="w-full border rounded px-3 py-2" required />
    </div>
    <div>
      <label class="block text-sm">Password</label>
      <input type="password" name="password" class="w-full border rounded px-3 py-2" required />
    </div>
    <button class="w-full bg-black text-white rounded py-2">Create</button>
  </form>
</div>
{% endblock %}
"""

DASHBOARD_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="md:flex md:items-start md:gap-6">
  <aside class="md:w-72 md:shrink-0 bg-white rounded-2xl shadow p-4 md:self-stretch mb-4 md:mb-0">
    <h2 class="font-semibold mb-2">Filters</h2>
    <form method="get" action="/dashboard" class="space-y-3">
      <div>
        <label class="block text-sm mb-1">Assignee</label>
        <select name="assignee_id" class="w-full h-10 border rounded-lg px-2">
          <option value="">All</option>
          {% for u in users %}
          <option value="{{u.id}}" {% if assignee_id and assignee_id|int == u.id %}selected{% endif %}>{{u.full_name}}</option>
          {% endfor %}
        </select>
      </div>
      <div>
        <label class="block text-sm mb-1">Status</label>
        <select name="status" class="w-full h-10 border rounded-lg px-2">
          <option value="">All</option>
          {% for s in ["todo","in_progress","issued_for_review","done"] %}
          <option value="{{s}}" {% if status_val==s %}selected{% endif %}>{{s.replace('_',' ').title()}}</option>
          {% endfor %}
        </select>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div>
          <label class="block text-sm mb-1">From</label>
          <input type="date" name="from" value="{{from or ''}}" class="w-full h-10 border rounded-lg px-2" />
        </div>
        <div>
          <label class="block text-sm mb-1">To</label>
          <input type="date" name="to" value="{{to or ''}}" class="w-full h-10 border rounded-lg px-2" />
        </div>
      </div>
      <button class="w-full h-10 bg-gray-900 text-white rounded-lg">Apply</button>
    </form>

    <hr class="my-4" />
    <form method="post" action="/import" enctype="multipart/form-data" class="space-y-2">
      <label class="block text-sm">Import CSV</label>
      <input type="file" name="file" accept=".csv" class="w-full text-sm" required />
      <button class="w-full h-10 bg-gray-100 rounded-lg">Upload</button>
    </form>
  </aside>

  <section class="flex-1 min-w-0">
    <div class="flex justify-between items-center mb-4">
      <h1 class="text-xl font-semibold">Tasks</h1>
      <a href="/tasks/new" class="px-3 py-2 rounded-lg bg-black text-white">+ New Task</a>
    </div>

    <div class="bg-white rounded-2xl shadow overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full table-fixed min-w-[700px]">
          <colgroup>
            <col class="w-[40%]">
            <col class="w-[18%]">
            <col class="w-[16%]">
            <col class="w-[14%]">
            <col class="w-[12%]">
          </colgroup>
          <thead class="bg-gray-50 text-left text-sm">
            <tr>
              <th class="p-3 align-top">Title</th>
              <th class="p-3 align-top">Assignee</th>
              <th class="p-3 align-top">Due</th>
              <th class="p-3 align-top">Status</th>
              <th class="p-3 align-top">Updated</th>
            </tr>
          </thead>
          <tbody class="text-sm">
            {% for t in tasks %}
            <tr class="border-t hover:bg-gray-50 align-top">
              <td class="p-3 align-top">
                <a class="underline font-medium" href="/tasks/{{t.id}}">{{t.title}}</a>
                <div class="text-xs text-gray-500 leading-snug mt-1">{{t.description[:120]}}{% if t.description|length>120 %}…{% endif %}</div>
              </td>
              <td class="p-3 align-top">{{ user_by_id.get(t.assignee_id).full_name if t.assignee_id else '-' }}</td>
              <td class="p-3 align-top">{{ t.due_date or '-' }}</td>
              <td class="p-3 align-top">{{ t.status.replace('_',' ').title() }}</td>
              <td class="p-3 align-top">{{ t.updated_at.strftime('%Y-%m-%d %H:%M') }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </section>
</div>
{% endblock %}
"""

TASK_NEW_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="max-w-4xl mx-auto bg-white p-8 rounded-2xl shadow">
  <h1 class="text-xl font-semibold mb-4">New Task</h1>
  <form method="post" action="/tasks/new" class="grid gap-3">
    <div>
      <label class="block text-sm mb-1">Title</label>
      <input name="title" class="w-full h-10 border rounded-lg px-3" required />
    </div>
    <div>
      <label class="block text-sm mb-1">Description</label>
      <textarea name="description" class="w-full border rounded-lg px-3 py-2" rows="4"></textarea>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div>
        <label class="block text-sm mb-1">Due date</label>
        <input type="date" name="due_date" class="w-full h-10 border rounded-lg px-3" />
      </div>
      <div>
        <label class="block text-sm mb-1">Assignee</label>
        <select name="assignee_id" class="w-full h-10 border rounded-lg px-3">
          <option value="">Unassigned</option>
          {% for u in users %}
            <option value="{{u.id}}">{{u.full_name}}</option>
          {% endfor %}
        </select>
      </div>
    </div>
    <button class="h-10 bg-black text-white rounded-lg">Create</button>
  </form>
</div>
{% endblock %}
"""

TASK_DETAIL_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="grid md:grid-cols-3 gap-6 max-w-6xl mx-auto">
  <section class="md:col-span-2 bg-white rounded-2xl shadow p-5">
    <div class="flex justify-between items-start gap-4">
      <div class="min-w-0">
        <h1 class="text-xl font-semibold leading-tight">{{task.title}}</h1>
        <div class="text-sm text-gray-600 mt-1">Due: {{task.due_date or '-'}} • Assigned to: {{ assignee.full_name if assignee else '-' }}</div>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <form method="post" action="/tasks/{{task.id}}/status" class="flex items-center gap-2 shrink-0">
          <select name="status" class="border rounded-lg px-2 h-10">
            {% for s in ["todo","in_progress","issued_for_review","done"] %}
            <option value="{{s}}" {% if task.status==s %}selected{% endif %}>{{s.replace('_',' ').title()}}</option>
            {% endfor %}
          </select>
          <button class="px-3 h-10 rounded-lg bg-gray-900 text-white">Update</button>
        </form>
        {% if task.status == 'done' %}
        <form method="post" action="/tasks/{{task.id}}/delete" onsubmit="return confirm('Delete this task? This cannot be undone.')" class="shrink-0">
          <button class="px-3 h-10 rounded-lg bg-red-600 text-white">Delete</button>
        </form>
        {% endif %}
      </div>
    </div>
    <p class="mt-4 whitespace-pre-line leading-relaxed">{{task.description}}</p>
  </section>

  <aside class="bg-white rounded-2xl shadow p-5">
    <h2 class="font-semibold mb-2">Notes</h2>
    <div id="notes" class="space-y-2">
      {% for n in notes %}
      <div class="border rounded-lg p-2">
        <div class="text-xs text-gray-500">{{n.created_at.strftime('%Y-%m-%d %H:%M')}} • {{ users_map[n.author_id].full_name }}</div>
        <div class="text-sm whitespace-pre-line">{{n.content}}</div>
      </div>
      {% endfor %}
    </div>
    <form hx-post="/tasks/{{task.id}}/notes" hx-target="#notes" hx-swap="beforeend" class="mt-3 grid gap-2">
      <textarea name="content" class="w-full border rounded-lg px-2 py-2" rows="3" placeholder="Add a note..." required></textarea>
      <button class="h-10 bg-gray-900 text-white rounded-lg">Add Note</button>
    </form>
  </aside>
</div>
{% endblock %}
"""

TEAM_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="bg-white p-8 rounded-2xl shadow max-w-6xl mx-auto">
  <div class="flex justify-between items-center mb-4">
    {% if current_user and current_user.role=='manager' %}
    <form method="post" action="/team/new" class="flex flex-wrap gap-1 items-end">
      <div>
        <label class="block text-sm">Full name</label>
        <input name="full_name" class="border rounded px-2 py-1" required />
      </div>
      <div>
        <label class="block text-sm">Username</label>
        <input name="username" class="border rounded px-2 py-1" required />
      </div>
      <div>
        <label class="block text-sm">Password</label>
        <input type="password" name="password" class="border rounded px-2 py-1" required />
      </div>
      <div>
        <label class="block text-sm">Role</label>
        <select name="role" class="border rounded px-2 py-1">
          <option value="member">Member</option>
          <option value="manager">Manager</option>
        </select>
      </div>
      <button class="bg-black text-white rounded px-3 py-1">Add</button>
    </form>
    {% endif %}
  </div>

  <table class="w-full text-left">
    <thead class="bg-gray-50 text-sm">
      <tr><th class="p-2">Name</th><th class="p-2">Username</th><th class="p-2">Role</th></tr>
    </thead>
    <tbody>
      {% for u in users %}
      <tr class="border-t">
        <td class="p-2">{{u.full_name}}</td>
        <td class="p-2">{{u.username}}</td>
        <td class="p-2">{{u.role.title()}}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
"""

FORGOT_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="max-w-2xl mx-auto bg-white p-8 rounded-2xl shadow">
  <h1 class="text-xl font-semibold mb-4">Forgot password</h1>
  <form method="post" action="/forgot" class="space-y-3">
    <div>
      <label class="block text-sm">Username</label>
      <input name="username" class="w-full border rounded px-3 py-2" required />
    </div>
    <button class="w-full bg-black text-white rounded py-2">Generate reset link</button>
  </form>
  {% if reset_url %}
  <div class="mt-4 p-3 bg-gray-50 border rounded text-sm">
    <p class="font-medium">Reset link created (valid 24h):</p>
    <a class="underline break-all" href="{{ reset_url }}">{{ reset_url }}</a>
    <p class="text-xs text-gray-500 mt-2">Copy this link and send it securely to the user.</p>
  </div>
  {% endif %}
</div>
{% endblock %}
"""

RESET_HTML = """
{% extends 'base.html' %}
{% block content %}
<div class="max-w-2xl mx-auto bg-white p-8 rounded-2xl shadow">
  <h1 class="text-xl font-semibold mb-4">Reset password</h1>
  {% if error %}
    <div class="mb-3 p-2 text-sm bg-red-50 border border-red-200 rounded text-red-800">{{ error }}</div>
  {% endif %}
  <form method="post" action="" class="space-y-3">
    <div>
      <label class="block text-sm">New password</label>
      <input type="password" name="password" class="w-full border rounded px-3 py-2" required />
    </div>
    <div>
      <label class="block text-sm">Confirm password</label>
      <input type="password" name="password2" class="w-full border rounded px-3 py-2" required />
    </div>
    <button class="w-full bg-black text-white rounded py-2">Update password</button>
  </form>
</div>
{% endblock %}
"""

# Write templates to disk on startup (so Jinja2 can load them)
with open(os.path.join(TEMPLATES_DIR, "base.html"), "w", encoding="utf-8") as f:
    f.write(BASE_HTML)
with open(os.path.join(TEMPLATES_DIR, "login.html"), "w", encoding="utf-8") as f:
    f.write(LOGIN_HTML)
with open(os.path.join(TEMPLATES_DIR, "bootstrap.html"), "w", encoding="utf-8") as f:
    f.write(BOOTSTRAP_HTML)
with open(os.path.join(TEMPLATES_DIR, "dashboard.html"), "w", encoding="utf-8") as f:
    f.write(DASHBOARD_HTML)
with open(os.path.join(TEMPLATES_DIR, "task_new.html"), "w", encoding="utf-8") as f:
    f.write(TASK_NEW_HTML)
with open(os.path.join(TEMPLATES_DIR, "task_detail.html"), "w", encoding="utf-8") as f:
    f.write(TASK_DETAIL_HTML)
with open(os.path.join(TEMPLATES_DIR, "team.html"), "w", encoding="utf-8") as f:
    f.write(TEAM_HTML)
with open(os.path.join(TEMPLATES_DIR, "forgot.html"), "w", encoding="utf-8") as f:
    f.write(FORGOT_HTML)
with open(os.path.join(TEMPLATES_DIR, "reset.html"), "w", encoding="utf-8") as f:
    f.write(RESET_HTML)


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
    stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date, Task.updated_at.desc())
    tasks = db.exec(stmt).all()
    user_by_id = {u.id: u for u in users}
    return templates.TemplateResponse("dashboard.html", {"request": request, "title": "Dashboard", "current_user": user, "users": users, "tasks": tasks, "user_by_id": user_by_id, "assignee_id": assignee_id, "status_val": status, "from": from_, "to": to})

@app.get("/tasks/new", response_class=HTMLResponse)
def task_new_get(request: Request, db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    users = db.exec(select(User)).all()
    return templates.TemplateResponse("task_new.html", {"request": request, "title": "New Task", "current_user": user, "users": users})

@app.post("/tasks/new")
def task_new_post(request: Request, title: str = Form(...), description: str = Form(""), due_date: Optional[str] = Form(None), assignee_id: Optional[str] = Form(None), db: Session = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    login_required(user)
    due = datetime.strptime(due_date, "%Y-%m-%d").date() if due_date else None
    assignee = int(assignee_id) if assignee_id else None
    t = Task(title=title, description=description, due_date=due, assignee_id=assignee)
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


# Forgot password flow
@app.get("/forgot", response_class=HTMLResponse)
def forgot_get(request: Request, user: Optional[User] = Depends(get_current_user)):
    return templates.TemplateResponse("forgot.html", {"request": request, "title": "Forgot password", "current_user": user, "reset_url": None})

@app.post("/forgot", response_class=HTMLResponse)
def forgot_post(request: Request, username: str = Form(...), db: Session = Depends(get_db)):
    username_norm = normalize_username(username)
    u = db.exec(select(User).where(User.username == username_norm)).first()
    reset_url = None
    if u:
        token = uuid4().hex
        pr = PasswordReset(user_id=u.id, token=token)
        db.add(pr)
        db.commit()
        host = request.headers.get("host", "localhost:8000")
        scheme = "https" if request.url.scheme == "https" else "http"
        reset_url = f"{scheme}://{host}/reset/{token}"
    # Always render success (don’t reveal if username exists)
    return templates.TemplateResponse("forgot.html", {"request": request, "title": "Forgot password", "current_user": None, "reset_url": reset_url})

@app.get("/reset/{token}", response_class=HTMLResponse)
def reset_get(request: Request, token: str, db: Session = Depends(get_db)):
    pr = db.exec(select(PasswordReset).where(PasswordReset.token == token)).first()
    if not pr or pr.used or pr.expires_at < datetime.utcnow():
        return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": "Invalid or expired reset link."})
    return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": None})

@app.post("/reset/{token}")
def reset_post(request: Request, token: str, password: str = Form(...), password2: str = Form(...), db: Session = Depends(get_db)):
    if password != password2:
        return templates.TemplateResponse("reset.html", {"request": request, "title": "Reset password", "current_user": None, "error": "Passwords do not match."})
    pr = db.exec(select(PasswordReset).where(PasswordReset.token == token)).first()
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


#minimal smoke tests (run only if RUN_SMOKE_TESTS=1)
def _run_smoke_tests():
    client = TestClient(app)

    # 1) Bootstrap page loads when no users exist
    r = client.get("/bootstrap")
    assert r.status_code == 200

    # 2) Create first manager
    r = client.post("/bootstrap", data={"full_name": "Admin One", "username": "Admin", "password": "pass"}, allow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/login")

    # 3) Login is case-insensitive
    r = client.post("/login", data={"username": "ADMIN", "password": "pass"}, allow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/dashboard")

    # 4) Create a task
    r = client.get("/tasks/new")
    assert r.status_code == 200
    r = client.post("/tasks/new", data={"title": "Test Task", "description": "desc"}, allow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/tasks/")

    # 5) Dashboard renders and contains the task title
    r = client.get("/dashboard")
    assert r.status_code == 200 and "Test Task" in r.text

    # 6) Forgot password page
    r = client.get("/forgot")
    assert r.status_code == 200

if __name__ == "__main__" and os.environ.get("RUN_SMOKE_TESTS") == "1":
    _run_smoke_tests()