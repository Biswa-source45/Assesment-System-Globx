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
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
