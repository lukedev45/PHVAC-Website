# 🗂️ Principal HVAC Task Manager

This project was built for **Principal HVAC** to replace spreadsheet-based task tracking with a simple, web-based tool.  

It provides:
- Task lists with due dates and status tracking  
- Notes attached to tasks (to record updates or changes of plan)  
- Team management with different roles (manager/member)  
- Import/export of task data for easier reporting  

The goal is to make contract timelines clearer and improve communication between team members.

---

## 🌐 Live Demo

A demo version is available here:  
👉 [https://tasks.phvactask.uk](https://tasks.phvactask.uk)

- Anyone can register an account and log in to see how the system works.  
- **Note:** This demo runs on my personal machine. If the server is offline, the site will be temporarily unavailable.  
- Demo accounts and tasks are isolated — they are *not* connected to the real Principal HVAC task database.  

---

## 🛠️ Technical Details
- **Framework:** FastAPI (Python) with Jinja2 templates  
- **Database:** SQLite (simple file-based persistence)  
- **Frontend:** TailwindCSS + HTMX for interactivity  
- **Auth:** Session-based login with password hashing (bcrypt)  
- **Hosting/Access:** Cloudflare Tunnel (so the demo is accessible via the domain)  

---

## 🚀 Getting Started (for your own team)

Clone the repo and install dependencies:
```bash

git clone https://github.com/yourusername/hvac-task-manager.git
cd hvac-task-manager
pip install -r requirements.txt

```

To run locally use this command:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```
