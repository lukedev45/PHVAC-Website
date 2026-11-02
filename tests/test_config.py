"""Startup configuration. Settings are read once, when app.py is first imported, so these
tests import it in a fresh Python process with a controlled environment."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

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
