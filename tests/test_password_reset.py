"""Password resets: only a manager can create a reset link, and passes it on to the team member."""
import re

from sqlmodel import Session, select

import app as app_module


def reset_rows():
    with Session(app_module.engine) as db:
        return db.exec(select(app_module.PasswordReset)).all()


def token_from(html):
    match = re.search(r"/reset/([A-Za-z0-9_\-]+)", html)
    return match.group(1) if match else None


def test_anonymous_user_cannot_get_a_reset_link(client, make_user):
    boss_id = make_user("boss", role="manager")
    # The old public form that handed out links is gone...
    r = client.post("/forgot", data={"username": "boss"})
    assert r.status_code == 405 and token_from(r.text) is None
    # ...and the manager action sends anonymous users to the login page
    r = client.post(f"/team/{boss_id}/reset-link", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    assert reset_rows() == []


def test_forgot_page_tells_people_to_ask_their_manager(client):
    r = client.get("/forgot")
    assert r.status_code == 200
    assert "Ask your manager" in r.text and "<form" not in r.text


def test_member_cannot_generate_a_reset_link(make_user, login):
    boss_id = make_user("boss", role="manager")
    make_user("worker")
    r = login("worker").post(f"/team/{boss_id}/reset-link")
    assert r.status_code == 403
    assert reset_rows() == []


def test_manager_can_generate_a_reset_link(client, make_user, login):
    make_user("boss", role="manager")
    worker_id = make_user("worker", password="old-password")
    r = login("boss").post(f"/team/{worker_id}/reset-link")
    assert r.status_code == 200 and "Reset link for Worker (valid 24h)" in r.text
    token = token_from(r.text)
    assert token
    r = client.post(f"/reset/{token}", data={"password": "new-password", "password2": "new-password"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login"
    login("worker", "new-password")
