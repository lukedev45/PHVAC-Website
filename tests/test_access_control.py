"""Login and manager checks on every state-changing route.

Logged-out users must be sent to the login page, and members must get 403 from the
manager-only actions. /login, /logout, /bootstrap (only works while there are no users)
and /reset/{token} (the token is the credential) are public on purpose.

Each request carries valid form data, so it gets past FastAPI's form validation and
reaches the route's own check."""
import pytest
from sqlmodel import Session

import app as app_module

PNG = ("job.png", b"not really a png", "image/png")
CSV = ("tasks.csv", b"title\nImported task\n", "text/csv")

# (path, form data, files)
LOGIN_REQUIRED = [
    ("/tasks/new", {"title": "T"}, None),
    ("/tasks/1/status", {"status": "done"}, None),
    ("/tasks/1/delete", {}, None),
    ("/tasks/1/notes", {"content": "hello"}, None),
    ("/import", {}, {"file": CSV}),
    ("/jobs/new", {"title": "J"}, None),
]
MANAGER_ONLY = [
    ("/tasks/1/assign", {"assignee_id": ""}, None),
    ("/team/new", {"full_name": "New", "username": "new", "password": "pw", "role": "manager"}, None),
    ("/team/1/delete", {}, None),
    ("/team/1/reset-link", {}, None),
    ("/jobs/1/delete", {}, None),
    ("/jobs/1/image", {}, {"image": PNG}),
]


def cases(routes):
    return [pytest.param(path, data, files, id=path) for path, data, files in routes]


@pytest.mark.parametrize("path, data, files", cases(LOGIN_REQUIRED + MANAGER_ONLY))
def test_logged_out_users_are_sent_to_login(client, path, data, files):
    r = client.post(path, data=data, files=files, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"


@pytest.mark.parametrize("path, data, files", cases(MANAGER_ONLY))
def test_members_cannot_use_manager_actions(make_user, login, path, data, files):
    # Real targets (user 1, job 1, task 1), so a missing check would change something instead of returning 404
    make_user("boss", role="manager")
    make_user("worker")
    with Session(app_module.engine) as db:
        db.add(app_module.Job(title="Job"))
        db.add(app_module.Task(title="Task", job_id=1))
        db.commit()
    r = login("worker").post(path, data=data, files=files, follow_redirects=False)
    assert r.status_code == 403
