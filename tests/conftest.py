"""Shared pytest setup.

app.py creates its database engine from DB_URL when it is imported, so DB_URL has to
point at a throwaway SQLite file *before* the app is imported. pytest loads this file
before any test module, which guarantees the tests never touch a real database, even
if DB_URL is set in your shell.
"""
import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

_TMP_DIR = tempfile.mkdtemp(prefix="phvac-tests-")
TEST_DB_PATH = os.path.join(_TMP_DIR, "test.db")
os.environ["DB_URL"] = f"sqlite:///{TEST_DB_PATH}"  # deliberately overrides any real DB_URL

import app as app_module  # noqa: E402  (must be imported after DB_URL is set)


@pytest.fixture(autouse=True)
def fresh_db():
    """Give every test empty tables. Refuses to run against anything but the temporary database."""
    assert app_module.engine.url.database == TEST_DB_PATH, "tests must only ever use the temporary database"
    SQLModel.metadata.drop_all(app_module.engine)
    SQLModel.metadata.create_all(app_module.engine)


@pytest.fixture(scope="session", autouse=True)
def remove_temp_dir():
    yield
    app_module.engine.dispose()
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def make_user():
    """Create a user directly in the database and return their id."""
    def _make_user(username, role="member", password="pw"):
        with Session(app_module.engine) as db:
            u = app_module.User(username=username, full_name=username.title(), role=role, password_hash=app_module.hash_password(password))
            db.add(u)
            db.commit()
            return u.id
    return _make_user


@pytest.fixture
def login():
    """Return a new client logged in as the given user (fails the test if the login is rejected)."""
    def _login(username, password="pw"):
        c = TestClient(app_module.app)
        r = c.post("/login", data={"username": username, "password": password}, follow_redirects=False)
        assert r.headers["location"].endswith("/dashboard"), f"login failed for {username}"
        return c
    return _login
