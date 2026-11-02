"""Startup configuration. Settings are read once, when app.py is first imported, so these
tests import it in a fresh Python process with a controlled environment."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_python(code, tmp_path, **env):
    """Run code in a fresh interpreter from the repo root, against a throwaway database."""
    clean_env = {k: v for k, v in os.environ.items() if k not in ("APP_SECRET", "SESSION_HTTPS_ONLY")}
    clean_env["DB_URL"] = f"sqlite:///{tmp_path / 'app.db'}"
    clean_env.update(env)
    return subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=clean_env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("env", [{}, {"APP_SECRET": ""}], ids=["unset", "empty"])
def test_app_refuses_to_start_without_app_secret(tmp_path, env):
    result = run_python("import app", tmp_path, **env)
    assert result.returncode != 0
    assert "APP_SECRET is not set" in result.stderr
    assert "secrets.token_urlsafe" in result.stderr  # the message says how to generate one
    assert not (tmp_path / "app.db").exists()  # it stops before touching the database


def test_app_starts_with_app_secret(tmp_path):
    result = run_python("import app", tmp_path, APP_SECRET="a-long-random-value")
    assert result.returncode == 0, result.stderr


def cookie_attributes(set_cookie_header):
    return {part.strip().split("=")[0].lower() for part in set_cookie_header.split(";")[1:]}


def test_session_cookie_is_secure_by_default(client, make_user):
    make_user("worker")
    r = client.post("/login", data={"username": "worker", "password": "pw"}, follow_redirects=False)
    assert "secure" in cookie_attributes(r.headers["set-cookie"])


def test_secure_cookie_is_not_sent_back_over_plain_http(make_user):
    make_user("worker")
    http_client = TestClient(app_module.app, base_url="http://testserver")
    http_client.post("/login", data={"username": "worker", "password": "pw"})
    assert http_client.get("/dashboard", follow_redirects=False).headers["location"] == "/login"


def test_session_https_only_0_allows_logins_over_plain_http(tmp_path):
    code = """
import app
from fastapi.testclient import TestClient
from sqlmodel import Session
with Session(app.engine) as db:
    db.add(app.User(username="worker", full_name="Worker", password_hash=app.hash_password("pw")))
    db.commit()
c = TestClient(app.app, base_url="http://testserver")
r = c.post("/login", data={"username": "worker", "password": "pw"}, follow_redirects=False)
print(r.headers["set-cookie"])
print(c.get("/dashboard", follow_redirects=False).status_code)
"""
    result = run_python(code, tmp_path, APP_SECRET="a-long-random-value", SESSION_HTTPS_ONLY="0")
    set_cookie, dashboard_status = result.stdout.strip().splitlines()
    assert "secure" not in cookie_attributes(set_cookie)
    assert dashboard_status == "200"
