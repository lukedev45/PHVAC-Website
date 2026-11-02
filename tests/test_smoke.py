"""The smoke tests that used to sit at the bottom of app.py (run with RUN_SMOKE_TESTS=1),
ported to pytest. The only change is allow_redirects= -> follow_redirects=, which the
current Starlette TestClient requires."""


def test_smoke(client):
    # 1) Bootstrap page loads when no users exist
    r = client.get("/bootstrap")
    assert r.status_code == 200

    # 2) Create first manager
    r = client.post("/bootstrap", data={"full_name": "Admin One", "username": "Admin", "password": "pass"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/login")

    # 3) Login is case-insensitive
    r = client.post("/login", data={"username": "ADMIN", "password": "pass"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].endswith("/dashboard")

    # 4) Create a task
    r = client.get("/tasks/new")
    assert r.status_code == 200
    r = client.post("/tasks/new", data={"title": "Test Task", "description": "desc"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/tasks/")

    # 5) Dashboard renders and contains the task title
    r = client.get("/dashboard")
    assert r.status_code == 200 and "Test Task" in r.text

    # 6) Forgot password page
    r = client.get("/forgot")
    assert r.status_code == 200
