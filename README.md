# 🗂️ Principal HVAC Task Manager

This project was built for **Principal HVAC** to replace spreadsheet-based task tracking with a simple, web-based tool.  

It provides:
- Task lists with due dates and status tracking  
- Notes attached to tasks (to record updates or changes of plan)  
- Team management with different roles (manager/member)  
- Import/export of task data for easier reporting  

The goal is to make contract timelines clearer and improve communication between team members.

---

## 🛠️ Technical Details
- **Framework:** FastAPI (Python) with Jinja2 templates  
- **Database:** SQLite (simple file-based persistence)  
- **Frontend:** TailwindCSS + HTMX for interactivity  
- **Auth:** Session-based login with password hashing (bcrypt)  
- **Hosting/Access:** Cloudflare Tunnel (so the app can be reached through a domain without opening ports)  

---

## 🚀 Getting Started (for your own team)

You need **Python 3.12**. The pinned packages don't support Python 3.14 yet.

Clone the repo and install dependencies into a virtual environment:
```bash
git clone https://github.com/lukedev45/PHVAC-Website.git
cd PHVAC-Website
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

The app signs its login cookies with `APP_SECRET` and refuses to start without it. Generate a long random value once and keep using the same one (changing it logs everyone out):
```bash
export APP_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')"
```

To run locally use this command:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

The login cookie is only sent over HTTPS by default. If you open the app over plain HTTP, for example from another computer on your network (`http://192.168.x.x:8000`), turn that off for the run or logins won't stick:
```bash
SESSION_HTTPS_ONLY=0 uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

On first start there are no users: open `/bootstrap` to create the first manager account. Data is stored in `tasks.db` in the current directory unless you set `DB_URL` (for example `DB_URL=sqlite:////srv/phvac/tasks.db`).

---

## 🔑 Password Resets

There is no self-service reset, because anyone could use it to take over an account. Instead:

1. A manager opens the **Team** page and clicks **Reset link** next to the person.
2. The page shows a link that is valid for 24 hours. The manager sends it to that person over a channel they trust.
3. The person opens the link and chooses a new password.

Each link works once, and creating a new link cancels any earlier unused one for the same person. The database stores only a hash of each link's token. Managers can also create a link for themselves, which is how anyone changes their own password.

---

## 🧪 Running the Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use a temporary SQLite database (they never touch `tasks.db`) and set their own `APP_SECRET`. GitHub Actions runs them on every push and pull request.
