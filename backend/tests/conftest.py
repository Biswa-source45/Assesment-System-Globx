import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="oap-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.sqlite3")
os.environ.setdefault("STORAGE_DIR", os.path.join(_tmp, "storage"))
os.environ.setdefault("SANDBOX_DIR", os.path.join(_tmp, "sandbox"))
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-used-anywhere-else")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ["SMTP_HOST"] = ""  # forced, never setdefault: the repo .env may hold the real mail server, and no test may ever send a real mail
os.environ["SMTP_USER"] = os.environ["SMTP_PASSWORD"] = ""
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
